"""TrackNet V2 アーキテクチャ定義
出典: Chang-Chia-Chi/TrackNet (MIT License)
https://github.com/Chang-Chia-Chi/TrackNet

入力 : (N, 9, H, W) — 3フレーム × RGB 3ch をチャネル方向に結合
出力 : (N, 1, H, W) — シャトル位置のヒートマップ（0~1）
標準解像度: 512 × 288

ONNX変換コマンド（要PyTorch）:
  python -m backend.tracknet.setup export
"""
try:
    import torch
    import torch.nn as nn
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False


if _TORCH_AVAILABLE:
    def _vgg_block(in_ch: int, out_ch: int, n_conv: int) -> "nn.Sequential":
        layers = []
        for i in range(n_conv):
            layers += [
                nn.Conv2d(in_ch if i == 0 else out_ch, out_ch, 3, padding=1),
                nn.BatchNorm2d(out_ch),
                nn.ReLU(inplace=True),
            ]
        layers.append(nn.MaxPool2d(2, 2))
        return nn.Sequential(*layers)

    def _up_block(in_ch: int, out_ch: int, n_conv: int) -> "nn.Sequential":
        layers = [nn.Upsample(scale_factor=2, mode="bilinear", align_corners=True)]
        for i in range(n_conv):
            layers += [
                nn.Conv2d(in_ch if i == 0 else out_ch, out_ch, 3, padding=1),
                nn.BatchNorm2d(out_ch),
                nn.ReLU(inplace=True),
            ]
        return nn.Sequential(*layers)

    class TrackNetV2(nn.Module):
        """TrackNet V2: VGGベースのエンコーダ・デコーダ。
        Chang-Chia-Chi/TrackNet (MIT) の実装に基づく。"""

        def __init__(self):
            super().__init__()
            # Encoder（VGG-like）
            self.enc1 = _vgg_block(9,   64,  2)   # /2  → 256×144
            self.enc2 = _vgg_block(64,  128, 2)   # /4  → 128×72
            self.enc3 = _vgg_block(128, 256, 3)   # /8  →  64×36
            self.enc4 = _vgg_block(256, 512, 3)   # /16 →  32×18
            self.enc5 = _vgg_block(512, 512, 3)   # /32 →  16×9

            # Decoder（bilinear upsample + conv）
            self.dec4 = _up_block(512, 256, 2)    # /16
            self.dec3 = _up_block(256, 128, 2)    # /8
            self.dec2 = _up_block(128, 64,  2)    # /4
            self.dec1 = _up_block(64,  32,  2)    # /2
            self.dec0 = _up_block(32,  16,  2)    # /1

            # 出力ヘッド
            self.head = nn.Sequential(
                nn.Conv2d(16, 1, 1),
                nn.Sigmoid(),
            )

        def forward(self, x):
            e1 = self.enc1(x)
            e2 = self.enc2(e1)
            e3 = self.enc3(e2)
            e4 = self.enc4(e3)
            e5 = self.enc5(e4)

            d = self.dec4(e5)
            d = self.dec3(d)
            d = self.dec2(d)
            d = self.dec1(d)
            d = self.dec0(d)
            return self.head(d)
