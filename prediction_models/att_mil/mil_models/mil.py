import torchvision.models as models
from prediction_models.att_mil.utils import model_utils, init_helper
import torch.nn as nn
import torch
from fastai.vision import *
from prediction_models.tile_concat_wy.utiles import mishactivation
import torch.nn.functional as F


def config_encoder(input_size, num_classes, arch, pretrained):
    if "ssl" in arch:
        encoder = torch.hub.load('facebookresearch/semi-supervised-ImageNet1K-models', arch)
    else:
        encoder_name = models.__dict__[arch]
        encoder = encoder_name(pretrained=pretrained)
    # Convert encoders to have a features and a classifier
    # The classifier should be reinitialized to accommodate different number of classes
    if arch.startswith("vgg"):
        feature_dim = model_utils.config_vgg_layers(encoder, arch, input_size, num_classes)

    elif arch.startswith("res"):
        feature_dim = model_utils.config_resnet_layers(encoder, arch, num_classes)
    else:
        raise NotImplementedError(f"{arch} Haven't implemented")
    return encoder, feature_dim


class AttMIL(nn.Module):
    def __init__(self, base_encoder, pretrained, arch, input_size, feature_dim, mil_params):
        super(AttMIL, self).__init__()
        self.tile_encoder = base_encoder
        self.feature_dim = feature_dim
        self.pretrained = pretrained
        self.hp = {"input_size": input_size,  "encoder_arch": arch,
                   "feature_dim": feature_dim, "pretrained": pretrained,
                   "mil_params": mil_params, "arch": arch}
        self.mil_params = mil_params

        self.instance_embed = self._config_instance_embed()

        self.embed_bag_feat, self.attention = self._config_attention()
        self.slide_classifier = self._config_classifier()
        self._initialize()

    def _config_instance_embed(self):
        instance_embed = nn.Sequential(
            nn.AdaptiveAvgPool2d(output_size=(self.mil_params['mil_in_feat_size'],
                                              self.mil_params['mil_in_feat_size'])),
            nn.Conv2d(self.feature_dim, self.mil_params["instance_embed_dim"],
                      kernel_size=1, stride=1, padding=0))
        return instance_embed

    def _config_attention(self):
        embed_bag_feat = nn.Sequential(
            nn.Linear(self.mil_params["instance_embed_dim"] *
                      self.mil_params['mil_in_feat_size'] * self.mil_params['mil_in_feat_size'],
                      self.mil_params['bag_embed_dim']),
            nn.ReLU(),
            nn.Dropout(),
        )

        attention = nn.Sequential(
            nn.Linear(self.mil_params['bag_embed_dim'], self.mil_params['bag_hidden_dim']),
            nn.Tanh(),
            nn.Dropout(),
            nn.Linear(self.mil_params["bag_hidden_dim"], self.mil_params["n_slide_classes"])
        )
        return embed_bag_feat, attention

    def _config_classifier(self):
        classifier = nn.Sequential(
            nn.Linear(self.mil_params["bag_embed_dim"] * self.mil_params["n_slide_classes"],
                      self.mil_params["n_slide_classes"]),
        )
        return classifier

    def _initialize(self):
        if not self.pretrained:
            for m in self.tile_encoder.modules():
                init_helper.weight_init(m)
        for m in self.instance_embed.modules():
            init_helper.weight_init(m)
        for m in self.embed_bag_feat.modules():
            init_helper.weight_init(m)
        for m in self.slide_classifier.modules():
            init_helper.weight_init(m)

    def forward(self, tiles, phase="regular"):
        feats = self.tile_encoder.features(tiles.contiguous())
        tiles_probs = self.tile_encoder.classifier(feats)

        feats = self.instance_embed(feats)
        feats = self.embed_bag_feat(feats.view(feats.size(0), -1).contiguous())

        if phase == 'extract_feats':
            return feats

        raw_atts = self.attention(feats)
        atts = torch.transpose(raw_atts, 1, 0)
        atts = F.softmax(atts, dim=1)

        # size: 1 * bag_embed_size
        weighted_feats = torch.mm(atts, feats)
        probs = (self.slide_classifier(weighted_feats.view(-1).contiguous())).unsqueeze(dim=0)

        return probs, tiles_probs, atts


