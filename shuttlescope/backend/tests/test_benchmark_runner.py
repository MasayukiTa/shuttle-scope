"""ベンチマークランナーのユニットテスト。

CPU デバイスで tracknet ベンチが {fps, avg_ms, p95_ms} を返すことを検証する。
unavailable デバイスが error を返すことを検証する。
"""
from __future__ import annotations

import os

import pytest

from backend.benchmark.devices import ComputeDevice
from backend.benchmark.runner import BenchmarkRunner, TARGET_TRACKNET, TARGET_POSE
from backend.benchmark.runner import TARGET_PIPELINE_FULL, TARGET_STATISTICS


# ─── フィクスチャ ──────────────────────────────────────────────────────────────

@pytest.fixture()
def cpu_device() -> ComputeDevice:
    """テスト用 CPU デバイス（available=True）"""
    return ComputeDevice(
        device_id="cpu_test",
        label="Test CPU",
        device_type="cpu",
        backend="pytorch-cpu",
        available=True,
        specs={"name": "Test CPU", "cores": 4, "logical_cores": 8},
    )


@pytest.fixture()
def unavailable_device() -> ComputeDevice:
    """テスト用 unavailable デバイス"""
    return ComputeDevice(
        device_id="cuda_test",
        label="Test dGPU (unavailable)",
        device_type="dgpu",
        backend="pytorch-cuda",
        available=False,
        specs={},
    )


@pytest.fixture(autouse=True)
def mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """テスト時は SS_CV_MOCK=1 を強制して推論を Mock に向ける。

    環境変数を設定した後、settings を再生成して factory が Mock を選ぶようにする。
    """
    monkeypatch.setenv("SS_CV_MOCK", "1")
    monkeypatch.setenv("SS_USE_GPU", "0")
    # settings を再生成して環境変数を反映させる
    from backend import config as cfg_mod
    cfg_mod.settings = cfg_mod.Settings()


# ─── TrackNet ベンチマークテスト ───────────────────────────────────────────────

class TestBenchTracknet:
    def test_returns_fps_avg_p95(self, cpu_device: ComputeDevice) -> None:
        """CPU デバイスで TrackNet ベンチが fps / avg_ms / p95_ms を返すこと"""
        runner = BenchmarkRunner()
        result = runner._bench_tracknet(cpu_device, n_frames=5)

        assert "error" not in result, f"エラーが返された: {result}"
        assert "fps" in result, "fps キーが存在しない"
        assert "avg_ms" in result, "avg_ms キーが存在しない"
        assert "p95_ms" in result, "p95_ms キーが存在しない"

    def test_fps_is_positive(self, cpu_device: ComputeDevice) -> None:
        """fps は正の数値であること"""
        runner = BenchmarkRunner()
        result = runner._bench_tracknet(cpu_device, n_frames=3)
        assert result.get("fps", 0) > 0, f"fps が 0 以下: {result}"

    def test_avg_ms_is_positive(self, cpu_device: ComputeDevice) -> None:
        """avg_ms は正の数値であること"""
        runner = BenchmarkRunner()
        result = runner._bench_tracknet(cpu_device, n_frames=3)
        assert result.get("avg_ms", 0) > 0, f"avg_ms が 0 以下: {result}"

    def test_p95_ge_avg(self, cpu_device: ComputeDevice) -> None:
        """p95_ms >= avg_ms であること（統計的性質）"""
        runner = BenchmarkRunner()
        result = runner._bench_tracknet(cpu_device, n_frames=10)
        assert result["p95_ms"] >= result["avg_ms"] - 0.01, (
            f"p95 が avg より小さい: {result}"
        )


# ─── unavailable デバイスのエラーテスト ──────────────────────────────────────

class TestUnavailableDevice:
    def test_unavailable_returns_error(self, unavailable_device: ComputeDevice) -> None:
        """unavailable デバイスは {"error": "device unavailable"} を返すこと"""
        runner = BenchmarkRunner()
        result = runner._run_target(unavailable_device, TARGET_TRACKNET, n_frames=3)
        assert result == {"error": "device unavailable"}, f"期待外の結果: {result}"

    def test_unavailable_pose_returns_error(self, unavailable_device: ComputeDevice) -> None:
        """Pose ターゲットでも unavailable なら error を返すこと"""
        runner = BenchmarkRunner()
        result = runner._run_target(unavailable_device, TARGET_POSE, n_frames=3)
        assert result == {"error": "device unavailable"}

    def test_unavailable_pipeline_returns_error(self, unavailable_device: ComputeDevice) -> None:
        """pipeline_full ターゲットでも unavailable なら error を返すこと"""
        runner = BenchmarkRunner()
        result = runner._run_target(unavailable_device, TARGET_PIPELINE_FULL, n_frames=3)
        assert result == {"error": "device unavailable"}


# ─── run_all 統合テスト ────────────────────────────────────────────────────────

class TestRunAll:
    def test_run_all_cpu_tracknet(self, cpu_device: ComputeDevice) -> None:
        """run_all が cpu×tracknet の結果辞書を返すこと"""
        runner = BenchmarkRunner()
        results = runner.run_all(
            job_id="test-job-001",
            device_ids=["cpu_test"],
            targets=[TARGET_TRACKNET],
            n_frames=3,
            devices=[cpu_device],
        )
        assert "cpu_test" in results
        assert TARGET_TRACKNET in results["cpu_test"]
        tn = results["cpu_test"][TARGET_TRACKNET]
        assert "fps" in tn, f"tracknet result に fps なし: {tn}"

    def test_run_all_progress_reaches_1(self, cpu_device: ComputeDevice) -> None:
        """run_all 完了後に progress が 1.0 になること"""
        runner = BenchmarkRunner()
        runner.run_all(
            job_id="test-job-002",
            device_ids=["cpu_test"],
            targets=[TARGET_TRACKNET],
            n_frames=3,
            devices=[cpu_device],
        )
        assert runner.get_progress("test-job-002") == 1.0

    def test_run_all_mixed_devices(
        self, cpu_device: ComputeDevice, unavailable_device: ComputeDevice
    ) -> None:
        """available / unavailable 混在時に両方の結果が返ること"""
        runner = BenchmarkRunner()
        results = runner.run_all(
            job_id="test-job-003",
            device_ids=["cpu_test", "cuda_test"],
            targets=[TARGET_TRACKNET],
            n_frames=3,
            devices=[cpu_device, unavailable_device],
        )
        # CPU は正常結果
        assert "fps" in results["cpu_test"][TARGET_TRACKNET]
        # dGPU は unavailable エラー
        assert results["cuda_test"][TARGET_TRACKNET] == {"error": "device unavailable"}


# ─── statistics ベンチマークテスト ────────────────────────────────────────────

class TestBenchStatistics:
    def test_cpu_returns_metrics(self, cpu_device: ComputeDevice) -> None:
        """CPU で statistics ベンチが metrics を返すこと"""
        runner = BenchmarkRunner()
        result = runner._bench_statistics(cpu_device, n_frames=5)
        assert "error" not in result, f"エラーが返された: {result}"
        assert "fps" in result

    def test_gpu_returns_unavailable(self, unavailable_device: ComputeDevice) -> None:
        """GPU タイプでは statistics が device unavailable を返すこと"""
        # available=True の GPU デバイスを用意
        gpu_device = ComputeDevice(
            device_id="cuda_available",
            label="Available GPU",
            device_type="dgpu",
            backend="pytorch-cuda",
            available=True,
            specs={},
        )
        runner = BenchmarkRunner()
        result = runner._bench_statistics(gpu_device, n_frames=3)
        assert result == {"error": "device unavailable"}
