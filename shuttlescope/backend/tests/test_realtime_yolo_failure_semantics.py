from __future__ import annotations

import asyncio
import json

import numpy as np
import pytest

from backend.cv import yolov8n
from backend.routers.yolo_realtime import ws_realtime_yolo_handler

cv2 = pytest.importorskip("cv2")


class _Input:
    name = "images"


class _FakeSession:
    def __init__(self, output=None, error: Exception | None = None):
        self.output = output
        self.error = error

    def get_inputs(self):
        return [_Input()]

    def run(self, _outputs, _feeds):
        if self.error is not None:
            raise self.error
        return [self.output]


@pytest.fixture(autouse=True)
def _restore_yolo_globals(monkeypatch):
    monkeypatch.setattr(yolov8n, "_load_attempted", True)
    monkeypatch.setattr(yolov8n, "_session", None)


def _jpeg_bytes() -> bytes:
    ok, buf = cv2.imencode(".jpg", np.zeros((16, 16, 3), dtype=np.uint8))
    assert ok
    return bytes(buf)


def test_model_unavailable_is_not_reported_as_zero_detections():
    with pytest.raises(yolov8n.ModelUnavailableError) as exc:
        yolov8n.infer_jpeg(_jpeg_bytes())
    assert exc.value.reason == "model_not_available"


def test_invalid_jpeg_is_not_reported_as_zero_detections(monkeypatch):
    monkeypatch.setattr(yolov8n, "_session", _FakeSession())
    with pytest.raises(yolov8n.InvalidFrameError) as exc:
        yolov8n.infer_jpeg(b"not-a-jpeg")
    assert exc.value.reason == "invalid_frame"


def test_inference_exception_is_not_reported_as_zero_detections(monkeypatch):
    monkeypatch.setattr(
        yolov8n,
        "_session",
        _FakeSession(error=RuntimeError("provider exploded")),
    )
    with pytest.raises(yolov8n.InferenceRuntimeError) as exc:
        yolov8n.infer_jpeg(_jpeg_bytes())
    assert exc.value.reason == "inference_failed"


def test_missing_output_tensor_is_not_reported_as_zero_detections(monkeypatch):
    class _NoOutputSession(_FakeSession):
        def run(self, _outputs, _feeds):
            return []

    monkeypatch.setattr(yolov8n, "_session", _NoOutputSession())
    with pytest.raises(yolov8n.InvalidModelOutputError) as exc:
        yolov8n.infer_jpeg(_jpeg_bytes())
    assert exc.value.reason == "invalid_model_output"


def test_invalid_output_shape_is_not_reported_as_zero_detections(monkeypatch):
    # After YOLO's (1, C, N) -> (N, C) transpose this has only 4 channels.
    monkeypatch.setattr(
        yolov8n,
        "_session",
        _FakeSession(output=np.zeros((1, 4, 100), dtype=np.float32)),
    )
    with pytest.raises(yolov8n.InvalidModelOutputError) as exc:
        yolov8n.infer_jpeg(_jpeg_bytes())
    assert exc.value.reason == "invalid_model_output"


def test_valid_inference_with_no_person_is_still_an_empty_list(monkeypatch):
    # Valid COCO-like tensor: 4 box channels + 80 classes, but every score is
    # below the person threshold. This is the only class of case that should
    # remain indistinguishable from "zero detections".
    monkeypatch.setattr(
        yolov8n,
        "_session",
        _FakeSession(output=np.zeros((1, 84, 100), dtype=np.float32)),
    )
    assert yolov8n.infer_jpeg(_jpeg_bytes()) == []


class _FakeWebSocket:
    def __init__(self):
        self.sent: list[dict] = []
        self._messages = [
            {"type": "websocket.receive", "bytes": b"bad-frame"},
            {"type": "websocket.disconnect"},
        ]

    async def accept(self):
        return None

    async def close(self, code=1000, reason=None):
        return None

    async def send_text(self, text: str):
        self.sent.append(json.loads(text))

    async def receive(self):
        return self._messages.pop(0)


def test_websocket_sends_error_instead_of_empty_detections(monkeypatch):
    monkeypatch.setattr(yolov8n, "is_available", lambda: True)

    def _fail(_data: bytes):
        raise yolov8n.InvalidFrameError("JPEG frame could not be decoded")

    monkeypatch.setattr(yolov8n, "infer_jpeg", _fail)
    ws = _FakeWebSocket()

    asyncio.run(ws_realtime_yolo_handler("TEST", ws))

    assert ws.sent[0]["type"] == "ready"
    assert ws.sent[1] == {
        "type": "error",
        "reason": "invalid_frame",
        "message": "JPEG frame could not be decoded",
    }
    assert not any(msg.get("type") == "detections" for msg in ws.sent)
