from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from backend.utils.torch_state_npz import load_state_dict_npz, save_state_dict_npz


torch = pytest.importorskip("torch")


def test_state_dict_npz_round_trip(tmp_path: Path):
    source = {
        "layer.weight": torch.arange(12, dtype=torch.float32).reshape(3, 4),
        "layer.bias": torch.tensor([1.0, -2.0, 3.0], dtype=torch.float32),
        "counter": torch.tensor(7, dtype=torch.int64),
    }
    path = tmp_path / "state.npz"

    save_state_dict_npz(source, path)
    loaded = load_state_dict_npz(path, torch)

    assert list(loaded) == list(source)
    for key in source:
        assert torch.equal(loaded[key], source[key])


def test_state_dict_npz_rejects_object_arrays(tmp_path: Path):
    path = tmp_path / "bad.npz"
    np.savez(path, bad=np.array([{"payload": "not allowed"}], dtype=object))

    with pytest.raises(ValueError):
        load_state_dict_npz(path, torch)


def test_model_integrity_scans_npz(tmp_path: Path):
    import hashlib
    from backend.utils.model_integrity import verify_models

    models = tmp_path / "models"
    models.mkdir()
    state = models / "classifier.npz"
    state.write_bytes(b"safe-npz-placeholder")
    digest = hashlib.sha256(state.read_bytes()).hexdigest()
    manifest = models / "SHA256SUMS"
    manifest.write_text(f"{digest}  classifier.npz\n", encoding="utf-8")

    result = verify_models(models_dir=models, manifest_path=manifest)
    assert result.matched == ["classifier.npz"]
    assert result.mismatched == []
    assert result.missing == []
    assert result.unexpected == []
