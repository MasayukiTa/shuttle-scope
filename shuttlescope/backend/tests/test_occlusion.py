"""Track A4: OcclusionDetector + OcclusionResolver テスト。

3 パターン (count_drop / bbox_expand / pre_occlusion_iou) と
4 信号 Hungarian 割当を検証。
"""
from __future__ import annotations

import pytest

from backend.cv.occlusion import (
    OcclusionDetector,
    OcclusionEvent,
    OcclusionPattern,
    OcclusionResolver,
    ResolverSignals,
)


# ─── Detector ─────────────────────────────────────────────────────────────────

def _det(label, x1, y1, x2, y2, hist=None, track_id=None):
    d = {"label": label, "bbox": [x1, y1, x2, y2]}
    if hist is not None:
        d["hist"] = hist
    if track_id is not None:
        d["track_id"] = track_id
    return d


def _disjoint_dets(n):
    """重なりゼロの bbox を n 個返す (P3 false positive 回避)。"""
    out = []
    for i in range(n):
        x = 0.05 + i * 0.20
        out.append(_det(f"x{i}", x, 0.05, x + 0.05, 0.10))
    return out


def test_p1_count_drop_fires_after_patience():
    det = OcclusionDetector(expected_players=4, count_drop_patience=3)
    events_1 = det.detect({}, _disjoint_dets(3), frame_index=0)
    events_2 = det.detect({}, _disjoint_dets(3), frame_index=1)
    events_3 = det.detect({}, _disjoint_dets(3), frame_index=2)
    p1_1 = [e for e in events_1 if e.pattern == OcclusionPattern.PLAYER_COUNT_DROP]
    p1_2 = [e for e in events_2 if e.pattern == OcclusionPattern.PLAYER_COUNT_DROP]
    p1_3 = [e for e in events_3 if e.pattern == OcclusionPattern.PLAYER_COUNT_DROP]
    assert p1_1 == [] and p1_2 == []
    assert len(p1_3) == 1


def test_p1_count_drop_resets_when_recovered():
    det = OcclusionDetector(expected_players=4, count_drop_patience=2)
    det.detect({}, _disjoint_dets(3), frame_index=0)  # streak=1
    det.detect({}, _disjoint_dets(4), frame_index=1)  # 戻る → streak=0
    events = det.detect({}, _disjoint_dets(3), frame_index=2)  # streak=1, patience=2 まだ
    p1 = [e for e in events if e.pattern == OcclusionPattern.PLAYER_COUNT_DROP]
    assert p1 == []


def test_p2_bbox_expansion_detects_merged_bbox():
    det = OcclusionDetector(expected_players=4)
    # frame 0: bbox area = 0.01
    det.detect({}, [_det("p_a", 0.0, 0.0, 0.1, 0.1)], frame_index=0)
    # frame 1: bbox area = 0.04 (4x) → expand 1.5x 超えで発火
    events = det.detect({}, [_det("p_a", 0.0, 0.0, 0.2, 0.2)], frame_index=1)
    assert any(e.pattern == OcclusionPattern.BBOX_EXPANSION for e in events)


def test_p3_pre_occlusion_iou_detects_overlap():
    det = OcclusionDetector(pre_occlusion_iou_thresh=0.3)
    # 2 つの bbox が大きく重なる
    detections = [
        _det("a", 0.10, 0.10, 0.30, 0.30),
        _det("b", 0.15, 0.15, 0.35, 0.35),
    ]
    events = det.detect({}, detections, frame_index=0)
    p3_events = [e for e in events if e.pattern == OcclusionPattern.PRE_OCCLUSION_IOU]
    assert len(p3_events) == 1
    assert set(p3_events[0].involved_labels) == {"a", "b"}


def test_p3_pre_occlusion_iou_below_threshold_no_fire():
    det = OcclusionDetector(pre_occlusion_iou_thresh=0.3)
    # わずかな重なり → IoU < 0.3
    detections = [
        _det("a", 0.10, 0.10, 0.20, 0.20),
        _det("b", 0.18, 0.18, 0.28, 0.28),
    ]
    events = det.detect({}, detections, frame_index=0)
    p3_events = [e for e in events if e.pattern == OcclusionPattern.PRE_OCCLUSION_IOU]
    assert p3_events == []


