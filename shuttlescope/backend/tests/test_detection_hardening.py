"""Track C5: NetAwareDetector + CourtBoundedFilter テスト。"""
from __future__ import annotations

import pytest

from backend.cv.court_adapter import CourtAdapter
from backend.cv.detection_hardening import (
    CourtBoundedFilter,
    NetAwareDetector,
)


def _det(x1, y1, x2, y2, conf=0.9, track_id=None):
    d = {"bbox": [x1, y1, x2, y2], "confidence": conf, "label": "person"}
    if track_id is not None:
        d["track_id"] = track_id
    return d


# ─── NetAwareDetector ────────────────────────────────────────────────────────

def test_normal_threshold_filters_low_conf():
    nad = NetAwareDetector(normal_conf_threshold=0.50, net_conf_threshold=0.30)
    out = nad.filter([
        _det(0.10, 0.10, 0.20, 0.20, conf=0.45),  # 通常帯域、低 conf → 除外
        _det(0.10, 0.10, 0.20, 0.20, conf=0.70),  # 通常帯域、高 conf → 残る
    ])
    assert len(out) == 1
    assert out[0]["confidence"] == 0.70


def test_net_band_relaxed_threshold():
    """ネット帯域内の低 conf 検出が残る。"""
    nad = NetAwareDetector(net_conf_threshold=0.30, normal_conf_threshold=0.50)
    out = nad.filter([
        _det(0.10, 0.45, 0.20, 0.55, conf=0.35),  # ネット帯域、緩和 → 残る
        _det(0.10, 0.10, 0.20, 0.20, conf=0.35),  # 通常帯域 → 除外
    ])
    assert len(out) == 1


def test_net_band_split_bbox_merge():
    """ネット帯域内で y 方向に分断された 2 bbox が 1 つに統合される。

    両 bbox とも cy が 0.45 < cy < 0.55 にきれいに収まる範囲を選ぶ。
    """
    nad = NetAwareDetector(merge_x_overlap=0.6, merge_y_gap_max=0.05)
    out = nad.filter([
        _det(0.30, 0.46, 0.40, 0.49, conf=0.6),   # 上半身 cy=0.475
        _det(0.30, 0.51, 0.40, 0.54, conf=0.5),   # 下半身 cy=0.525, y_gap=0.02
    ])
    assert len(out) == 1
    merged = out[0]
    assert merged.get("merged_from") == 2


def test_net_band_no_merge_when_x_does_not_overlap():
    """両方 cy が確実にネット帯域内、x が重ならない場合は 2 件のまま。"""
    nad = NetAwareDetector(merge_x_overlap=0.6)
    out = nad.filter([
        _det(0.10, 0.46, 0.20, 0.49, conf=0.6),
        _det(0.50, 0.51, 0.60, 0.54, conf=0.6),
    ])
    assert len(out) == 2


def test_with_court_adapter_uses_homography_band():
    """単位 homography なら ネット帯域は court_y 0.5±0.08 → image y も同じ範囲。"""
    H = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    a = CourtAdapter(homography=H, homography_inv=H)
    nad = NetAwareDetector(court_adapter=a, net_band_court_y=(-0.08, 0.08))
    py_min, py_max = nad._net_band_image_y()
    assert py_min == pytest.approx(0.42, abs=0.01)
    assert py_max == pytest.approx(0.58, abs=0.01)


# ─── CourtBoundedFilter ──────────────────────────────────────────────────────

def test_in_court_default_margin():
    cbf = CourtBoundedFilter(court_margin=0.05)
    assert cbf.is_in_court([0.10, 0.10, 0.20, 0.20]) is True
    assert cbf.is_in_court([0.01, 0.01, 0.02, 0.02]) is False  # 外側マージン外


def test_umpire_zone_excluded():
    cbf = CourtBoundedFilter(umpire_zone_x=(0.40, 0.60), umpire_zone_y=(0.92, 1.0))
    out = cbf.filter([
        _det(0.45, 0.93, 0.55, 0.99, conf=0.9),  # 審判席 → 除外
        _det(0.45, 0.40, 0.55, 0.50, conf=0.9),  # コート内 → 残る
    ])
    assert len(out) == 1
    assert out[0]["bbox"][1] == 0.40


def test_min_area_excludes_tiny_dots():
    cbf = CourtBoundedFilter(min_area=0.001)
    out = cbf.filter([
        _det(0.50, 0.50, 0.51, 0.51, conf=0.9),  # area=0.0001 → 除外
        _det(0.50, 0.50, 0.55, 0.55, conf=0.9),  # area=0.0025 → 残る
    ])
    assert len(out) == 1


def test_max_area_excludes_huge():
    cbf = CourtBoundedFilter(max_area=0.30)
    out = cbf.filter([
        _det(0.05, 0.05, 0.95, 0.95, conf=0.9),  # 巨大 → 除外
    ])
    assert out == []


def test_persistence_filter_requires_n_frames():
    cbf = CourtBoundedFilter(persistence_frames=3)
    d = _det(0.50, 0.50, 0.55, 0.55, track_id=42)
    assert cbf.filter([d]) == []  # frame 1: skip
    assert cbf.filter([d]) == []  # frame 2: skip
    assert len(cbf.filter([d])) == 1  # frame 3: emit


def test_persistence_filter_resets_when_track_disappears():
    cbf = CourtBoundedFilter(persistence_frames=3)
    d1 = _det(0.50, 0.50, 0.55, 0.55, track_id=42)
    d2 = _det(0.40, 0.40, 0.45, 0.45, track_id=99)
    cbf.filter([d1])
    cbf.filter([d1])
    # track 42 が消える → カウンタ削除
    cbf.filter([d2])
    cbf.filter([d2])
    cbf.filter([d2])  # ここで track 99 が emit
    # 再び track 42 が来てもカウンタは 1 から
    assert cbf.filter([d1]) == []


def test_filter_with_court_adapter():
    H = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    a = CourtAdapter(homography=H, homography_inv=H,
                     roi_polygon=[[0.10, 0.10], [0.90, 0.10], [0.90, 0.90], [0.10, 0.90]])
    cbf = CourtBoundedFilter(court_adapter=a)
    out = cbf.filter([
        _det(0.50, 0.50, 0.55, 0.55, conf=0.9),  # ROI 内 → 残る
        _det(0.05, 0.05, 0.08, 0.08, conf=0.9),  # ROI 外 → 除外
    ])
    assert len(out) == 1


def test_reset_clears_persistence():
    cbf = CourtBoundedFilter(persistence_frames=3)
    d = _det(0.50, 0.50, 0.55, 0.55, track_id=1)
    cbf.filter([d])
    cbf.filter([d])
    cbf.reset()
    assert cbf.filter([d]) == []  # カウンタリセット後、また 1 から
