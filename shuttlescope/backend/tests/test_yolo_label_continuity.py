"""Track A1: YOLO _assign_player_labels の track_id 継続テスト。

ByteTrack track_id が連続する限り、同じ player ラベルが維持されることを検証する。
"""
from __future__ import annotations

import pytest

from backend.yolo.inference import YOLOInference


def _det(label, conf, x, y, track_id=None):
    return {
        "label": label,
        "confidence": conf,
        "centroid": (x, y),
        "track_id": track_id,
    }


def test_track_id_continuity_preserves_label():
    """同じ track_id は次フレームでも同じ player ラベルを保つ。"""
    inf = YOLOInference()
    # Frame 1: 4 人
    f1 = inf._assign_player_labels([
        _det("person", 0.9, 0.2, 0.2, track_id=10),
        _det("person", 0.85, 0.8, 0.2, track_id=11),
        _det("person", 0.95, 0.2, 0.8, track_id=12),
        _det("person", 0.92, 0.8, 0.8, track_id=13),
    ])
    labels_f1 = {d["track_id"]: d["label"] for d in f1 if d["label"].startswith("player_")}
    assert len(labels_f1) == 4
    # Frame 2: 同じ track_id、座標は揺らぎあり
    f2 = inf._assign_player_labels([
        _det("person", 0.88, 0.3, 0.25, track_id=10),
        _det("person", 0.86, 0.75, 0.22, track_id=11),
        _det("person", 0.93, 0.18, 0.78, track_id=12),
        _det("person", 0.91, 0.82, 0.85, track_id=13),
    ])
    labels_f2 = {d["track_id"]: d["label"] for d in f2 if d["label"].startswith("player_")}
    # ラベル完全一致
    assert labels_f1 == labels_f2


def test_track_id_swap_in_position_does_not_swap_label():
    """位置が swap しても track_id が一貫していればラベルは swap しない。"""
    inf = YOLOInference()
    # Frame 1
    inf._assign_player_labels([
        _det("person", 0.9, 0.2, 0.2, track_id=1),
        _det("person", 0.9, 0.8, 0.2, track_id=2),
    ])
    # Frame 2: track_id=1 の選手が右に移動 (位置交換)
    f2 = inf._assign_player_labels([
        _det("person", 0.9, 0.85, 0.2, track_id=1),
        _det("person", 0.9, 0.15, 0.2, track_id=2),
    ])
    map2 = {d["track_id"]: d["label"] for d in f2}
    # track_id 1 は player_a を維持 (位置でなく ID で判断)
    assert map2[1] == "player_a"
    assert map2[2] == "player_b"


def test_no_track_id_falls_back_to_position():
    """track_id が無い (ByteTrack OFF) 場合は従来の位置ベース割当。"""
    inf = YOLOInference()
    f = inf._assign_player_labels([
        _det("person", 0.9, 0.2, 0.2),
        _det("person", 0.9, 0.8, 0.2),
        _det("person", 0.9, 0.2, 0.8),
        _det("person", 0.9, 0.8, 0.8),
    ])
    labels = [d["label"] for d in f if d["label"].startswith("player_")]
    assert sorted(labels) == ["player_a", "player_b", "player_c", "player_d"]


def test_new_track_id_gets_unused_label():
    """既知 track_id がいて新しい track_id が来た場合、未使用ラベルを割り当て。"""
    inf = YOLOInference()
    # Frame 1: 1 人
    inf._assign_player_labels([
        _det("person", 0.9, 0.2, 0.2, track_id=100),
    ])
    # Frame 2: 同じ track_id + 新規 track_id
    f2 = inf._assign_player_labels([
        _det("person", 0.9, 0.2, 0.2, track_id=100),
        _det("person", 0.9, 0.8, 0.8, track_id=200),
    ])
    map2 = {d["track_id"]: d["label"] for d in f2}
    assert map2[100] == "player_a"
    # 200 は未使用ラベル (player_b/c/d のいずれか)
    assert map2[200] in ("player_b", "player_c", "player_d")


def test_reset_label_continuity_clears_map():
    """reset_tracker() / reset_label_continuity() で継続マップが消える。"""
    inf = YOLOInference()
    inf._assign_player_labels([
        _det("person", 0.9, 0.2, 0.2, track_id=10),
    ])
    assert inf._prev_track_labels == {10: "player_a"}
    inf.reset_label_continuity()
    assert inf._prev_track_labels == {}


def test_default_bytetrack_enabled():
    """Track A1: ByteTrack はデフォルト ON。"""
    import os
    # env を一時クリア
    old = os.environ.pop("SS_YOLO_BYTETRACK", None)
    try:
        inf = YOLOInference()
        assert inf._bt_enabled is True
    finally:
        if old is not None:
            os.environ["SS_YOLO_BYTETRACK"] = old


def test_explicit_off_disables_bytetrack():
    """SS_YOLO_BYTETRACK=0 を明示すれば OFF。"""
    import os
    old = os.environ.get("SS_YOLO_BYTETRACK")
    os.environ["SS_YOLO_BYTETRACK"] = "0"
    try:
        inf = YOLOInference()
        assert inf._bt_enabled is False
    finally:
        if old is not None:
            os.environ["SS_YOLO_BYTETRACK"] = old
        else:
            os.environ.pop("SS_YOLO_BYTETRACK", None)
