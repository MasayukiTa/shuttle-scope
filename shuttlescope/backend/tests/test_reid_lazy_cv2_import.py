"""Regression: backend.cv.reid must NOT import cv2 at module import time.

backend.routers.yolo imports backend.cv.reid at module top
(`from backend.cv.reid import extract_embedding, MIN_APP_SIM`). reid.py used
to run `import cv2` at module top, so importing the yolo router transitively
forced opencv into the process even though the router's own cv2 use was
already made lazy. That defeated a lean, CV-free startup.

reid.py now defers the real opencv import to first attribute use via a lazy
proxy (same pattern as the router). This test is Linux-safe and does not
require opencv to be installed.
"""
import builtins
import importlib
import sys

import pytest


def test_reid_import_does_not_require_cv2(monkeypatch):
    sys.modules.pop("backend.cv.reid", None)
    # Make an eager `import cv2` fail loudly.
    monkeypatch.setitem(sys.modules, "cv2", None)

    real_import = builtins.__import__

    def guard_import(name, *args, **kwargs):
        if name == "cv2" or name.startswith("cv2."):
            raise AssertionError("cv2 imported at module import time (not lazy)")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard_import)

    try:
        mod = importlib.import_module("backend.cv.reid")
    except AssertionError:
        raise
    except Exception as exc:  # environment-dependent heavy deps (e.g. numpy)
        pytest.skip(f"reid has unrelated heavy import deps here: {exc!r}")
        return

    assert hasattr(mod, "cv2")
    assert type(mod.cv2).__name__ == "_LazyCv2"


def test_yolo_router_import_does_not_pull_cv2_via_reid(monkeypatch):
    """The whole point: importing the router must not drag opencv in through
    the transitive backend.cv.reid dependency."""
    for m in ("backend.routers.yolo", "backend.cv.reid"):
        sys.modules.pop(m, None)
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
    except Exception as exc:  # unrelated heavy deps in this environment
        pytest.skip(f"router has unrelated heavy import deps here: {exc!r}")
        return

    assert hasattr(mod, "cv2")
    assert type(mod.cv2).__name__ == "_LazyCv2"
