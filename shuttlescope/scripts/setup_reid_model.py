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

    # torch.onnx.export は weight を外部データ (`*.onnx.data`) に切り出すことがある。
    # その場合 .onnx 本体だけ deploy / コピーすると onnxruntime が
    # "file_size: ... .onnx.data ... cannot find the file" で load 失敗する
    # (2026-05-30 の ReID 復旧で実際に踏んだ罠)。weight を本体に inline 化して
    # 1 ファイル自己完結にし、外部 .data を削除する。
    import onnx  # type: ignore

    m = onnx.load(str(OUT_PATH), load_external_data=True)
    onnx.save_model(m, str(OUT_PATH), save_as_external_data=False)
    ext = OUT_PATH.with_name(OUT_PATH.name + ".data")
    if ext.exists():
        ext.unlink()
        logger.info("外部 weight %s を inline 化して削除", ext.name)

    # 自己検証: onnxruntime で load + ダミー推論し 512-d feature を確認。
    import numpy as np  # type: ignore
    import onnxruntime as ort  # type: ignore

    so = ort.SessionOptions()
    so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess = ort.InferenceSession(str(OUT_PATH), so, providers=["CPUExecutionProvider"])
    iname = sess.get_inputs()[0].name
    probe = np.random.RandomState(0).randn(2, 3, 256, 128).astype(np.float32)
    feats = sess.run(None, {iname: probe})[0]
    if feats.shape[1] != 512:
        logger.error("自己検証 NG: feature dim=%s (期待 512)", feats.shape)
        return 4
    logger.info("自己検証 OK: onnxruntime load + 推論 → feature shape=%s", tuple(feats.shape))

    size_mb = OUT_PATH.stat().st_size / 1e6
    logger.info("完了: %s (%.1f MB, self-contained)", OUT_PATH, size_mb)
    return 0


if __name__ == "__main__":
    sys.exit(main())
