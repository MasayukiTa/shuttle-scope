"""Regression: backend.routers.yolo must NOT import cv2 at module import time.

Importing this router used to run `import cv2`, forcing opencv into every
process that imports it (app startup via include_router) and blocking a
lean, CV-free startup. The router now defers the real opencv import to
first attribute use via a lazy proxy. This test is Linux-safe and does
not require opencv to be installed.
"""
import builtins
import importlib
import sys

import pytest


def test_router_import_does_not_require_cv2(monkeypatch):
    sys.modules.pop("backend.routers.yolo", None)
    # Make an eager `import cv2` fail loudly.
    monkeypatch.setitem(sys.modules, "cv2", None)

    real_import = builtins.__import__

    def guard_import(name, *args, **kwargs):
        if name == "cv2" or name.startswith("cv2."):
            raise AssertionError("cv2 imported at module import time (not lazy)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard_import)

    try:
        mod = importlib.import_module("backend.routers.yolo")
    except AssertionError:
        raise
    except Exception as exc:  # environment-dependent heavy deps
        pytest.skip(f"router has unrelated heavy import deps here: {exc!r}")
        return

    assert hasattr(mod, "cv2")
    assert type(mod.cv2).__name__ == "_LazyCv2"
