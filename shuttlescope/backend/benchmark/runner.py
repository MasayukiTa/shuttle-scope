"""ベンチマーク計測ランナー。

BenchmarkRunner.run_all() が全 device × target を計測し、
jobs.py の進捗 (progress フィールド) を更新しながら結果を集積する。

target 名 (固定):
    tracknet / pose / pipeline_full / clip_extract / statistics

CV 推論は必ず backend.cv.factory 経由で呼ぶ。
"""
from __future__ import annotations

import gc
import logging
import os
import subprocess
import tempfile
import time
from contextlib import contextmanager
from typing import Any, Dict, Generator, List

import numpy as np

from backend.benchmark.devices import ComputeDevice
from backend.benchmark.synthetic import make_frames, make_video_file

logger = logging.getLogger(__name__)

# ターゲット名定数
TARGET_TRACKNET = "tracknet"
TARGET_POSE = "pose"
TARGET_PIPELINE_FULL = "pipeline_full"
TARGET_CLIP_EXTRACT = "clip_extract"
TARGET_STATISTICS = "statistics"

ALL_TARGETS = [
    TARGET_TRACKNET,
    TARGET_POSE,
    TARGET_PIPELINE_FULL,
    TARGET_CLIP_EXTRACT,
    TARGET_STATISTICS,
]


def _compute_metrics(latencies_sec: List[float]) -> Dict[str, float]:
    """レイテンシ列から fps / avg_ms / p95_ms を算出する。"""
    arr = np.array(latencies_sec, dtype=np.float64)
    avg_ms = float(np.mean(arr)) * 1000.0
    p95_ms = float(np.percentile(arr, 95)) * 1000.0
    fps = 1000.0 / avg_ms if avg_ms > 0 else 0.0
    return {
        "fps": round(fps, 2),
        "avg_ms": round(avg_ms, 2),
        "p95_ms": round(p95_ms, 2),
    }


@contextmanager
def _gpu_cleanup(use_gpu: bool) -> Generator[None, None, None]:
    """計測前後で GC + GPU キャッシュをクリアする。"""
    gc.collect()
    if use_gpu:
        try:
            import torch
            torch.cuda.empty_cache()
        except Exception:
            pass
    try:
        yield
    finally:
        gc.collect()
        if use_gpu:
            try:
                import torch
                torch.cuda.empty_cache()
            except Exception:
                pass


@contextmanager
def _env_override(device: ComputeDevice) -> Generator[None, None, None]:
    """SS_USE_GPU / SS_CUDA_DEVICE を device に合わせて一時的に上書きする。

    デバイスタイプが dgpu / igpu なら GPU 経路を有効化する。
    with ブロックを抜けると元の値に戻す。
    """
    use_gpu = device.device_type in ("dgpu", "igpu")
    old_use_gpu = os.environ.get("SS_USE_GPU")
    old_cuda_dev = os.environ.get("SS_CUDA_DEVICE")
    old_cv_mock = os.environ.get("SS_CV_MOCK")

    os.environ["SS_USE_GPU"] = "1" if use_gpu else "0"
    if use_gpu:
        # specs に device_index があれば使う、なければ 0
        dev_idx = str(device.specs.get("device_index", 0))
        os.environ["SS_CUDA_DEVICE"] = dev_idx
    # ベンチマーク時は Mock を使わない（実測値が必要）
    # ただし GPU 系がなければ factory が自動で CPU / Mock にフォールバックする
    if os.environ.get("SS_CV_MOCK") == "1":
        # モック環境でも計測はできるが上書きはしない（テスト互換維持）
        pass

    try:
        # pydantic_settings の singleton を更新するために settings を再生成する
        from backend import config as cfg_mod
        cfg_mod.settings = cfg_mod.Settings()
        yield
    finally:
        # 元の環境変数を復元する
        _restore_env("SS_USE_GPU", old_use_gpu)
        _restore_env("SS_CUDA_DEVICE", old_cuda_dev)
        _restore_env("SS_CV_MOCK", old_cv_mock)
        from backend import config as cfg_mod
        cfg_mod.settings = cfg_mod.Settings()


def _restore_env(key: str, old_value: str | None) -> None:
    """環境変数を元の値（または未設定）に戻す。"""
    if old_value is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = old_value


def _make_video_path(n_frames: int) -> tuple[str, bool]:
    """合成 mp4 を生成して (path, created) を返す。

    ffmpeg が使用不可なら ("", False) を返す。
    """
    try:
        path = make_video_file(n=n_frames)
        return path, True
    except RuntimeError as exc:
        logger.warning("[runner] 合成動画生成失敗: %s", exc)
        return "", False


