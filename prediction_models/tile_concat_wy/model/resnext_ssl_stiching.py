## system package
import os, sys
# os.environ["CUDA_DEVICE_ORDER"]="PCI_BUS_ID"
# os.environ["CUDA_VISIBLE_DEVICES"]="0"  # specify which GPU(s) to be used
sys.path.append('../')
import warnings
warnings.filterwarnings("ignore")
## general package
import torch
import torch.nn as nn
from collections import OrderedDict
from fastai.vision import *
## custom package
from utiles.mishactivation import Mish
from utiles.hubconf import *


class Model(nn.Module):
    def __init__(self, arch='resnext50_32x4d_ssl', n=5, GleasonScore = False):
        super().__init__()
        m = torch.hub.load('facebookresearch/semi-supervised-ImageNet1K-models', arch)
        self.enc = nn.Sequential(*list(m.children())[:-2])
        nc = list(m.children())[-1].in_features
        self.head = nn.Sequential(AdaptiveConcatPool2d(), Flatten(), nn.Linear(2 * nc, 512),
                                  Mish(), nn.BatchNorm1d(512), nn.Dropout(0.5), nn.Linear(512, n))
        self.GLS = GleasonScore
        if self.GLS:
            self.prim = nn.Sequential(AdaptiveConcatPool2d(), Flatten(), nn.Linear(2 * nc, 512),
                                      Mish(), nn.BatchNorm1d(512), nn.Dropout(0.5), nn.Linear(512, 4))
            self.sec = nn.Sequential(AdaptiveConcatPool2d(), Flatten(), nn.Linear(2 * nc, 512),
                                  Mish(), nn.BatchNorm1d(512), nn.Dropout(0.5), nn.Linear(512, 4))

    def forward(self, x):
        """
        x: [bs, N, 3, h, w]
        x_out: [bs, N]
        """
        result = OrderedDict()
        # bs, c, h, w = x.shape
        x = self.enc(x)  # x: bs*N x C x 4 x 4
        _, c, h, w = x.shape
        # print("1", x.shape)
        y = self.head(x)  # x: bs x n
        # print("2", x.shape)
        result['out'] = y
        if self.GLS:
            primary_gls = self.prim(x)
            sec_gls = self.sec(x)
            result['primary_gls'] = primary_gls
            result['secondary_gls'] = sec_gls
        return result

class Model_Infer(nn.Module):
    def __init__(self, arch='resnext50_32x4d', n=5):
        super().__init__()
        # m = torch.hub.load('facebookresearch/semi-supervised-ImageNet1K-models', arch)
        m = self._resnext(semi_supervised_model_urls[arch], Bottleneck, [3, 4, 6, 3], False,
                     progress=False, groups=32, width_per_group=4)
        self.enc = nn.Sequential(*list(m.children())[:-2])
        nc = list(m.children())[-1].in_features
        self.head = nn.Sequential(AdaptiveConcatPool2d(), Flatten(), nn.Linear(2 * nc, 512),
                                  Mish(), nn.BatchNorm1d(512), nn.Dropout(0.5), nn.Linear(512, n))

    def _resnext(self, url, block, layers, pretrained, progress, **kwargs):
        model = ResNet(block, layers, **kwargs)
        #state_dict = load_state_dict_from_url(url, progress=progress)
        #model.load_state_dict(state_dict)
        return model
    def forward(self, x):
        """
        x: [bs, N, 3, h, w]
        x_out: [bs, N]
        """
        result = OrderedDict()
        # bs, c, h, w = x.shape
        x = self.enc(x)  # x: bs*N x C x 4 x 4
        _, c, h, w = x.shape
        # print("1", x.shape)
        x = self.head(x)  # x: bs x n
        # print("2", x.shape)
        result['out'] = x
        return result

if __name__ == "__main__":
    img = torch.rand([4, 3, 6 * 256, 6 * 256])
    model = Model_Infer()
    output = model(img)
    print(output['out'].shape)