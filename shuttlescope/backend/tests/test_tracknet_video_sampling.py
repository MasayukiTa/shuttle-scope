from __future__ import annotations

import pytest

from backend.tracknet.video_sampling import TrackNetFrameSampler, step_frames_for_fps


def _collect(total_frames: int, step_frames: int):
    sampler = TrackNetFrameSampler[int](step_frames=step_frames)
    out = []
    for frame in range(total_frames):
        window = sampler.push(frame)
        if window is not None:
            out.append(window)
    return sampler, out


def test_15fps_on_30fps_uses_consecutive_triplets_at_two_frame_starts():
    sampler, windows = _collect(total_frames=10, step_frames=2)
    assert [w.start_frame for w in windows] == [0, 2, 4, 6]
    assert [w.frames for w in windows] == [
        [0, 1, 2],
        [2, 3, 4],
        [4, 5, 6],
        [6, 7, 8],
    ]
    assert sampler.decoded_frames == 10
    assert sampler.sampled_windows == 4


def test_30fps_on_30fps_slides_one_physical_frame_at_a_time():
    sampler, windows = _collect(total_frames=8, step_frames=1)
    assert [w.start_frame for w in windows] == [0, 1, 2, 3, 4, 5]
    assert windows[-1].frames == [5, 6, 7]
    assert sampler.sampled_windows == 6


def test_10fps_on_30fps_starts_every_three_frames_without_internal_skips():
    _sampler, windows = _collect(total_frames=12, step_frames=3)
    assert [w.start_frame for w in windows] == [0, 3, 6, 9]
    assert [w.frames for w in windows] == [
        [0, 1, 2],
        [3, 4, 5],
        [6, 7, 8],
        [9, 10, 11],
    ]


@pytest.mark.parametrize(
    ("video_fps", "sample_fps", "expected"),
    [
        (30.0, 30.0, 1),
        (29.97, 15.0, 2),
        (30.0, 10.0, 3),
        (60.0, 15.0, 4),
        (24.0, 30.0, 1),
        (30.0, 0.0, 3),
    ],
)
def test_step_frames_for_fps(video_fps, sample_fps, expected):
    assert step_frames_for_fps(video_fps, sample_fps) == expected


def test_invalid_sampler_parameters_fail_fast():
    with pytest.raises(ValueError):
        TrackNetFrameSampler(step_frames=0)
    with pytest.raises(ValueError):
        TrackNetFrameSampler(step_frames=1, frame_stack=0)
