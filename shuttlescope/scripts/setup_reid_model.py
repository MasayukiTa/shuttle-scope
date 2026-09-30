"""OSNet x0_25 ReID model setup script (Phase 4).

The source checkpoint is treated as executable supply-chain input:
- download from the model author's immutable Hugging Face commit
- verify SHA-256 before deserializing the checkpoint container
- build with pretrained=False so torchreid never performs its own mutable download
- install the generated ONNX only if its SHA-256 matches the committed runtime
  model manifest

Usage:
    python shuttlescope/scripts/setup_reid_model.py
"""
from __future__ import annotations

import hashlib
import logging
import sys
import tempfile
import urllib.parse
import urllib.request
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = _REPO_ROOT / "backend" / "models" / "osnet_x0_25_reid.onnx"
_MANIFEST_PATH = _REPO_ROOT / "backend" / "models" / "SHA256SUMS"
_RUNTIME_MODEL_REL = "osnet_x0_25_reid.onnx"

# Official author mirror, pinned to the verified commit that introduced the
# ImageNet weights. The file SHA-256 is published by Hugging Face/Xet.
SOURCE_WEIGHT_URL = (
    "https://huggingface.co/kaiyangzhou/osnet/resolve/"
    "4fb800163ca4da8f34bbb34703926eda7e7ef84e/"
    "osnet_x0_25_imagenet.pth?download=true"
)
SOURCE_WEIGHT_SHA256 = (
    "f54941a66bad4ddd07f2907f498c810ce639ce7a1abeaf2a151f8da118d84693"  # DevSkim: ignore DS173237 -- public SHA-256 checksum, not a credential
)


def _sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _runtime_expected_sha256() -> str | None:
    """Return the approved runtime ONNX hash from backend/models/SHA256SUMS."""
    if not _MANIFEST_PATH.is_file():
        return None
    for raw in _MANIFEST_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, rel = parts
        rel = rel.lstrip("*").replace("\\", "/")
        if rel == _RUNTIME_MODEL_REL and len(digest) == 64:
            return digest.lower()
    return None


def _verify_existing_output() -> int:
    expected = _runtime_expected_sha256()
    if expected is None:
        logger.error(
            "%s exists but is not approved in %s; refusing to trust it",
            OUT_PATH,
            _MANIFEST_PATH,
        )
        return 5
    actual = _sha256_file(OUT_PATH)
    if actual != expected:
        logger.error(
            "runtime model hash mismatch: expected=%s actual=%s",
            expected,
            actual,
        )
        return 5
    logger.info(
        "existing model verified: %s (%.1f MB, sha256=%s)",
        OUT_PATH,
        OUT_PATH.stat().st_size / 1e6,
        actual,
    )
    return 0


def _download_verified_source(dst: Path) -> None:
    parsed = urllib.parse.urlsplit(SOURCE_WEIGHT_URL)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "huggingface.co"
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise RuntimeError("OSNet source URL must be HTTPS on huggingface.co")

    logger.info("download pinned OSNet source checkpoint: %s", SOURCE_WEIGHT_URL)
    request = urllib.request.Request(
        SOURCE_WEIGHT_URL,
        headers={"User-Agent": "ShuttleScope-model-setup/1"},
        method="GET",
    )
    h = hashlib.sha256()
    # B310 is safe here because the immutable constant URL is validated above
    # to the exact HTTPS scheme and approved host before urlopen.
    with urllib.request.urlopen(request, timeout=90) as response, dst.open("wb") as out:  # nosec B310
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.write(chunk)
            h.update(chunk)
    actual = h.hexdigest()
    if actual != SOURCE_WEIGHT_SHA256:
        dst.unlink(missing_ok=True)
        raise RuntimeError(
            "source checkpoint SHA256 mismatch: "
            f"expected={SOURCE_WEIGHT_SHA256} actual={actual}"
        )
    logger.info("source checkpoint verified sha256=%s", actual)


def _load_verified_weights(model, checkpoint: Path, torch) -> None:
    # The checkpoint is a pickle container. It reaches torch.load only after
    # cryptographic verification above. weights_only further narrows deserialization.
    state_dict = torch.load(  # DevSkim: ignore DS425050 -- SHA-256-pinned checkpoint; weights_only=True below
        str(checkpoint),
        map_location="cpu",
        weights_only=True,
    )
    if isinstance(state_dict, dict) and "state_dict" in state_dict:
        state_dict = state_dict["state_dict"]
    if not isinstance(state_dict, dict):
        raise RuntimeError("unexpected OSNet checkpoint structure")

    model_dict = model.state_dict()
    matched = {}
    for raw_key, value in state_dict.items():
        key = raw_key[7:] if raw_key.startswith("module.") else raw_key
        if key in model_dict and hasattr(value, "size") and value.size() == model_dict[key].size():
            matched[key] = value

    required = [
        key
        for key in model_dict
        if not key.startswith("classifier.")
    ]
    missing = [key for key in required if key not in matched]
    if missing:
        raise RuntimeError(
            f"OSNet source checkpoint missing {len(missing)} required layer(s): "
            + ", ".join(missing[:8])
        )

    model_dict.update(matched)
    model.load_state_dict(model_dict)
    logger.info("loaded %d verified checkpoint tensors", len(matched))


