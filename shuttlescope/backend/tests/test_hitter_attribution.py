"""Track C4: Hitter Attribution 3 段階テスト。"""
from __future__ import annotations

import pytest

from backend.cv.hitter_attribution import HitterAttribution, attribute_hitter
from backend.cv.swing_detector import SwingEvent


def _swing(ident, ts, conf=0.8):
    return SwingEvent(
        frame_idx=int(ts * 60), timestamp_sec=ts, identity=ident,
        hand="right", wrist_velocity=2.0, elbow_angle_change=30.0, confidence=conf,
    )


# ─── Priority 1: SwingDetector ────────────────────────────────────────────────

def test_priority1_swing_event_wins():
    res = attribute_hitter(
        stroke_timestamp_sec=1.0,
        swing_events=[_swing("player_a", 1.05, conf=0.7)],
        shuttle_position=(0.5, 0.5),
        player_positions=[{"label": "player_b", "centroid": [0.5, 0.5]}],
    )
    assert res.identity == "player_a"
    assert res.source == "swing_detector"
    assert res.confidence == 0.7


def test_priority1_picks_highest_confidence_swing():
    res = attribute_hitter(
        stroke_timestamp_sec=1.0,
        swing_events=[
            _swing("player_a", 1.05, conf=0.5),
            _swing("player_b", 0.95, conf=0.9),
        ],
    )
    assert res.identity == "player_b"
    assert res.source == "swing_detector"


def test_priority1_window_excludes_far_events():
    res = attribute_hitter(
        stroke_timestamp_sec=1.0,
        swing_events=[_swing("player_a", 5.0, conf=0.9)],  # 4 sec 離れてる
        swing_window_sec=0.25,
    )
    # P1 不発、P2/P3 へ
    assert res.source != "swing_detector"


# ─── Priority 2: proximity ────────────────────────────────────────────────────

def test_priority2_nearest_player_to_shuttle():
    res = attribute_hitter(
        stroke_timestamp_sec=1.0,
        swing_events=[],
        shuttle_position=(0.50, 0.50),
        player_positions=[
            {"label": "player_a", "centroid": [0.10, 0.10]},  # 遠い
            {"label": "player_b", "centroid": [0.55, 0.52]},  # 近い
        ],
    )
    assert res.identity == "player_b"
    assert res.source == "proximity"
    assert "no_swing_in_window" in res.fallback_reasons


def test_priority2_too_far_falls_to_review():
    res = attribute_hitter(
        stroke_timestamp_sec=1.0,
        swing_events=[],
        shuttle_position=(0.10, 0.10),
        player_positions=[{"label": "player_a", "centroid": [0.90, 0.90]}],  # 距離 ~1.13
        proximity_max_dist=0.35,
    )
    assert res.source == "review_required"
    assert "no_player_near_shuttle" in res.fallback_reasons


# ─── Priority 3: review_required ──────────────────────────────────────────────

def test_priority3_no_signals_returns_review():
    res = attribute_hitter(stroke_timestamp_sec=1.0, swing_events=[])
    assert res.identity is None
    assert res.source == "review_required"
    assert res.confidence == 0.0
    assert "no_swing_in_window" in res.fallback_reasons
    assert "no_shuttle_position" in res.fallback_reasons
    assert "no_player_positions" in res.fallback_reasons


def test_priority3_no_shuttle_only():
    res = attribute_hitter(
        stroke_timestamp_sec=1.0,
        swing_events=[],
        player_positions=[{"label": "player_a", "centroid": [0.5, 0.5]}],
    )
    assert res.source == "review_required"
    assert "no_shuttle_position" in res.fallback_reasons


def test_proximity_confidence_decreases_with_distance():
    """近い player は高い confidence、遠い player は低い confidence。"""
    near = attribute_hitter(
        stroke_timestamp_sec=1.0, swing_events=[],
        shuttle_position=(0.50, 0.50),
        player_positions=[{"label": "p", "centroid": [0.50, 0.50]}],
        proximity_max_dist=0.35,
    )
    far = attribute_hitter(
        stroke_timestamp_sec=1.0, swing_events=[],
        shuttle_position=(0.50, 0.50),
        player_positions=[{"label": "p", "centroid": [0.65, 0.65]}],  # 距離 ~0.21
        proximity_max_dist=0.35,
    )
    assert near.confidence > far.confidence
    assert near.confidence == pytest.approx(1.0)
