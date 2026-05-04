"""Track C3: SwingDetector テスト。

合成 PoseResult 列を入れ、wrist 速度 + elbow 角度の閾値超えで
SwingEvent が返ることを確認。
"""
from __future__ import annotations

import math
import numpy as np
import pytest

from backend.cv.rtmpose import KP, PoseResult
from backend.cv.swing_detector import SwingDetector, SwingEvent


def _kp_with(values: dict, conf: float = 0.9) -> np.ndarray:
    """指定インデックスだけ値を入れた (17,3) keypoints を作る。"""
    arr = np.zeros((17, 3), dtype=np.float32)
    for idx, (x, y) in values.items():
        arr[idx, 0] = x
        arr[idx, 1] = y
        arr[idx, 2] = conf
    return arr


def _pose(label, kpts):
    return PoseResult(track_id=None, label=label, bbox=[0, 0, 0.1, 0.2],
                      keypoints=kpts, confidence=0.9)


def test_no_swing_returns_none_when_static():
    det = SwingDetector(fps=60, window_seconds=0.1, wrist_vel_threshold=0.5,
                        elbow_change_min=10)
    static_kp = _kp_with({
        KP.R_SHOULDER: (0.5, 0.5),
        KP.R_ELBOW: (0.5, 0.55),
        KP.R_WRIST: (0.5, 0.6),
    })
    for i in range(6):
        ev = det.process_frame(i, i / 60.0, [_pose("player_a", static_kp.copy())])
    assert ev is None


def test_swing_detected_with_fast_wrist_and_elbow_change():
    det = SwingDetector(fps=60, window_seconds=0.1, wrist_vel_threshold=1.0,
                        elbow_change_min=20.0)
    # シンプルケース: 2 フレームだけ与え、elbow と wrist が大きく動く
    kp1 = _kp_with({
        KP.R_SHOULDER: (0.50, 0.30),
        KP.R_ELBOW: (0.55, 0.50),
        KP.R_WRIST: (0.50, 0.70),  # 真下に伸びた腕
    })
    kp2 = _kp_with({
        KP.R_SHOULDER: (0.50, 0.30),
        KP.R_ELBOW: (0.55, 0.50),
        KP.R_WRIST: (0.85, 0.50),  # 右に大きく振った
    })
    det.process_frame(0, 0.0, [_pose("player_a", kp1)])
    ev = det.process_frame(1, 1 / 60.0, [_pose("player_a", kp2)])
    assert ev is not None
    assert ev.identity == "player_a"
    assert ev.hand == "right"
    assert ev.wrist_velocity >= 1.0
    assert ev.elbow_angle_change >= 20.0


def test_low_keypoint_confidence_skipped():
    det = SwingDetector(fps=60, wrist_vel_threshold=0.5, elbow_change_min=10,
                        min_kp_confidence=0.5)
    fast_kp1 = _kp_with({
        KP.R_SHOULDER: (0.50, 0.30),
        KP.R_ELBOW: (0.55, 0.50),
        KP.R_WRIST: (0.50, 0.70),
    }, conf=0.2)  # 低 conf
    fast_kp2 = _kp_with({
        KP.R_SHOULDER: (0.50, 0.30),
        KP.R_ELBOW: (0.55, 0.50),
        KP.R_WRIST: (0.85, 0.50),
    }, conf=0.2)
    det.process_frame(0, 0.0, [_pose("player_a", fast_kp1)])
    ev = det.process_frame(1, 0.05, [_pose("player_a", fast_kp2)])
    assert ev is None


def test_cooldown_prevents_double_fire():
    det = SwingDetector(fps=60, wrist_vel_threshold=1.0, elbow_change_min=20,
                        cooldown_frames=5)
    kp1 = _kp_with({
        KP.R_SHOULDER: (0.50, 0.30),
        KP.R_ELBOW: (0.55, 0.50),
        KP.R_WRIST: (0.50, 0.70),
    })
    kp2 = _kp_with({
        KP.R_SHOULDER: (0.50, 0.30),
        KP.R_ELBOW: (0.55, 0.50),
        KP.R_WRIST: (0.85, 0.50),
    })
    det.process_frame(0, 0.0, [_pose("player_a", kp1)])
    ev1 = det.process_frame(1, 1 / 60.0, [_pose("player_a", kp2)])
    assert ev1 is not None
    # 直後の同じ動きは cooldown 中なので発火しない
    ev2 = det.process_frame(2, 2 / 60.0, [_pose("player_a", kp1)])
    ev3 = det.process_frame(3, 3 / 60.0, [_pose("player_a", kp2)])
    assert ev3 is None  # 2 frame しか経ってない


def test_left_hand_also_detected():
    det = SwingDetector(fps=60, wrist_vel_threshold=1.0, elbow_change_min=20)
    kp1 = _kp_with({
        KP.L_SHOULDER: (0.50, 0.30),
        KP.L_ELBOW: (0.45, 0.50),
        KP.L_WRIST: (0.50, 0.70),
    })
    kp2 = _kp_with({
        KP.L_SHOULDER: (0.50, 0.30),
        KP.L_ELBOW: (0.45, 0.50),
        KP.L_WRIST: (0.10, 0.50),
    })
    det.process_frame(0, 0.0, [_pose("player_a", kp1)])
    ev = det.process_frame(1, 1 / 60.0, [_pose("player_a", kp2)])
    assert ev is not None
    assert ev.hand == "left"


def test_multiple_players_pick_highest_confidence():
    det = SwingDetector(fps=60, wrist_vel_threshold=0.5, elbow_change_min=10)
    # player_a: 弱いスイング, player_b: 強いスイング
    a_kp1 = _kp_with({
        KP.R_SHOULDER: (0.20, 0.30), KP.R_ELBOW: (0.22, 0.50),
        KP.R_WRIST: (0.20, 0.70),
    })
    a_kp2 = _kp_with({
        KP.R_SHOULDER: (0.20, 0.30), KP.R_ELBOW: (0.22, 0.50),
        KP.R_WRIST: (0.23, 0.65),  # わずかに動いた程度
    })
    b_kp1 = _kp_with({
        KP.R_SHOULDER: (0.70, 0.30), KP.R_ELBOW: (0.75, 0.50),
        KP.R_WRIST: (0.70, 0.70),
    })
    b_kp2 = _kp_with({
        KP.R_SHOULDER: (0.70, 0.30), KP.R_ELBOW: (0.75, 0.50),
        KP.R_WRIST: (0.99, 0.50),
    })
    det.process_frame(0, 0.0, [_pose("player_a", a_kp1), _pose("player_b", b_kp1)])
    ev = det.process_frame(1, 1 / 60.0, [_pose("player_a", a_kp2), _pose("player_b", b_kp2)])
    assert ev is not None
    assert ev.identity == "player_b"


def test_reset_clears_history():
    det = SwingDetector()
    det._history["x"].poses.append(_pose("x", _kp_with({})))
    det._last_swing_frame["x"] = 5
    det.reset()
    assert det._history == {}
    assert det._last_swing_frame == {}
