"""
DataLoader to extract tiles from a slide
"""
from PIL import Image
from preprocessing.tile_generation import generate_grid_br as generate_grid
import torch
import torch.utils.data as data
import numpy as np
import skimage.io


class BiopsySlides(data.Dataset):
    def __init__(self, params, test_df, transform, tile_normalizer):
        self.params = params
        self.test_df = test_df
        self.test_slides_dir = params.test_slides_dir
        self.transform = transform
        self.tile_normalizer = tile_normalizer

    def __len__(self):
        return len(self.test_df)

    def __getitem__(self, ix):
        slide_info = self.test_df.iloc[ix]
        tile_generator = generate_grid.TileGeneratorGridBr(self.test_slides_dir, f"{slide_info.image_id}.tiff",
                                                           None, verbose=False)
        norm_tiles, _, _ = tile_generator.extract_top_tiles(self.params.im_size, self.params.overlap,
                                                         self.params.ts_thres, self.params.dw_rate,
                                                         self.params.top_n, normalizer=self.tile_normalizer)
        instances = torch.FloatTensor(len(norm_tiles),
                                      self.params.num_channels, self.params.input_size, self.params.input_size)
        for i, norm_tile in enumerate(norm_tiles):
            if self.transform:
                instances[i, :, :, :] = self.transform(norm_tile)
        del norm_tiles
        return instances, slide_info.image_id



class BiopsySlidesBatch(BiopsySlides):
    def __init__(self, params, test_df, transform, tile_normalizer):
        super().__init__(params, test_df, transform, tile_normalizer)

    def __len__(self):
        return len(self.test_df)

    def __getitem__(self, ix):
        slide_info = self.test_df.iloc[ix]
        tile_generator = generate_grid.TileGeneratorGridBr(self.test_slides_dir, f"{slide_info.image_id}.tiff",
                                                           None, verbose=False)
        norm_tiles, _, _ = tile_generator.extract_top_tiles(self.params.im_size, self.params.overlap,
                                                         self.params.ts_thres, self.params.dw_rate,
                                                         self.params.top_n, normalizer=self.tile_normalizer)
        instances = torch.FloatTensor(len(norm_tiles),
                                      self.params.num_channels, self.params.input_size, self.params.input_size)
        for i, norm_tile in enumerate(norm_tiles):
            if self.transform:
                instances[i, :, :, :] = self.transform(norm_tile)
        del norm_tiles
        if len(instances) < self.params.top_n:
            pad_len = self.params.top_n - len(instances)
            instances = \
                torch.cat([instances, torch.zeros(pad_len, 3, self.params.input_size, self.params.input_size)], dim=0)
        return instances, slide_info.image_id


class BiopsySlidesLowest(data.Dataset):
    def __init__(self, params, test_df, transform):
        self.params = params
        self.test_df = test_df
        self.test_slides_dir = params.test_slides_dir
        self.transform = transform

    def __len__(self):
        return len(self.test_df)

    def _tile(self, img, sz, N):
        shape = img.shape
        pad0, pad1 = (sz - shape[0] % sz) % sz, (sz - shape[1] % sz) % sz
        img = np.pad(img, [[pad0 // 2, pad0 - pad0 // 2], [pad1 // 2, pad1 - pad1 // 2], [0, 0]],
                     constant_values=255)

        img = img.reshape(img.shape[0] // sz, sz, img.shape[1] // sz, sz, 3)
        img = img.transpose(0, 2, 1, 3, 4).reshape(-1, sz, sz, 3)

        if len(img) < N:
            img = np.pad(img, [[0, N - len(img)], [0, 0], [0, 0], [0, 0]], constant_values=255)
        idxs = np.argsort(img.reshape(img.shape[0], -1).sum(-1))[:N]
        img = img[idxs]
        return img, idxs

    def __getitem__(self, ix):
        slide_info = self.test_df.iloc[ix]
        img = skimage.io.MultiImage(f"{self.test_slides_dir}/{slide_info.image_id}.tiff")[-1]
        tiles, tile_idxs = self._tile(img, self.params.input_size, self.params.top_n)
        instances = torch.FloatTensor(len(tiles),
                                      self.params.num_channels, self.params.input_size, self.params.input_size)
        for i, tile in enumerate(tiles):
            if self.transform:
                instances[i, :, :, :] = self.transform(tile)
        return instances, slide_info.image_id, tile_idxs