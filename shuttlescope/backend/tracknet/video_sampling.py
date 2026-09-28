"""Frame-window sampling shared by TrackNet video import and benchmarks.

TrackNet consumes three consecutive physical video frames per inference. The
sampling rate controls how often a new 3-frame window starts; it must not be
implemented by skipping frames inside the temporal window.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Generic, Optional, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class SampledWindow(Generic[T]):
    """One TrackNet input window keyed by its first physical frame index."""

    start_frame: int
    frames: list[T]


class TrackNetFrameSampler(Generic[T]):
    """Incremental sampler for consecutive 3-frame TrackNet windows."""

    def __init__(self, step_frames: int, frame_stack: int = 3) -> None:
        if step_frames < 1:
            raise ValueError("step_frames must be >= 1")
        if frame_stack < 1:
            raise ValueError("frame_stack must be >= 1")
        self.step_frames = int(step_frames)
        self.frame_stack = int(frame_stack)
        self._buf: deque[T] = deque(maxlen=self.frame_stack)
        self.decoded_frames = 0
        self.sampled_windows = 0

    def push(self, frame: T) -> Optional[SampledWindow[T]]:
        """Consume one physical frame and return a window when scheduled."""
        read_index = self.decoded_frames
        self.decoded_frames += 1
        self._buf.append(frame)
        if len(self._buf) < self.frame_stack:
            return None
        start_frame = read_index - self.frame_stack + 1
        if start_frame % self.step_frames != 0:
            return None
        self.sampled_windows += 1
        return SampledWindow(start_frame=start_frame, frames=list(self._buf))


def step_frames_for_fps(video_fps: float, sample_fps: float) -> int:
    """Return the integer frame stride used by the production sampler."""
    if video_fps <= 0:
        video_fps = 30.0
    if sample_fps <= 0:
        sample_fps = 10.0
    return max(1, int(round(video_fps / min(sample_fps, video_fps))))
