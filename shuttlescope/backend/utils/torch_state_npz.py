"""Safe NumPy-backed serialization for PyTorch state_dict values.

This module intentionally avoids pickle. Model state is stored as an NPZ archive
containing numeric ndarrays only and loaded with allow_pickle=False.
"""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from typing import Mapping, Any

import numpy as np


def save_state_dict_npz(state_dict: Mapping[str, Any], path: Path) -> None:
    """Atomically save a tensor state_dict as numeric NPZ arrays."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    arrays: dict[str, np.ndarray] = {}
    for key, value in state_dict.items():
        if not isinstance(key, str):
            raise TypeError("state_dict keys must be strings")
        if not hasattr(value, "detach"):
            raise TypeError(f"state_dict value is not tensor-like: {key}")
        arr = value.detach().cpu().numpy()
        if arr.dtype.hasobject:
            raise TypeError(f"object dtype is not allowed in model state: {key}")
        arrays[key] = arr

    tmp = path.with_name(path.name + ".part")
    try:
        with tmp.open("wb") as fh:
            np.savez_compressed(fh, **arrays)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def load_state_dict_npz(path: Path, torch_module) -> "OrderedDict[str, Any]":
    """Load an NPZ tensor state without permitting pickle/object arrays."""
    path = Path(path)
    state: "OrderedDict[str, Any]" = OrderedDict()
    with np.load(path, allow_pickle=False) as archive:
        for key in archive.files:
            arr = np.array(archive[key], copy=True)
            if arr.dtype.hasobject:
                raise TypeError(f"object dtype is not allowed in model state: {key}")
            state[key] = torch_module.from_numpy(arr)
    if not state:
        raise ValueError(f"empty model state archive: {path}")
    return state
