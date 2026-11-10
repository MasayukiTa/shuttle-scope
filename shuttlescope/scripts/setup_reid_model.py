"""Verify the approved OSNet ReID runtime artifact.

The runtime repository intentionally does not download or deserialize upstream
PyTorch checkpoints.  `osnet_x0_25_reid.onnx` must be provisioned from the
trusted artifact channel and its SHA-256 must match backend/models/SHA256SUMS.

Usage:
    python shuttlescope/scripts/setup_reid_model.py
"""
from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = _REPO_ROOT / "backend" / "models" / "osnet_x0_25_reid.onnx"
_MANIFEST_PATH = _REPO_ROOT / "backend" / "models" / "SHA256SUMS"
_RUNTIME_MODEL_REL = "osnet_x0_25_reid.onnx"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _runtime_expected_sha256() -> str | None:
    if not _MANIFEST_PATH.is_file():
        return None
    for raw in _MANIFEST_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2 and parts[-1].replace("\\", "/") == _RUNTIME_MODEL_REL:
            digest = parts[0].lower()
            if len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest):
                return digest
    return None


def main() -> int:
    expected = _runtime_expected_sha256()
    if expected is None:
        logger.error("approved hash for %s is missing from %s", _RUNTIME_MODEL_REL, _MANIFEST_PATH)
        return 5

    if not OUT_PATH.is_file():
        logger.error(
            "approved ReID model is not provisioned: %s. "
            "Restore the exact ONNX artifact from the trusted artifact store; "
            "runtime hosts must not regenerate it from pickle checkpoints.",
            OUT_PATH,
        )
        return 2

    actual = _sha256_file(OUT_PATH)
    if actual != expected:
        logger.error(
            "ReID model hash mismatch: expected=%s actual=%s path=%s",
            expected,
            actual,
            OUT_PATH,
        )
        return 5

    logger.info(
        "verified approved ReID model: %s (%.1f MB, sha256=%s)",
        OUT_PATH,
        OUT_PATH.stat().st_size / 1e6,
        expected,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