class AttMILBatch(AttMIL):
    def __init__(self, base_encoder, pretrained, arch, input_size, feature_dim, mil_params):
        super().__init__(base_encoder, pretrained, arch, input_size, feature_dim, mil_params)
        self.softmax = nn.Softmax(dim=1)

    def _config_classifier(self):
        classifier = nn.Sequential(nn.Linear(self.mil_params["bag_embed_dim"], 512),
                                   mishactivation.Mish(), nn.BatchNorm1d(512), nn.Dropout(0.5),
                                   nn.Linear(512, self.mil_params["n_slide_classes"]))
        return classifier

    def forward(self, tiles, phase="regular"):
        batch_size, n_tiles, channel, h, w = tiles.shape
        feats = self.tile_encoder.features(tiles.view(-1, channel, h, w).contiguous())
        if phase == "regular":
            tiles_probs = self.tile_encoder.classifier(feats)
        else:
            tiles_probs = None

        feats = self.instance_embed(feats)
        feats = self.embed_bag_feat(feats)

        if phase == 'extract_feats':
            return feats.view(batch_size, n_tiles, -1)

        raw_atts = self.attention(feats)
        atts = self.softmax(raw_atts.view(batch_size, n_tiles, -1))
        weighted_feats = torch.matmul(atts.permute(0, 2, 1), feats.view(batch_size, n_tiles, -1))
        weighted_feats = torch.squeeze(weighted_feats, dim=1)
        probs = (self.slide_classifier(weighted_feats))

        return probs, tiles_probs, atts


class AttMILBatchV2(AttMIL):
    def __init__(self, base_encoder, pretrained, arch, input_size, feature_dim, mil_params):
        super().__init__(base_encoder, pretrained, arch, input_size, feature_dim, mil_params)
        self.softmax = nn.Softmax(dim=1)

    def _config_instance_embed(self):
        instance_embed = nn.Sequential(
            AdaptiveConcatPool2d(), Flatten())
        return instance_embed

    def _config_attention(self):
        embed_bag_feat = nn.Sequential(
            nn.Linear(2 * self.feature_dim,
                      self.mil_params['bag_embed_dim']),
            mishactivation.Mish(), nn.Dropout(0.5)
        )

        attention = nn.Sequential(
            nn.Linear(self.mil_params['bag_embed_dim'], self.mil_params['bag_hidden_dim']),
            nn.Tanh(),
            nn.Dropout(),
            nn.Linear(self.mil_params["bag_hidden_dim"], 1)
        )
        return embed_bag_feat, attention

    def _config_classifier(self):
        classifier = nn.Sequential(
            nn.Linear(self.mil_params["bag_embed_dim"],
                      self.mil_params["n_slide_classes"]),
        )
        return classifier

    def forward(self, tiles, phase="regular"):
        batch_size, n_tiles, channel, h, w = tiles.shape
        feats = self.tile_encoder.features(tiles.view(-1, channel, h, w).contiguous())
        if phase == "regular":
            tiles_probs = self.tile_encoder.classifier(feats)
        else:
            tiles_probs = None

        feats = self.instance_embed(feats)
        feats = self.embed_bag_feat(feats)

        if phase == 'extract_feats':
            return feats.view(batch_size, n_tiles, -1)

        raw_atts = self.attention(feats)
        atts = self.softmax(raw_atts.view(batch_size, n_tiles, -1))
        weighted_feats = torch.matmul(atts.permute(0, 2, 1), feats.view(batch_size, n_tiles, -1))
        weighted_feats = torch.squeeze(weighted_feats, dim=1)
        probs = (self.slide_classifier(weighted_feats))

        return probs, tiles_probs, atts


class PoolMilBatch(nn.Module):
    def __init__(self, base_encoder, pretrained, arch, input_size, feature_dim, mil_params):
        super(PoolMilBatch, self).__init__()
        self.tile_encoder = base_encoder
        self.feature_dim = feature_dim
        self.pretrained = pretrained
        self.hp = {"input_size": input_size, "encoder_arch": arch,
                   "feature_dim": feature_dim, "pretrained": pretrained,
                   "mil_params": mil_params, "arch": arch}
        self.slide_classifier = nn.Sequential(AdaptiveConcatPool2d(), Flatten(), nn.Linear(2 * feature_dim, 512),
                                              mishactivation.Mish(), nn.BatchNorm1d(512), nn.Dropout(0.5),
                                              nn.Linear(512, self.mil_params['n_slide_classes']))

    def forward(self, tiles, phase="regular"):
        bs, n, c, h, w = tiles.shape
        tiles = tiles.view(-1, c, h, w)  # x: bs*N x 3 x 128 x 128
        tiles = self.tile_encoder(tiles)  # x: bs*N x C x 4 x 4
        _, c, h, w = tiles.shape

        # concatenate the output for tiles into a single map
        tiles = tiles.view(bs, n, c, h, w).permute(0, 2, 1, 3, 4).contiguous().view(-1, c, h * n, w)  # x: bs x C x N*4 x 4
        out = self.head(tiles)  # x: bs x n
        return out



