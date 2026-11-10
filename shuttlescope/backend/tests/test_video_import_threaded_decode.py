from __future__ import annotations

import pytest

from backend.routers.video_import import _iter_video_frames_threaded


class FakeCapture:
    def __init__(self, frames, *, fail_after: int | None = None):
        self.frames = list(frames)
        self.index = 0
        self.fail_after = fail_after
        self.released = False

    def read(self):
        if self.fail_after is not None and self.index >= self.fail_after:
            raise ValueError("decode boom")
        if self.index >= len(self.frames):
            return False, None
        frame = self.frames[self.index]
        self.index += 1
        return True, frame

    def release(self):
        self.released = True


def test_threaded_decode_preserves_order_and_releases_capture():
    cap = FakeCapture(["f0", "f1", "f2", "f3"])

    assert list(_iter_video_frames_threaded(cap, queue_size=2)) == [
        "f0",
        "f1",
        "f2",
        "f3",
    ]
    assert cap.released is True


def test_threaded_decode_propagates_producer_failure():
    cap = FakeCapture(["f0", "f1"], fail_after=1)

    with pytest.raises(RuntimeError, match="video decode failed: decode boom"):
        list(_iter_video_frames_threaded(cap, queue_size=1))

    assert cap.released is True


def test_threaded_decode_stops_producer_when_consumer_closes_early():
    cap = FakeCapture(range(100))
    frames = _iter_video_frames_threaded(cap, queue_size=1)

    assert next(frames) == 0
    frames.close()

    assert cap.released is True
