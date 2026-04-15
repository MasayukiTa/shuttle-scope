"""INFRA Phase A: CV factory / gpu_health のテスト。

重要:
    - torch / mediapipe / pynvml が未インストールでも全テストが通ること。
    - SS_USE_GPU / SS_CV_MOCK は monkeypatch で切替える。
"""
from __future__ import annotations

import importlib

import pytest


def _reload_settings(monkeypatch, **env):
    """環境変数を差し替えた上で backend.config を再読込する。"""
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    import backend.config as cfg

    importlib.reload(cfg)
    return cfg.settings


def test_factory_returns_mock_when_ss_cv_mock(monkeypatch):
    """SS_CV_MOCK=1 のとき TrackNet / Pose ともに Mock が返る。"""
    _reload_settings(monkeypatch, SS_CV_MOCK="1", SS_USE_GPU="0")

    # factory も再読込して最新 settings を拾わせる
    import backend.cv.factory as factory

    importlib.reload(factory)

    from backend.cv.tracknet_mock import MockTrackNet
    from backend.cv.pose_mock import MockPose

    tn = factory.get_tracknet()
    pose = factory.get_pose()
    assert isinstance(tn, MockTrackNet)
    assert isinstance(pose, MockPose)


def test_factory_does_not_import_cuda_when_gpu_off(monkeypatch):
    """SS_USE_GPU=0 のとき CPU か Mock が返る。CUDA (torch) が無くても通ること。"""
    _reload_settings(monkeypatch, SS_CV_MOCK="0", SS_USE_GPU="0")

    import backend.cv.factory as factory

    importlib.reload(factory)

    from backend.cv.base import PoseInferencer, TrackNetInferencer

    tn = factory.get_tracknet()
    pose = factory.get_pose()
    # Protocol 準拠 (runtime_checkable) で確認
    assert isinstance(tn, TrackNetInferencer)
    assert isinstance(pose, PoseInferencer)
    # CUDA 実装ではないことを確認
    assert "Cuda" not in type(tn).__name__
    assert "Cuda" not in type(pose).__name__


def test_mock_tracknet_returns_900_frames():
    """Mock TrackNet はデフォルトで 30 秒 × 30fps = 900 frame 返す (決定的)。"""
    from backend.cv.tracknet_mock import MockTrackNet

    m = MockTrackNet()
    samples = m.run("dummy_video.mp4")
    assert len(samples) == 900
    assert samples[0].frame == 0
    assert samples[-1].frame == 899
    # 決定的: 同じ入力 → 同じ出力
    again = m.run("dummy_video.mp4")
    assert samples[0].x == again[0].x and samples[0].y == again[0].y


def test_mock_pose_returns_two_sides():
    """Mock Pose は a / b 両選手ぶんのサンプルを返す。"""
    from backend.cv.pose_mock import MockPose

    m = MockPose()
    samples = m.run("dummy.mp4")
    sides = {s.side for s in samples}
    assert sides == {"a", "b"}
    # 900 frame × 2 side = 1800
    assert len(samples) == 1800


def test_cuda_tracknet_raises_without_torch(monkeypatch):
    """torch が無い環境では CudaTrackNet() が ImportError を投げる (モジュール import 自体は成功)。"""
    import backend.cv.tracknet_cuda as mod

    # import 自体は成功していること (トップレベルで torch を触らない)
    assert hasattr(mod, "CudaTrackNet")

    try:
        import torch  # noqa: F401

        # torch がある環境ではこのテストは skip
        pytest.skip("torch インストール済み環境では未インストール挙動を検証できない")
    except ImportError:
        pass

    with pytest.raises(ImportError):
        mod.CudaTrackNet()


def test_gpu_health_probe_returns_dict_without_pynvml():
    """pynvml 未インストールでも probe() は dict を返し例外を投げない。"""
    from backend.services import gpu_health

    result = gpu_health.probe()
    assert isinstance(result, dict)
    assert "available" in result
    # 未インストール時の典型
    if not result["available"]:
        assert "reason" in result


def test_backend_main_imports_without_gpu_deps():
    """torch / mediapipe / pynvml 未インストールでも backend.main が import できる。"""
    # 既に import 済みでもエラー無く再取得できれば OK
    mod = importlib.import_module("backend.main")
    assert hasattr(mod, "app")
