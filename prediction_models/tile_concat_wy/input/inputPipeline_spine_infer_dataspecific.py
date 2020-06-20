import os,sys
import warnings
warnings.filterwarnings("ignore")
from PIL import Image
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset, DataLoader
from torchvision import transforms
from torch.utils.data.sampler import RandomSampler, SequentialSampler
from collections import OrderedDict
import skimage.io
import cv2
from spine import spine, tile, tile_rect, tile_img, tile_rect_img

def get_tiles(img, tile_size, n_tiles, mode=0):
    result = []
    h, w, c = img.shape
    pad_h = (tile_size - h % tile_size) % tile_size + ((tile_size * mode) // 2)
    pad_w = (tile_size - w % tile_size) % tile_size + ((tile_size * mode) // 2)

    img2 = np.pad(img, [[pad_h // 2, pad_h - pad_h // 2], [pad_w // 2, pad_w - pad_w // 2], [0, 0]],
                  mode='constant', constant_values=255)
    img3 = img2.reshape(
        img2.shape[0] // tile_size,
        tile_size,
        img2.shape[1] // tile_size,
        tile_size,
        3
    )

    img3 = img3.transpose(0, 2, 1, 3, 4).reshape(-1, tile_size, tile_size, 3)
    n_tiles_with_info = (img3.reshape(img3.shape[0], -1).sum(1) < tile_size ** 2 * 3 * 255).sum()
    if len(img3) < n_tiles:
        img3 = np.pad(img3, [[0, n_tiles - len(img3)], [0, 0], [0, 0], [0, 0]], mode='constant', constant_values=255)
    idxs = np.argsort(img3.reshape(img3.shape[0], -1).sum(-1))[:n_tiles]
    img3 = img3[idxs]
    for i in range(len(img3)):
        result.append({'img': img3[i], 'idx': i})
    return result, n_tiles_with_info >= n_tiles

class PandaPatchDatasetInfer(Dataset):
    """
        gls2isu = {"0+0":0,'negative':0,'3+3':1,'3+4':2,'4+3':3,'4+4':4,'3+5':4,'5+3':4,'4+5':5,'5+4':5,'5+5':5}
        """
    gls = {"0+0": [0, 0], 'negative': [0, 0], '3+3': [1, 1], '3+4': [1, 2], '4+3': [2, 1], '4+4': [2, 2],
           '3+5': [1, 3], '5+3': [3, 1], '4+5': [2, 3], '5+4': [3, 2], '5+5': [3, 3]}
    """Panda Tile dataset. With fixed tiles for each slide."""

    def __init__(self, csv_file, image_dir, image_size, N=36, transform=None, rand=False):
        """
        Args:
            csv_file (string): Path to the csv file with annotations.
            image_dir (string): Directory with all the images.
            N (interger): Number of tiles selected for each slide.
            transform (callable, optional): Optional transform to be applied
                on a sample.
        """
        self.train_csv = pd.read_csv(csv_file)
        self.image_dir = image_dir
        self.image_size = image_size
        self.transform = transform
        self.N = N
        self.rand = rand

    def __len__(self):
        return len(self.train_csv)

    def __getitem__(self, idx):
        result = OrderedDict()
        kwargs = {'step_size': 5,
                  'h_step_size': 0.15,
                  'patch_size': 33,
                  'slide_thresh': 0.1,
                  'overlap_thresh': 0.5,
                  'min_size': 1,
                  'iou_cover_thresh': 0.84,
                  'low_tile_mode': 'random'}
        name = self.train_csv.image_id[idx]
        datacenter = self.train_csv.loc[idx, 'data_provider']
        biopsy = skimage.io.MultiImage(os.path.join(self.image_dir, name + '.tiff'))
        img = biopsy[1]
        if datacenter == "radboud":
            img0 = cv2.resize(biopsy[-1], (int(biopsy[-1].shape[1] / 2), int(biopsy[-1].shape[0] / 2)))
            spine_result = spine(img0, **kwargs)
            ra = np.sum(np.multiply((spine_result['patch_mask'] > 0).astype('int'), spine_result['mask'])) / np.sum(spine_result['mask'])
            if ra < kwargs['iou_cover_thresh'] or len(spine_result['tile_location']) < self.N:
                tiles, ra, _ = tile_rect_img(img, spine_result['mask'], sz = self.image_size,
                                         N = self.N, overlap_ratio=0.6, mode=kwargs['low_tile_mode'])
            else:
                tiles = tile_img(img, spine_result['tile_location'], spine_result['IOU'], sz = self.image_size, N = self.N)
            imgs = []
            for i in range(self.N):
                img = tiles[i]['img']
                img = Image.fromarray(img).convert('RGB')
                img = np.asarray(img)
                imgs.append({'img': img, 'idx': i})
        else:
            imgs, OK = get_tiles(img, self.image_size, self.N, mode=0)

        if self.rand:  ## random shuffle the order of tiles
            idxes = np.random.choice(list(range(self.N)), self.N, replace=False)
        else:
            idxes = list(range(self.N))

        n_row_tiles = int(np.sqrt(self.N))

        images = np.zeros((self.image_size * n_row_tiles, self.image_size * n_row_tiles, 3))
        for h in range(n_row_tiles):
            for w in range(n_row_tiles):
                i = h * n_row_tiles + w
                if len(imgs) > idxes[i]:
                    this_img = imgs[idxes[i]]['img']
                else:
                    this_img = np.ones((self.image_size, self.image_size, 3)).astype(np.uint8) * 255
                this_img = 255 - this_img  ## todo: see how this trik plays out
                if self.transform is not None:
                    this_img = self.transform(image=this_img)['image']
                h1 = h * self.image_size
                w1 = w * self.image_size
                images[h1:h1 + self.image_size, w1:w1 + self.image_size] = this_img

        if self.transform is not None:
            images = self.transform(image=images)['image']
        images = images.astype(np.float32)
        images /= 255
        images = images.transpose(2, 0, 1)
        result['img'] = torch.tensor(images)
        result['datacenter'] = datacenter
        result['name'] = name
        return result