def main() -> int:
    try:
        import torch
    except ImportError:
        logger.error("torch is required: pip install torch")
        return 2

    try:
        import torchreid  # type: ignore
    except ImportError:
        logger.error("torchreid is required")
        return 2

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if OUT_PATH.exists():
        return _verify_existing_output()

    expected_output_hash = _runtime_expected_sha256()
    if expected_output_hash is None:
        logger.error(
            "approved hash for %s is missing from %s",
            _RUNTIME_MODEL_REL,
            _MANIFEST_PATH,
        )
        return 5

    with tempfile.TemporaryDirectory(prefix="ss_osnet_setup_") as tmpdir:
        tmpdir_path = Path(tmpdir)
        source_checkpoint = tmpdir_path / "osnet_x0_25_imagenet.pth"
        candidate_onnx = tmpdir_path / "osnet_x0_25_reid.onnx"

        try:
            _download_verified_source(source_checkpoint)
        except Exception as exc:
            logger.error("source checkpoint download/verification failed: %s", exc)
            return 3

        logger.info("build OSNet x0_25 from pinned source checkpoint")
        model = torchreid.models.build_model(
            name="osnet_x0_25",
            num_classes=1000,
            loss="softmax",
            pretrained=False,
        )
        try:
            _load_verified_weights(model, source_checkpoint, torch)
        except Exception as exc:
            logger.error("verified checkpoint load failed: %s", exc)
            return 3
        model.eval()

        import torch.nn as nn  # type: ignore

        class _FeatureWrapper(nn.Module):
            def __init__(self, backbone):
                super().__init__()
                self._backbone = backbone

            def forward(self, x):  # noqa: D401
                f = self._backbone.featuremaps(x)
                v = self._backbone.global_avgpool(f)
                v = v.view(v.size(0), -1)
                if hasattr(self._backbone, "fc") and self._backbone.fc is not None:
                    v = self._backbone.fc(v)
                return v

        wrapped = _FeatureWrapper(model)
        wrapped.eval()

        dummy = torch.randn(1, 3, 256, 128, dtype=torch.float32)
        with torch.no_grad():
            out = wrapped(dummy)
        if tuple(out.shape) != (1, 512):
            logger.error("unexpected feature shape before export: %s", tuple(out.shape))
            return 4

        logger.info("export ONNX candidate -> %s", candidate_onnx)
        torch.onnx.export(
            wrapped,
            dummy,
            str(candidate_onnx),
            input_names=["input"],
            output_names=["features"],
            dynamic_axes={"input": {0: "batch"}, "features": {0: "batch"}},
            opset_version=14,
            do_constant_folding=True,
        )

        import onnx  # type: ignore

        m = onnx.load(str(candidate_onnx), load_external_data=True)
        onnx.save_model(m, str(candidate_onnx), save_as_external_data=False)
        ext = candidate_onnx.with_name(candidate_onnx.name + ".data")
        ext.unlink(missing_ok=True)

        import numpy as np  # type: ignore
        import onnxruntime as ort  # type: ignore

        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess = ort.InferenceSession(
            str(candidate_onnx),
            so,
            providers=["CPUExecutionProvider"],
        )
        iname = sess.get_inputs()[0].name
        probe = np.random.RandomState(0).randn(2, 3, 256, 128).astype(np.float32)
        feats = sess.run(None, {iname: probe})[0]
        if feats.shape != (2, 512):
            logger.error("self-check failed: feature shape=%s", feats.shape)
            return 4

        actual_output_hash = _sha256_file(candidate_onnx)
        if actual_output_hash != expected_output_hash:
            logger.error(
                "generated ONNX is functionally valid but not the approved runtime artifact: "
                "expected=%s actual=%s. Review the toolchain/output before updating SHA256SUMS.",
                expected_output_hash,
                actual_output_hash,
            )
            return 5

        candidate_onnx.replace(OUT_PATH)

    logger.info(
        "completed: %s (%.1f MB, sha256=%s)",
        OUT_PATH,
        OUT_PATH.stat().st_size / 1e6,
        expected_output_hash,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
