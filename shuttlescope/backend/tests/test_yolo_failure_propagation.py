"""D-8: YOLO の正常 0 件と推論失敗を下流で区別する回帰テスト。"""

import numpy as np
import pytest

from backend.yolo.inference import YOLOInferenceError
from backend.routers.video_import import _run_yolo


class _FakeCapture:
    def __init__(self):
        self._reads = 0
        self.released = False

    def isOpened(self):
        return True

    def get(self, prop):
        import cv2
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return 1
        if prop == cv2.CAP_PROP_FPS:
            return 30.0
        return 0.0

    def read(self):
        if self._reads == 0:
            self._reads += 1
            return True, np.zeros((32, 32, 3), dtype=np.uint8)
        return False, None

    def release(self):
        self.released = True


class _FakeInference:
    def __init__(self, *, fail=False):
        self.fail = fail

    def load(self):
        return True

    def backend_name(self):
        return "fake"

    def predict_frame_checked(self, frame):
        if self.fail:
            raise YOLOInferenceError("推論に失敗しました")
        return []


def _job():
    return {
        "match_id": None,
        "progress": 0.5,
        "yolo": {"status": "running", "progress": 0.0},
    }


def _install(monkeypatch, *, fail):
    import cv2
    import backend.yolo.inference as inference_mod

    cap = _FakeCapture()
    monkeypatch.setattr(cv2, "VideoCapture", lambda _path: cap)
    monkeypatch.setattr(
        inference_mod,
        "get_yolo_inference",
        lambda: _FakeInference(fail=fail),
    )
    return cap


def test_video_import_valid_zero_detections_completes(monkeypatch):
    cap = _install(monkeypatch, fail=False)
    job = _job()

    _run_yolo(job, "dummy.mp4")

    assert job["yolo"]["status"] == "done"
    assert job["yolo"]["frame_count"] == 1
    assert cap.released is True


def test_video_import_inference_failure_is_not_zero_detections(monkeypatch):
    cap = _install(monkeypatch, fail=True)
    job = _job()

    with pytest.raises(YOLOInferenceError, match="推論に失敗しました"):
        _run_yolo(job, "dummy.mp4")

    assert job["yolo"]["status"] == "error"
    assert job["yolo"]["error"] == "推論に失敗しました"
    assert cap.released is True
