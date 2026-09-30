from __future__ import annotations

import ast
from pathlib import Path

from backend.utils.model_integrity import parse_manifest


SHUTTLESCOPE_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = SHUTTLESCOPE_ROOT / "backend"
MANIFEST_PATH = BACKEND_ROOT / "models" / "SHA256SUMS"
SETUP_REID_PATH = SHUTTLESCOPE_ROOT / "scripts" / "setup_reid_model.py"

ACTIVE_GITIGNORED_RUNTIME_MODELS = {
    "osnet_x0_25_reid.onnx",
    "yolov8n_v2_finetuned_dyn.onnx",
}


def _module_string_constant(path: Path, name: str) -> str:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    value = ast.literal_eval(node.value)
                    if isinstance(value, str):
                        return value
    raise AssertionError(f"{name} not found as a string constant in {path}")


def test_active_gitignored_runtime_models_are_manifest_pinned():
    manifest = parse_manifest(MANIFEST_PATH)

    for rel in ACTIVE_GITIGNORED_RUNTIME_MODELS:
        digest = manifest.get(rel)
        assert digest is not None, (
            f"active runtime model {rel} must be protected by SHA256SUMS"
        )
        assert len(digest) == 64
        assert all(ch in "0123456789abcdef" for ch in digest)


def test_reid_setup_targets_the_manifest_pinned_runtime_artifact():
    source = SETUP_REID_PATH.read_text(encoding="utf-8")

    assert _module_string_constant(SETUP_REID_PATH, "_RUNTIME_MODEL_REL") == (
        "osnet_x0_25_reid.onnx"
    )
    assert "_runtime_expected_sha256" in source
    assert "_sha256_file" in source
    assert "actual != expected" in source


def test_reid_setup_never_downloads_or_deserializes_model_checkpoints():
    source = SETUP_REID_PATH.read_text(encoding="utf-8")

    forbidden = (
        "torch.load",
        "torchreid",
        "urllib.request",
        "urlopen(",
        "httpx",
        "requests.get",
        "requests.post",
        ".pth",
    )
    for token in forbidden:
        assert token not in source

    assert "trusted artifact" in source.lower()
    assert "must not regenerate it from pickle checkpoints" in source
