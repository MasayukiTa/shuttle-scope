from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from backend.utils.model_integrity import (
    DEFAULT_MANIFEST_PATH,
    parse_manifest,
    verify_and_log,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_prod_only_runtime_models_are_pinned_in_manifest():
    manifest = parse_manifest(DEFAULT_MANIFEST_PATH)
    # These binaries are intentionally gitignored, but they are production runtime
    # inputs. Their hashes must still be version-controlled in SHA256SUMS.
    assert "osnet_x0_25_reid.onnx" in manifest
    assert "yolov8n_v2_finetuned.onnx" in manifest
    assert "yolov8n_v2_finetuned_dyn.onnx" in manifest


def test_unexpected_model_can_fail_closed(tmp_path: Path):
    models = tmp_path / "models"
    models.mkdir()
    known = models / "known.onnx"
    known.write_bytes(b"known")
    (models / "rogue.onnx").write_bytes(b"rogue")

    manifest = models / "SHA256SUMS"
    manifest.write_text(
        f"{_sha(b'known')}  known.onnx\n",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc:
        verify_and_log(
            fail_on_mismatch=True,
            fail_on_unexpected=True,
            models_dir=models,
            manifest_path=manifest,
        )
    assert exc.value.code == 3


def test_unexpected_model_remains_warning_only_when_not_enforced(tmp_path: Path):
    models = tmp_path / "models"
    models.mkdir()
    known = models / "known.onnx"
    known.write_bytes(b"known")
    (models / "experimental.onnx").write_bytes(b"experimental")

    manifest = models / "SHA256SUMS"
    manifest.write_text(
        f"{_sha(b'known')}  known.onnx\n",
        encoding="utf-8",
    )

    result = verify_and_log(
        fail_on_mismatch=False,
        fail_on_unexpected=False,
        models_dir=models,
        manifest_path=manifest,
    )
    assert result.unexpected == ["experimental.onnx"]


def test_startup_model_integrity_uses_production_posture_single_source():
    main_src = (
        Path(__file__).resolve().parents[1] / "main.py"
    ).read_text(encoding="utf-8")
    assert "is_prod = bool(app_settings.is_production_posture)" in main_src
    assert 'is_prod = env_norm == "production"' not in main_src
