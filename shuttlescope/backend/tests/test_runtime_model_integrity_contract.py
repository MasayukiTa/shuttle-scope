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


def test_reid_source_checkpoint_is_immutable_and_hash_pinned():
    source_url = _module_string_constant(SETUP_REID_PATH, "SOURCE_WEIGHT_URL")
    source_hash = _module_string_constant(
        SETUP_REID_PATH,
        "SOURCE_WEIGHT_SHA256",
    )

    prefix = "https://huggingface.co/kaiyangzhou/osnet/resolve/"
    assert source_url.startswith(prefix)
    revision = source_url[len(prefix):].split("/", 1)[0]
    assert len(revision) == 40
    assert all(ch in "0123456789abcdef" for ch in revision)
    assert len(source_hash) == 64
    assert all(ch in "0123456789abcdef" for ch in source_hash)


def test_reid_setup_never_uses_torchreid_mutable_pretrained_download():
    source = SETUP_REID_PATH.read_text(encoding="utf-8")

    assert "pretrained=False" in source
    assert "weights_only=True" in source
    assert "pretrained=True" not in source
    assert "SOURCE_WEIGHT_SHA256" in source


def test_reid_setup_constrains_download_scheme_host_and_documents_scanner_exceptions():
    source = SETUP_REID_PATH.read_text(encoding="utf-8")

    assert "urllib.parse.urlsplit(SOURCE_WEIGHT_URL)" in source
    assert 'parsed.scheme != "https"' in source
    assert 'parsed.hostname != "huggingface.co"' in source
    assert "parsed.username is not None" in source
    assert "parsed.password is not None" in source
    assert "# nosec B310" in source
    assert "nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected" in source
    assert "nosemgrep: trailofbits.python.pickles-in-pytorch.pickles-in-pytorch" in source
    assert "DevSkim: ignore DS173237" in source
    assert "DevSkim: ignore DS425050" in source
