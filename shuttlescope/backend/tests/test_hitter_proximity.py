"""D-3: hitter proximity is normalized by apparent player scale."""
from __future__ import annotations

import pytest

from backend.cv.hitter_proximity import (
    MAX_IMAGE_DISTANCE,
    nearest_player_by_proximity,
    proximity_for_player,
)


def _player(label: str, cx: float, cy: float, height: float) -> dict:
    half_h = height / 2.0
    return {
        "label": label,
        "centroid": [cx, cy],
        "bbox": [cx - 0.05, cy - half_h, cx + 0.05, cy + half_h],
    }


def test_far_side_small_player_gets_tighter_image_radius():
    shuttle = (0.50, 0.50)
    near = _player("near", 0.63, 0.50, 0.30)
    far = _player("far", 0.63, 0.50, 0.08)

    near_p = proximity_for_player(near, *shuttle)
    far_p = proximity_for_player(far, *shuttle)

    assert near_p is not None and far_p is not None
    assert near_p.raw_distance == pytest.approx(far_p.raw_distance)
    assert near_p.allowed_distance == pytest.approx(MAX_IMAGE_DISTANCE)
    assert far_p.allowed_distance < near_p.allowed_distance
    assert near_p.normalized_distance < 1.0
    assert far_p.normalized_distance > 1.0


def test_selection_uses_body_scale_not_raw_pixel_nearest():
    shuttle = (0.50, 0.50)
    # far player is raw-image closer, but its tiny bbox means that distance is
    # large in body-height units. The larger/near player is the plausible hit.
    far = _player("far", 0.60, 0.50, 0.08)
    near = _player("near", 0.64, 0.50, 0.30)

    result = nearest_player_by_proximity([far, near], *shuttle)

    assert result is not None
    assert result.player["label"] == "near"
    assert result.raw_distance == pytest.approx(0.14)
    assert result.normalized_distance < 0.5


def test_missing_bbox_does_not_fall_back_to_fixed_threshold():
    result = proximity_for_player(
        {"label": "legacy", "centroid": [0.51, 0.50]},
        0.50,
        0.50,
    )
    assert result is None


def test_absolute_035_remains_only_an_upper_cap():
    player = _player("huge", 0.50, 0.50, 0.90)
    result = proximity_for_player(player, 0.50, 0.50)
    assert result is not None
    assert result.allowed_distance == pytest.approx(MAX_IMAGE_DISTANCE)