def test_detector_reset_clears_state():
    det = OcclusionDetector(expected_players=4, count_drop_patience=1)
    det.detect({}, [], frame_index=0)
    det.reset()
    # reset 後、空のフレームを 1 回入れても直ちには発火しない... と思いきや patience=1 なので 1 フレームで発火する
    # 状態クリア確認は streak が戻ったことを別経路で確認
    assert det._low_count_streak == 0
    assert det._prev_areas == {}


# ─── Resolver ─────────────────────────────────────────────────────────────────

def _ident(label, last_bbox, vel=(0.0, 0.0), reid=None, team=None):
    return {
        "label": label,
        "last_bbox": list(last_bbox),
        "vel_cx": vel[0],
        "vel_cy": vel[1],
        "frozen_reid": reid,
        "team": team,
    }


def test_resolver_returns_empty_for_empty_input():
    r = OcclusionResolver()
    assert r.resolve([], []) == {}


def test_resolver_motion_signal_picks_predicted_position():
    """直前位置 + 速度から最も近い detection が選ばれる。"""
    r = OcclusionResolver(weights=ResolverSignals(motion=1.0, court=0.0, reid=0.0, trajectory=0.0))
    idents = [
        _ident("p_a", (0.10, 0.20, 0.20, 0.40), vel=(0.05, 0.0)),  # 予測 cx ~ 0.20
    ]
    dets = [
        _det("?", 0.55, 0.20, 0.65, 0.40),  # 遠い
        _det("?", 0.20, 0.20, 0.30, 0.40),  # 予測位置に近い
    ]
    result = r.resolve(idents, dets)
    assert result.get(1) == "p_a"
    assert 0 not in result


def test_resolver_reid_signal_picks_similar_appearance():
    """frozen_reid と似た hist を持つ detection が優先される。"""
    r = OcclusionResolver(weights=ResolverSignals(motion=0.0, court=0.0, reid=1.0, trajectory=0.0))
    idents = [
        _ident("p_a", (0.0, 0.0, 0.1, 0.1), reid=[1.0, 0.0, 0.0]),
    ]
    dets = [
        _det("?", 0.5, 0.5, 0.6, 0.6, hist=[0.0, 1.0, 0.0]),  # 類似度 0
        _det("?", 0.5, 0.5, 0.6, 0.6, hist=[0.9, 0.1, 0.0]),  # 類似度高
    ]
    result = r.resolve(idents, dets)
    assert result.get(1) == "p_a"


def test_resolver_court_constraint_prefers_correct_half():
    """team=near のはずの選手が、自陣 (y > 0.5) detection を選ぶ。"""
    r = OcclusionResolver(weights=ResolverSignals(motion=0.0, court=1.0, reid=0.0, trajectory=0.0))
    idents = [
        _ident("p_near", (0.5, 0.7, 0.6, 0.9), team="near"),
    ]
    dets = [
        _det("?", 0.5, 0.20, 0.6, 0.30),  # 相手陣 → reject
        _det("?", 0.5, 0.70, 0.6, 0.85),  # 自陣 → accept
    ]
    result = r.resolve(idents, dets)
    assert result.get(1) == "p_near"


def test_resolver_hungarian_one_to_one():
    """2 identity x 2 detection で 1-to-1 割当。"""
    r = OcclusionResolver(weights=ResolverSignals(motion=1.0, court=0.0, reid=0.0, trajectory=0.0))
    idents = [
        _ident("a", (0.10, 0.20, 0.20, 0.40)),
        _ident("b", (0.70, 0.20, 0.80, 0.40)),
    ]
    dets = [
        _det("?", 0.10, 0.20, 0.20, 0.40),  # → a
        _det("?", 0.70, 0.20, 0.80, 0.40),  # → b
    ]
    result = r.resolve(idents, dets)
    assert result == {0: "a", 1: "b"}


def test_resolver_below_min_score_drops():
    r = OcclusionResolver(
        weights=ResolverSignals(motion=1.0, court=0.0, reid=0.0, trajectory=0.0),
        min_score=0.95,
    )
    idents = [_ident("a", (0.10, 0.20, 0.20, 0.40))]
    dets = [_det("?", 0.90, 0.20, 0.95, 0.40)]
    result = r.resolve(idents, dets)
    assert result == {}
