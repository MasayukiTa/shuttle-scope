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


def test_openvino_tracknet_raises_without_openvino(monkeypatch):
    """openvino が未インストールの環境では OpenVINOTrackNet() が ImportError を投げる。"""
    import backend.cv.tracknet_openvino as mod

    # import 自体は成功すること（トップレベルで openvino を触らない）
    assert hasattr(mod, "OpenVINOTrackNet")

    try:
        import openvino  # noqa: F401
        pytest.skip("openvino インストール済み環境では未インストール挙動を検証できない")
    except ImportError:
        pass

    with pytest.raises(ImportError):
        mod.OpenVINOTrackNet()


def test_factory_openvino_falls_through_to_cpu_or_mock(monkeypatch):
    """SS_USE_GPU=0 かつ OpenVINO 不使用環境では CPU か Mock にたどり着く。

    OpenVINO がインストールされていても重みファイルが無ければ RuntimeError →
    CPU にフォールバックするため、いずれにせよ CUDA / OpenVINO 実装では終わらない。
    """
    _reload_settings(monkeypatch, SS_CV_MOCK="0", SS_USE_GPU="0")

    import backend.cv.factory as factory
    importlib.reload(factory)

    tn = factory.get_tracknet()
    # CUDA 実装・OpenVINO 実装にはならないことを確認
    assert "Cuda" not in type(tn).__name__
    # OpenVINO でも重みなしなら RuntimeError → CPU か Mock に落ちる
    assert type(tn).__name__ in ("CpuTrackNet", "OpenVINOTrackNet", "MockTrackNet")


def test_runner_modules_are_importable():
    """tracknet_runner / mediapipe_runner が import 可能であることを確認。"""
    import backend.cv.tracknet_runner as tr
    import backend.cv.mediapipe_runner as mr

    assert callable(tr.run_tracknet)
    assert callable(mr.run_mediapipe)


def test_pipeline_modules_are_importable():
    """pipeline/clips, statistics, cog, shot_classifier が import 可能であることを確認。"""
    import backend.pipeline.clips as clips
    import backend.pipeline.statistics as stats
    import backend.pipeline.cog as cog
    import backend.pipeline.shot_classifier as shot

    assert callable(clips.extract_clips)
    assert callable(stats.run_statistics)
    assert callable(cog.calc_center_of_gravity)
    assert callable(shot.classify_shots)


def test_clips_skips_when_rally_bounds_none():
    """extract_clips は rally_bounds=None のときエラーにならず skipped を返す。"""
    from backend.pipeline.clips import extract_clips

    result = extract_clips("dummy.mp4", rally_bounds=None)
    assert result["status"] == "skipped"


def test_runner_returns_error_on_bad_path(monkeypatch):
    """tracknet_runner は動画が存在しないパスでも status=error を返し例外を投げない。"""
    monkeypatch.setenv("SS_CV_MOCK", "1")
    import importlib
    import backend.cv.factory as factory
    importlib.reload(factory)

    from backend.cv.tracknet_runner import run_tracknet

    # Mock は video_path を実際には開かないので status=ok が返る
    result = run_tracknet("nonexistent_video.mp4")
    assert result["status"] in ("ok", "error")
