from __future__ import annotations

import ast
from pathlib import Path

from backend.utils.model_integrity import parse_manifest


SHUTTLESCOPE_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = SHUTTLESCOPE_ROOT / "backend"
MANIFEST_PATH = BACKEND_ROOT / "models" / "SHA256SUMS"
SETUP_REID_PATH = SHUTTLESCOPE_ROOT / "scripts" / "setup_reid_model.py"

APPROVED_RUNTIME_HASHES = {
    "osnet_x0_25_reid.onnx":
        "de0fe0bf9e07ecdb08045394247713b5dbd2be54d00d267cba912c369d44c7f3",
    "yolov8n_v2_finetuned_dyn.onnx":
        "8b3c3a56fc25b82e26ae8aa56fdfd02ceae016a3203e1959d39c8b858661a62d",
}
OFFICIAL_OSNET_SOURCE_SHA256 = (
    "f54941a66bad4ddd07f2907f498c810ce639ce7a1abeaf2a151f8da118d84693"
)
OFFICIAL_OSNET_SOURCE_COMMIT = "4fb800163ca4da8f34bbb34703926eda7e7ef84e"


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

    for rel, expected_hash in APPROVED_RUNTIME_HASHES.items():
        assert manifest.get(rel) == expected_hash, (
            f"active runtime model {rel} must be protected by SHA256SUMS"
        )


def test_reid_source_checkpoint_is_immutable_and_hash_pinned():
    source_url = _module_string_constant(SETUP_REID_PATH, "SOURCE_WEIGHT_URL")
    source_hash = _module_string_constant(
        SETUP_REID_PATH,
        "SOURCE_WEIGHT_SHA256",
    )

    assert OFFICIAL_OSNET_SOURCE_COMMIT in source_url
    assert source_url.startswith(
        "https://huggingface.co/kaiyangzhou/osnet/resolve/"
    )
    assert source_hash == OFFICIAL_OSNET_SOURCE_SHA256


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
    assert "DevSkim: ignore DS173237" in source
    assert "DevSkim: ignore DS425050" in source
