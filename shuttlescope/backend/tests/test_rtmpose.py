"""Track C2: RTMPoseEngine テスト。

graceful degradation (mmpose/onnx 未インストール) と PoseResult 型を検証。
実 GPU 推論は prod (5060Ti) 上で smoke 確認する。
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.cv.rtmpose import KP, PoseResult, RTMPoseEngine, get_rtmpose_engine


def test_engine_load_does_not_raise_without_weights():
    eng = RTMPoseEngine()
    # 重みファイルが無い CI 環境でも例外を投げない
    result = eng.load()
    # True/False どちらでも OK、例外でないこと
    assert result in (True, False)


def test_infer_returns_unloaded_results_when_not_loaded():
    eng = RTMPoseEngine()
    eng._loaded = False
    detections = [
        {"bbox": [0.1, 0.1, 0.2, 0.3], "track_id": 5, "label": "player_a"},
        {"bbox": [0.7, 0.1, 0.8, 0.3], "track_id": 6, "label": "player_b"},
    ]
    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    out = eng.infer(frame, detections)
    assert len(out) == 2
    for r in out:
        assert isinstance(r, PoseResult)
        assert r.backend == "unloaded"
        assert r.keypoints.shape == (17, 3)
        assert r.confidence == 0.0


def test_pose_result_has_kp_helpers():
    kp = np.zeros((17, 3), dtype=np.float32)
    kp[KP.R_WRIST] = [0.45, 0.55, 0.9]
    r = PoseResult(track_id=1, label="player_a", bbox=[0.0, 0.0, 0.1, 0.2], keypoints=kp)
    assert r.kp_xy(KP.R_WRIST) == (pytest.approx(0.45), pytest.approx(0.55))
    assert r.kp_conf(KP.R_WRIST) == pytest.approx(0.9)


def test_singleton_engine_returns_same_instance():
    e1 = get_rtmpose_engine()
    e2 = get_rtmpose_engine()
    assert e1 is e2


def test_kp_constants_cover_17_indices():
    """COCO 17 keypoint インデックスがすべて 0-16。"""
    indices = [v for k, v in vars(KP).items() if not k.startswith("_") and isinstance(v, int)]
    assert sorted(indices) == list(range(17))


def test_engine_backend_name_starts_unloaded():
    eng = RTMPoseEngine()
    assert eng.backend_name == "unloaded"


def test_infer_skips_invalid_bbox():
    eng = RTMPoseEngine()
    eng._loaded = False
    out = eng.infer(np.zeros((50, 50, 3), dtype=np.uint8),
                    [{"bbox": [0.1, 0.1, 0.2]}])  # 不正 bbox
    # unloaded なので 1 件返るが keypoints は zeros
    assert len(out) == 1
