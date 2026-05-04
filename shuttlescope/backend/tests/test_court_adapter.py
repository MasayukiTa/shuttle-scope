"""Track A2: CourtAdapter テスト。

- フォールバック (キャリブ無し) で hard-coded 値を返す
- キャリブ済 homography で pixel_to_court / court_to_pixel が逆操作になる
- formation_type / depth_band が正しく分類
- candidate_builder / court_mapper への注入動作
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.cv.court_adapter import (
    CourtAdapter,
    FALLBACK_FRONT_THRESHOLD_Y,
    FALLBACK_BACK_THRESHOLD_Y,
    FALLBACK_FORMATION_MIN_Y_DIFF,
)


# ── キャリブ無し (フォールバック) ─────────────────────────────────────────────

def test_fallback_thresholds_match_constants():
    a = CourtAdapter()
    assert not a.is_calibrated
    assert a.front_threshold_y == FALLBACK_FRONT_THRESHOLD_Y
    assert a.back_threshold_y == FALLBACK_BACK_THRESHOLD_Y
    assert a.formation_min_y_diff == FALLBACK_FORMATION_MIN_Y_DIFF


def test_fallback_pixel_to_court_passthrough():
    a = CourtAdapter()
    cx, cy = a.pixel_to_court(0.3, 0.7)
    assert cx == pytest.approx(0.3)
    assert cy == pytest.approx(0.7)


def test_fallback_in_court_always_true():
    a = CourtAdapter()
    assert a.in_court(0.0, 0.0) is True
    assert a.in_court(0.99, 0.99) is True


def test_fallback_formation_classification():
    a = CourtAdapter()
    # 大きな y 差 → front_back
    assert a.formation_type((0.5, 0.2), (0.5, 0.5)) == "front_back"
    # 大きな x 差、y 同じ → parallel
    assert a.formation_type((0.2, 0.5), (0.8, 0.5)) == "parallel"
    # 中間 → mixed
    assert a.formation_type((0.4, 0.4), (0.5, 0.45)) == "mixed"


# ── キャリブ済 (mock homography) ─────────────────────────────────────────────

def _identity_adapter() -> CourtAdapter:
    """画像 (x,y) = コート (x,y) になる単位 homography."""
    H = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    H_inv = H
    return CourtAdapter(homography=H, homography_inv=H_inv)


def test_calibrated_pixel_to_court_round_trip():
    a = _identity_adapter()
    assert a.is_calibrated
    cx, cy = a.pixel_to_court(0.3, 0.7)
    assert cx == pytest.approx(0.3)
    assert cy == pytest.approx(0.7)
    px, py = a.court_to_pixel(cx, cy)
    assert px == pytest.approx(0.3)
    assert py == pytest.approx(0.7)


def test_calibrated_thresholds_dynamic():
    """単位 homography なら court (0.5, 0.42) → image y=0.42。"""
    a = _identity_adapter()
    assert a.front_threshold_y == pytest.approx(0.42, abs=1e-3)
    assert a.back_threshold_y == pytest.approx(0.60, abs=1e-3)


def test_calibrated_depth_band():
    a = _identity_adapter()
    # cy=0.2 → side a, cy < 1/3 → back_a
    assert a.depth_band(0.5, 0.2) == "back_a"
    # cy=0.4 → side a, between 1/3 and 0.5 → front_a
    assert a.depth_band(0.5, 0.4) == "front_a"
    # cy=0.55 → side b, between 0.5 and 2/3 → front_b
    assert a.depth_band(0.5, 0.55) == "front_b"
    # cy=0.85 → side b, > 2/3 → back_b
    assert a.depth_band(0.5, 0.85) == "back_b"


def test_calibrated_formation_uses_court_coords():
    a = _identity_adapter()
    assert a.formation_type((0.5, 0.2), (0.5, 0.5)) == "front_back"


def test_in_court_with_polygon():
    """ROI 多角形で in_court が動作。"""
    a = CourtAdapter(roi_polygon=[[0.1, 0.1], [0.9, 0.1], [0.9, 0.9], [0.1, 0.9]])
    assert a.in_court(0.5, 0.5) is True
    assert a.in_court(0.05, 0.05) is False


# ── for_match ファクトリ (DB なし環境で例外なくフォールバック) ─────────────

def test_for_match_no_db_returns_uncalibrated():
    # DB なしや未設定 match_id で例外を投げず uncalibrated adapter を返す
    a = CourtAdapter.for_match(99999999)
    assert isinstance(a, CourtAdapter)
    # DB が無くても少なくとも fallback 動作する
    assert a.front_threshold_y == FALLBACK_FRONT_THRESHOLD_Y


# ── candidate_builder / court_mapper への注入動作 ─────────────────────────────

def test_candidate_builder_role_inference_with_adapter():
    from backend.cv.candidate_builder import _infer_front_back_role
    yolo_frames = [
        {
            "timestamp_sec": 0.0,
            "players": [
                {"label": "player_a", "centroid": [0.5, 0.30]},   # 浅い → front
                {"label": "player_b", "centroid": [0.5, 0.70]},   # 深い → back
            ],
        }
    ]
    a = _identity_adapter()
    role = _infer_front_back_role(yolo_frames, stroke_ts=0.0, court_adapter=a)
    assert role is not None
    assert role["player_a"] == "front"
    assert role["player_b"] == "back"


def test_court_mapper_formation_with_adapter():
    from backend.yolo.court_mapper import classify_formation
    players = [
        {"label": "player_a", "centroid": [0.5, 0.20]},
        {"label": "player_b", "centroid": [0.5, 0.50]},
    ]
    a = _identity_adapter()
    assert classify_formation(players, court_adapter=a) == "front_back"


def test_court_mapper_formation_without_adapter_unchanged():
    """adapter なし呼出で従来動作不変。"""
    from backend.yolo.court_mapper import classify_formation
    players = [
        {"label": "player_a", "centroid": [0.5, 0.20]},
        {"label": "player_b", "centroid": [0.5, 0.50]},
    ]
    assert classify_formation(players) == "front_back"
