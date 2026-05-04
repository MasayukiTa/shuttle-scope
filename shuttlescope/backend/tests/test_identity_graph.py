"""Track A3: identity_graph.track_identities ユニットテスト。

routers/yolo.py から抽出された行動互換性を検証。
"""
from __future__ import annotations

import pytest

from backend.cv.identity_graph import (
    IdentityGraph,
    IdentityState,
    bbox_iou,
    cos_sim,
    cos_sim_gallery,
    foot_in_roi,
    track_identities,
)


# ─── ヘルパー関数 ─────────────────────────────────────────────────────────────

def test_bbox_iou_no_overlap():
    assert bbox_iou([0, 0, 0.1, 0.1], [0.5, 0.5, 0.6, 0.6]) == 0.0


def test_bbox_iou_full_overlap():
    assert bbox_iou([0.2, 0.2, 0.4, 0.4], [0.2, 0.2, 0.4, 0.4]) == pytest.approx(1.0)


def test_bbox_iou_invalid_shape():
    assert bbox_iou([0, 0, 0.1], [0.2, 0.2, 0.3, 0.3]) == 0.0


def test_cos_sim_identical():
    a = [0.5, 0.5]
    assert cos_sim(a, a) == pytest.approx(1.0, abs=1e-6)


def test_cos_sim_orthogonal():
    assert cos_sim([1.0, 0.0], [0.0, 1.0]) == pytest.approx(0.0, abs=1e-6)


def test_cos_sim_neutral_when_empty():
    assert cos_sim([], [0.5]) == 0.5


def test_cos_sim_gallery_picks_max():
    g = [[1.0, 0.0], [0.0, 1.0]]
    assert cos_sim_gallery(g, [1.0, 0.0]) == pytest.approx(1.0)


def test_foot_in_roi_no_roi_is_true():
    assert foot_in_roi([0.0, 0.0, 1.0, 1.0], None) is True


def test_foot_in_roi_inside():
    roi = {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}
    assert foot_in_roi([0.4, 0.4, 0.6, 0.8], roi) is True


def test_foot_in_roi_outside():
    roi = {"x": 0.0, "y": 0.0, "w": 0.5, "h": 0.5}
    # foot_y = 0.9 → outside roi (y_max=0.5+margin=0.53)
    assert foot_in_roi([0.4, 0.7, 0.6, 0.9], roi) is False


# ─── track_identities メイン関数 ──────────────────────────────────────────────

def _frame(idx, ts, *players):
    return {
        "frame_idx": idx,
        "timestamp_sec": ts,
        "players": list(players),
    }


def _player(bbox, hist=None, track_id=None):
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    p = {"bbox": bbox, "cx_n": cx, "cy_n": cy, "hist": hist or []}
    if track_id is not None:
        p["track_id"] = track_id
    return p


def test_track_identities_empty_input():
    assert track_identities([], 0.0, []) == []


def test_track_identities_no_assignments_returns_empty():
    frames = [_frame(0, 0.0, _player([0.1, 0.1, 0.2, 0.3]))]
    assert track_identities(frames, 0.0, []) == []


def test_track_identities_single_player_propagation():
    """1 人を 3 フレーム追跡して frame_idx 全部に出る。"""
    frames = [
        _frame(0, 0.0, _player([0.10, 0.10, 0.20, 0.30])),
        _frame(1, 0.033, _player([0.12, 0.10, 0.22, 0.30])),
        _frame(2, 0.066, _player([0.14, 0.10, 0.24, 0.30])),
    ]
    assignments = [
        {"player_key": "player_a", "detection_index": 0, "bbox": [0.10, 0.10, 0.20, 0.30]},
    ]
    out = track_identities(frames, 0.0, assignments)
    assert len(out) == 3
    keys = [p["player_key"] for f in out for p in f["players"]]
    assert all(k == "player_a" for k in keys)


def test_track_identities_two_players_assignment_stable():
    """2 人を逆方向に動かしても一貫したラベルが維持される。"""
    frames = [
        _frame(0, 0.0,
               _player([0.10, 0.20, 0.18, 0.40]),
               _player([0.80, 0.20, 0.88, 0.40])),
        _frame(1, 0.033,
               _player([0.13, 0.20, 0.21, 0.40]),
               _player([0.77, 0.20, 0.85, 0.40])),
    ]
    assignments = [
        {"player_key": "player_a", "detection_index": 0, "bbox": [0.10, 0.20, 0.18, 0.40]},
        {"player_key": "player_b", "detection_index": 1, "bbox": [0.80, 0.20, 0.88, 0.40]},
    ]
    out = track_identities(frames, 0.0, assignments)
    # frame 1 で player_a の cx は 0.13 付近、player_b は 0.81 付近のはず
    f1 = next(f for f in out if f["frame_idx"] == 1)
    pa = next(p for p in f1["players"] if p["player_key"] == "player_a")
    pb = next(p for p in f1["players"] if p["player_key"] == "player_b")
    assert pa["cx_n"] < pb["cx_n"]


def test_track_identities_lost_then_predicted():
    """検出が消えても lost=True で予測位置が出る。"""
    frames = [
        _frame(0, 0.0, _player([0.10, 0.20, 0.18, 0.40])),
        _frame(1, 0.033),  # 空 → lost
    ]
    assignments = [
        {"player_key": "player_a", "detection_index": 0, "bbox": [0.10, 0.20, 0.18, 0.40]},
    ]
    out = track_identities(frames, 0.0, assignments)
    f1 = [f for f in out if f["frame_idx"] == 1][0]
    pa = f1["players"][0]
    assert pa["lost"] is True


# ─── IdentityGraph wrapper ───────────────────────────────────────────────────

def test_identity_graph_facade_calls_track_identities():
    g = IdentityGraph()
    frames = [_frame(0, 0.0, _player([0.1, 0.2, 0.2, 0.4]))]
    out = g.track(frames, 0.0, [{"player_key": "player_a", "detection_index": 0, "bbox": None}])
    assert len(out) == 1


def test_identity_graph_pose_injection_no_op_safe():
    g = IdentityGraph()
    g.inject_pose_features("player_a", [0.5, 0.5, 1.0])
    assert g._identities["player_a"].pose_keypoints == [0.5, 0.5, 1.0]


def test_identity_graph_get_confidence_default_zero():
    g = IdentityGraph()
    assert g.get_confidence("player_a") == 0.0


def test_identity_graph_get_confidence_decreases_with_lost():
    g = IdentityGraph()
    g._identities["player_a"] = IdentityState(label="player_a", lost_count=0)
    assert g.get_confidence("player_a") == pytest.approx(1.0)
    g._identities["player_a"].lost_count = 15
    assert g.get_confidence("player_a") == 0.0


def test_identity_graph_reset():
    g = IdentityGraph()
    g.inject_pose_features("player_a", [0.0])
    g.reset()
    assert g._identities == {}