class BenchmarkRunner:
    """全 device × target の計測を行うランナー。

    使用例:
        runner = BenchmarkRunner()
        results = runner.run_all(
            job_id="bench-001",
            device_ids=["cpu_0"],
            targets=["tracknet", "pose"],
            n_frames=30,
            devices=[cpu_device],
        )
    """

    def __init__(self) -> None:
        # {job_id: progress(0.0〜1.0)} をメモリ保持（外部 jobs.py と統合可能）
        self._progress: Dict[str, float] = {}
        self._results: Dict[str, Dict[str, Any]] = {}

    # ── 公開インタフェース ──────────────────────────────────────────────────

    def run_all(
        self,
        job_id: str,
        device_ids: List[str],
        targets: List[str],
        n_frames: int,
        devices: List[ComputeDevice],
        job: "Any | None" = None,
    ) -> Dict[str, Any]:
        """全 device × target を計測して結果を返す。

        Args:
            job_id:     進捗追跡用の識別子
            device_ids: 計測対象デバイス ID リスト（devices に含まれる ID）
            targets:    計測対象ターゲット名リスト
            n_frames:   1 ターゲットあたりの計測フレーム数
            devices:    ComputeDevice のリスト
            job:        BenchmarkJob オブジェクト（キャンセル確認用、省略可）

        Returns:
            {device_id: {target: result_dict}} の形式
        """
        dev_map: Dict[str, ComputeDevice] = {d.device_id: d for d in devices}
        target_devices = [dev_map[did] for did in device_ids if did in dev_map]

        total_steps = len(target_devices) * len(targets)
        completed = 0
        self._progress[job_id] = 0.0
        results: Dict[str, Any] = {}

        for device in target_devices:
            if job is not None and job.cancelled:
                logger.info("[runner] キャンセル検出: job=%s", job_id)
                break
            results[device.device_id] = {}
            for target in targets:
                if job is not None and job.cancelled:
                    results[device.device_id][target] = {"error": "キャンセルされました"}
                    break
                logger.info(
                    "[runner] 計測開始: job=%s device=%s target=%s n=%d",
                    job_id, device.device_id, target, n_frames,
                )
                result = self._run_target(device, target, n_frames, job=job)
                results[device.device_id][target] = result
                completed += 1
                self._progress[job_id] = completed / max(total_steps, 1)
                logger.info(
                    "[runner] 計測完了: device=%s target=%s result=%s",
                    device.device_id, target, result,
                )

        self._results[job_id] = results
        return results

    def get_progress(self, job_id: str) -> float:
        """job_id の進捗 (0.0〜1.0) を返す。"""
        return self._progress.get(job_id, 0.0)

    def get_results(self, job_id: str) -> Dict[str, Any] | None:
        """job_id の計測結果を返す。未完了なら None。"""
        return self._results.get(job_id)

    # ── 内部: ターゲット振り分け ───────────────────────────────────────────

    def _run_target(self, device: ComputeDevice, target: str, n_frames: int,
                    job: "Any | None" = None) -> Dict[str, Any]:
        """対象デバイスが unavailable なら即座にエラーを返す。それ以外は各計測を実行。"""
        if not device.available:
            return {"error": "device unavailable"}
        if job is not None and job.cancelled:
            return {"error": "キャンセルされました"}

        use_gpu = device.device_type in ("dgpu", "igpu")

        dispatch = {
            TARGET_TRACKNET: self._bench_tracknet,
            TARGET_POSE: self._bench_pose,
            TARGET_PIPELINE_FULL: self._bench_pipeline_full,
            TARGET_CLIP_EXTRACT: self._bench_clip_extract,
            TARGET_STATISTICS: self._bench_statistics,
        }

        bench_fn = dispatch.get(target)
        if bench_fn is None:
            return {"error": f"未知のターゲット: {target}"}

        try:
            with _gpu_cleanup(use_gpu):
                with _env_override(device):
                    return bench_fn(device, n_frames)
        except Exception as exc:
            logger.exception("[runner] 計測例外: device=%s target=%s", device.device_id, target)
            return {"error": str(exc)}

    # ── 各ターゲット実装 ──────────────────────────────────────────────────

    def _bench_tracknet(self, device: ComputeDevice, n_frames: int,
                        job: "Any | None" = None) -> Dict[str, Any]:
        """TrackNet 推論速度計測。n_frames 回の run() レイテンシを計測する。"""
        from backend.cv import factory
        from backend.benchmark.synthetic import make_video_file

        inferencer = factory.get_tracknet()
        video_path = make_video_file(n=10)
        latencies: List[float] = []
        try:
            for _ in range(n_frames):
                if job is not None and job.cancelled:
                    break
                t0 = time.perf_counter()
                inferencer.run(video_path)
                latencies.append(time.perf_counter() - t0)
        finally:
            try:
                os.remove(video_path)
            except OSError:
                pass

        return _compute_metrics(latencies) if latencies else {"error": "キャンセルされました"}

    def _bench_pose(self, device: ComputeDevice, n_frames: int,
                    job: "Any | None" = None) -> Dict[str, Any]:
        """Pose 推論速度計測。n_frames 回の run() レイテンシを計測する。"""
        from backend.cv import factory
        from backend.benchmark.synthetic import make_video_file

        inferencer = factory.get_pose()
        video_path = make_video_file(n=10)
        latencies: List[float] = []
        try:
            for _ in range(n_frames):
                if job is not None and job.cancelled:
                    break
                t0 = time.perf_counter()
                inferencer.run(video_path)
                latencies.append(time.perf_counter() - t0)
        finally:
            try:
                os.remove(video_path)
            except OSError:
                pass

        return _compute_metrics(latencies) if latencies else {"error": "キャンセルされました"}

    def _bench_pipeline_full(self, device: ComputeDevice, n_frames: int) -> Dict[str, Any]:
        """パイプライン全工程（TrackNet + Pose + Gravity）の計測。

        tracknet → pose → gravity の一気通貫時間を計測する。
        """
        from backend.cv import factory
        from backend.cv.gravity import compute_cog_batch

        from backend.benchmark.synthetic import make_video_file

        tracknet = factory.get_tracknet()
        pose = factory.get_pose()
        video_path = make_video_file(n=10)  # 固定 10 フレーム
        latencies: List[float] = []

        try:
            for _ in range(n_frames):
                t0 = time.perf_counter()
                shuttle_samples = tracknet.run(video_path)
                pose_samples = pose.run(video_path)
                landmarks_batch = [s.landmarks for s in pose_samples]
                compute_cog_batch(landmarks_batch)
                latencies.append(time.perf_counter() - t0)
        finally:
            try:
                os.remove(video_path)
            except OSError:
                pass

        return _compute_metrics(latencies)

    def _bench_clip_extract(self, device: ComputeDevice, n_frames: int) -> Dict[str, Any]:
        """ffmpeg による合成 mp4 → クリップ切り出し時間の計測（CPU のみ有効）。

        GPU デバイスでは計測対象外として {"error": "device unavailable"} を返す。
        """
        # clip_extract は CPU のみ有効
        if device.device_type not in ("cpu",):
            return {"error": "device unavailable"}

        # 合成 mp4 を生成（失敗したら計測不能）
        video_path, created = _make_video_path(n_frames)
        if not created:
            return {"error": "ffmpeg unavailable"}

        try:
            latencies: List[float] = []
            for i in range(min(n_frames, 5)):  # クリップ切り出しは重いので最大 5 回
                out_path = tempfile.mktemp(suffix=f"_clip_{i}.mp4")
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", "0",
                    "-i", video_path,
                    "-t", "1",
                    "-c", "copy",
                    out_path,
                ]
                t0 = time.perf_counter()
                result = subprocess.run(cmd, capture_output=True, timeout=30)
                latencies.append(time.perf_counter() - t0)
                # 一時ファイルを削除
                try:
                    os.remove(out_path)
                except OSError:
                    pass
                if result.returncode != 0:
                    return {"error": f"ffmpeg clip 失敗 (code={result.returncode})"}
        finally:
            # 合成元動画を削除
            try:
                os.remove(video_path)
            except OSError:
                pass

        return _compute_metrics(latencies)

    def _bench_statistics(self, device: ComputeDevice, n_frames: int) -> Dict[str, Any]:
        """numpy/scipy を使った統計計算（相関・EPV 模擬）の時間計測（CPU のみ）。

        GPU デバイスでは計測対象外として {"error": "device unavailable"} を返す。
        """
        # statistics は CPU のみ有効
        if device.device_type not in ("cpu",):
            return {"error": "device unavailable"}

        rng = np.random.default_rng(123)
        latencies: List[float] = []

        for _ in range(n_frames):
            # EPV 模擬: n=200 の多変量乱数に対して相関行列・期待値計算
            data = rng.standard_normal((200, 10))

            t0 = time.perf_counter()

            # 相関行列
            corr = np.corrcoef(data.T)

            # EPV 模擬: ソフトマックス重み付き平均
            weights = np.exp(data[:, 0])
            weights /= weights.sum()
            epv = float(np.dot(weights, data[:, 1]))

            # scipy が使えれば線形回帰も計測に含める
            try:
                from scipy import stats as scipy_stats
                slope, intercept, r_value, p_value, std_err = scipy_stats.linregress(
                    data[:, 0], data[:, 1]
                )
            except ImportError:
                pass

            latencies.append(time.perf_counter() - t0)

            # 変数を明示的に削除して GC を促す
            del corr, weights, epv

        return _compute_metrics(latencies)
