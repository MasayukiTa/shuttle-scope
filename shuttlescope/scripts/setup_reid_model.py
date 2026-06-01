"""OSNet x0_25 ReID model setup script (Phase 4).

torchreid 経由で OSNet x0_25 (約 10 MB) を取得し、ONNX export して
`backend/models/osnet_x0_25_reid.onnx` に配置する。1 度だけ実行する。

Usage:
    python shuttlescope/scripts/setup_reid_model.py

依存:
    pip install torchreid gdown
    (torch + onnx は既存 venv にあれば OK)

出力:
    backend/models/osnet_x0_25_reid.onnx (約 10 MB、gitignore)
    - 入力: NCHW float32 [N, 3, 256, 128] ImageNet normalized
    - 出力: [N, 512] feature vector (L2 正規化前)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = _REPO_ROOT / "backend" / "models" / "osnet_x0_25_reid.onnx"


def main() -> int:
    try:
        import torch  # noqa: F401
    except ImportError:
        logger.error("torch が必要です: pip install torch")
        return 2

    try:
        import torchreid  # type: ignore
    except ImportError:
        logger.error("torchreid が必要です: pip install torchreid gdown")
        return 2

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if OUT_PATH.exists():
        logger.info("既に存在: %s (%.1f MB) — 上書きしません", OUT_PATH, OUT_PATH.stat().st_size / 1e6)
        return 0

    logger.info("OSNet x0_25 model を torchreid から構築 + pretrained weight load")
    model = torchreid.models.build_model(
        name="osnet_x0_25",
        num_classes=1000,  # placeholder; reid 推論時は feature だけ使う
        loss="softmax",
        pretrained=True,
    )
    model.eval()

    # feature extraction mode (classifier 通さない)
    # osnet は forward(x) で classifier 通過。feature だけ欲しいので feature_dim 取得。
    # build_model 後の osnet は forward でモデル出力（classifier 後）が返るため、
    # 直接 module を辿って global avgpool 後の feature (512-d) を取得する hook を使う。
    import torch  # type: ignore
    import torch.nn as nn  # type: ignore

    class _FeatureWrapper(nn.Module):
        def __init__(self, backbone):
            super().__init__()
            self._backbone = backbone

        def forward(self, x):  # noqa: D401
            # torchreid osnet は featuremaps -> global_avgpool -> fc(classifier)
            # featuremaps + global_avgpool までで 512-d を得る。
            f = self._backbone.featuremaps(x)
            v = self._backbone.global_avgpool(f)
            v = v.view(v.size(0), -1)
            # fc は 512->512 の中間 layer (BN + ReLU)。reid feature として使う標準。
            if hasattr(self._backbone, "fc") and self._backbone.fc is not None:
                v = self._backbone.fc(v)
            return v

    wrapped = _FeatureWrapper(model)
    wrapped.eval()

    dummy = torch.randn(1, 3, 256, 128, dtype=torch.float32)
    with torch.no_grad():
        out = wrapped(dummy)
    logger.info("feature shape (single): %s", tuple(out.shape))

    logger.info("ONNX export → %s", OUT_PATH)
    torch.onnx.export(
        wrapped,
        dummy,
        str(OUT_PATH),
        input_names=["input"],
        output_names=["features"],
        dynamic_axes={"input": {0: "batch"}, "features": {0: "batch"}},
        opset_version=14,
        do_constant_folding=True,
    )
    size_mb = OUT_PATH.stat().st_size / 1e6
    logger.info("完了: %s (%.1f MB)", OUT_PATH, size_mb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
