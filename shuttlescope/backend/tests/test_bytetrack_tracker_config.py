# -*- coding: utf-8 -*-
"""Regression: bytetrack.yaml must contain every field ultralytics' BYTETracker reads.

ultralytics loads the tracker yaml WITHOUT merging defaults
(track.py: IterableSimpleNamespace(**YAML.load(tracker))), so a field missing
from our yaml (e.g. fuse_score) makes .track() raise AttributeError on frame 0.
See docs/validation/ultralytics-fusescore-fix-2026-05-29.md.
"""
from __future__ import annotations

from pathlib import Path

import pytest

_BT_YAML = Path(__file__).resolve().parents[1] / "yolo" / "bytetrack.yaml"


def _load_cfg():
    from ultralytics.utils import YAML, IterableSimpleNamespace

    return IterableSimpleNamespace(**YAML.load(str(_BT_YAML)))


def test_bytetrack_yaml_has_fuse_score():
    """fuse_score must be present (BYTETracker.get_dists reads self.args.fuse_score)."""
    pytest.importorskip("ultralytics")
    cfg = _load_cfg()
    assert isinstance(cfg.fuse_score, bool)
    assert cfg.tracker_type == "bytetrack"


class _DetSlice:
    """Subscriptable view that mimics ultralytics Boxes slicing used by BYTETracker."""

    def __init__(self, conf, xywh, cls, xyxy):
        import numpy as np

        self.conf = np.asarray(conf, dtype=np.float32)
        self.xywh = np.asarray(xywh, dtype=np.float32).reshape(-1, 4)
        self.cls = np.asarray(cls, dtype=np.float32)
        self.xyxy = np.asarray(xyxy, dtype=np.float32).reshape(-1, 4)

    def __getitem__(self, idx):
        return _DetSlice(self.conf[idx], self.xywh[idx], self.cls[idx], self.xyxy[idx])

    def __len__(self):
        return len(self.conf)


def test_bytetracker_update_without_attr_error():
    """BYTETracker built from our yaml must update through the get_dists/
    fuse_score code paths without AttributeError (the original crash).

    Two frames with one detection each exercise the second-stage match where
    self.args.fuse_score is read (byte_tracker.py:342/412)."""
    pytest.importorskip("ultralytics")
    import numpy as np
    from ultralytics.trackers.byte_tracker import BYTETracker

    import inspect as _inspect
    _kw = {"frame_rate": 30} if "frame_rate" in _inspect.signature(BYTETracker.__init__).parameters else {}
    tracker = BYTETracker(args=_load_cfg(), **_kw)
    img = np.zeros((64, 64, 3), dtype=np.uint8)

    det = _DetSlice(conf=[0.9], xywh=[[32, 32, 20, 40]], cls=[0], xyxy=[[22, 12, 42, 52]])
    # No exception == fix in place; previously raised AttributeError on fuse_score.
    tracker.update(det, img)
    tracker.update(det, img)


def test_bytetracker_empty_frame_no_crash():
    """Empty-detection frame must not crash the tracker."""
    pytest.importorskip("ultralytics")
    import numpy as np
    from ultralytics.trackers.byte_tracker import BYTETracker

    import inspect as _inspect
    _kw = {"frame_rate": 30} if "frame_rate" in _inspect.signature(BYTETracker.__init__).parameters else {}
    tracker = BYTETracker(args=_load_cfg(), **_kw)
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    empty = _DetSlice(
        conf=np.empty((0,)), xywh=np.empty((0, 4)),
        cls=np.empty((0,)), xyxy=np.empty((0, 4)),
    )
    tracker.update(empty, img)
