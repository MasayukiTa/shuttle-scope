"""person v2: court area filter と NMS IoU env のテスト。

- filter_detections_by_court() がコート外の person を drop すること
- margin で許容範囲が広がること
- polygon=None / 空 / 不正 のとき no-op (fail-safe)
- env SS_PERSON_COURT_FILTER=0 で完全 no-op
- SS_PERSON_NMS_IOU env が読み込めること
- player_other / person ラベルもフィルタ対象、shuttle は対象外
"""
from __future__ import annotations

import os

import pytest

from backend.yolo.inference import (
    filter_detections_by_court,
    _get_nms_iou_threshold,
    _point_in_polygon,
    _expand_polygon,
)


# コート 4 コーナー (正規化座標): TL=(0.2,0.2) TR=(0.8,0.2) BR=(0.8,0.8) BL=(0.2,0.8)
COURT = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]


def _det(label, fx, fy, **extra):
    d = {
        "label": label,
        "confidence": 0.9,
        "bbox": [fx - 0.02, fy - 0.1, fx + 0.02, fy],
        "centroid": [fx, fy - 0.05],
        "foot_point": [fx, fy],
    }
    d.update(extra)
    return d


def test_inside_court_kept():
    dets = [_det("player_a", 0.5, 0.5)]
    out = filter_detections_by_court(dets, COURT, margin=1.0)
    assert len(out) == 1


def test_outside_court_dropped():
    """審判 (コート横) / 観客 (コート上方) を drop"""
    dets = [
        _det("player_a", 0.5, 0.5),       # 中央 → keep
        _det("player_b", 0.05, 0.5),      # 左端外 → drop
        _det("player_c", 0.5, 0.05),      # 上端外 (掲示板/観客) → drop
        _det("player_d", 0.95, 0.95),     # 右下外 → drop
    ]
    out = filter_detections_by_court(dets, COURT, margin=1.0)
    labels = [d["label"] for d in out]
    assert labels == ["player_a"]


def test_margin_allows_line_overshoot():
    """margin=1.5 ならコートラインを少しはみ出した選手は keep"""
    # 0.85 は元 polygon (0.2-0.8) の外だが margin 1.5 で重心 0.5 中心に 0.05-0.95 まで拡大
    dets = [_det("player_a", 0.85, 0.5)]
    out_no_margin = filter_detections_by_court(dets, COURT, margin=1.0)
    out_margin = filter_detections_by_court(dets, COURT, margin=1.5)
    assert len(out_no_margin) == 0
    assert len(out_margin) == 1


def test_polygon_none_is_noop():
    dets = [_det("player_a", 0.05, 0.5)]
    out = filter_detections_by_court(dets, None)
    assert len(out) == 1


def test_polygon_empty_is_noop():
    dets = [_det("player_a", 0.05, 0.5)]
    out = filter_detections_by_court(dets, [])
    assert len(out) == 1


def test_polygon_too_few_points_is_noop():
    dets = [_det("player_a", 0.05, 0.5)]
    out = filter_detections_by_court(dets, [[0, 0], [1, 0]])
    assert len(out) == 1


def test_env_disable_is_noop():
    """SS_PERSON_COURT_FILTER=0 で完全 no-op"""
    old = os.environ.get("SS_PERSON_COURT_FILTER")
    os.environ["SS_PERSON_COURT_FILTER"] = "0"
    try:
        dets = [_det("player_a", 0.05, 0.5)]
        out = filter_detections_by_court(dets, COURT, margin=1.0)
        assert len(out) == 1
    finally:
        if old is None:
            os.environ.pop("SS_PERSON_COURT_FILTER", None)
        else:
            os.environ["SS_PERSON_COURT_FILTER"] = old


def test_shuttle_label_not_filtered():
    """shuttle ラベルは person 系でないので filter 対象外 (素通し)"""
    dets = [
        {"label": "shuttle", "confidence": 0.9, "foot_point": [0.05, 0.05]},
    ]
    out = filter_detections_by_court(dets, COURT, margin=1.0)
    assert len(out) == 1


def test_player_other_filtered():
    """player_other (5 人目以降) も filter 対象"""
    dets = [_det("player_other", 0.05, 0.05)]
    out = filter_detections_by_court(dets, COURT, margin=1.0)
    assert len(out) == 0


def test_missing_foot_point_kept():
    """foot_point/centroid 欠落の検出は念のため keep (fail-safe)"""
    dets = [{"label": "player_a", "confidence": 0.9}]
    out = filter_detections_by_court(dets, COURT, margin=1.0)
    assert len(out) == 1


def test_nms_iou_default():
    """env 未設定なら 0.45"""
    old = os.environ.pop("SS_PERSON_NMS_IOU", None)
    try:
        assert _get_nms_iou_threshold() == 0.45
    finally:
        if old is not None:
            os.environ["SS_PERSON_NMS_IOU"] = old


def test_nms_iou_env_override():
    """SS_PERSON_NMS_IOU=0.30 で重なり許容を緩める"""
    old = os.environ.get("SS_PERSON_NMS_IOU")
    os.environ["SS_PERSON_NMS_IOU"] = "0.30"
    try:
        assert _get_nms_iou_threshold() == pytest.approx(0.30)
    finally:
        if old is None:
            os.environ.pop("SS_PERSON_NMS_IOU", None)
        else:
            os.environ["SS_PERSON_NMS_IOU"] = old


def test_nms_iou_invalid_falls_back():
    """不正値はデフォルトに fallback"""
    old = os.environ.get("SS_PERSON_NMS_IOU")
    os.environ["SS_PERSON_NMS_IOU"] = "abc"
    try:
        assert _get_nms_iou_threshold() == 0.45
    finally:
        if old is None:
            os.environ.pop("SS_PERSON_NMS_IOU", None)
        else:
            os.environ["SS_PERSON_NMS_IOU"] = old


def test_nms_iou_out_of_range_falls_back():
    old = os.environ.get("SS_PERSON_NMS_IOU")
    os.environ["SS_PERSON_NMS_IOU"] = "1.5"
    try:
        assert _get_nms_iou_threshold() == 0.45
    finally:
        if old is None:
            os.environ.pop("SS_PERSON_NMS_IOU", None)
        else:
            os.environ["SS_PERSON_NMS_IOU"] = old


def test_expand_polygon_scales_around_centroid():
    poly = [[0.2, 0.2], [0.8, 0.2], [0.8, 0.8], [0.2, 0.8]]
    expanded = _expand_polygon(poly, 2.0)
    # 重心 (0.5, 0.5) を中心に 2 倍 → corners は (-0.1, -0.1)..(1.1, 1.1)
    assert expanded[0] == pytest.approx([-0.1, -0.1])
    assert expanded[2] == pytest.approx([1.1, 1.1])


def test_point_in_polygon_basic():
    poly = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]
    assert _point_in_polygon(0.5, 0.5, poly) is True
    assert _point_in_polygon(1.5, 0.5, poly) is False
    assert _point_in_polygon(-0.1, 0.5, poly) is False
