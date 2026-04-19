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
TARGET_YOLO = "yolo"
TARGET_PIPELINE_FULL = "pipeline_full"
TARGET_CLIP_EXTRACT = "clip_extract"
TARGET_STATISTICS = "statistics"

ALL_TARGETS = [
    TARGET_TRACKNET,
    TARGET_POSE,
    TARGET_YOLO,
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
    # ベンチマーク時は常に実モデルを使用する（Mock では計測値が無意味になる）
    os.environ["SS_CV_MOCK"] = "0"

    # デバイスの backend に応じて推論バックエンドを明示指定する。
    # dGPU(NVIDIA) → auto（ONNX CUDA を優先）
    # iGPU(AMD DirectML) → directml（ONNX CUDA をスキップして DML を使う）
    # iGPU(Intel OpenVINO) → openvino
    # CPU → onnx_cpu
    _BACKEND_MAP = {
        "pytorch-cuda": "",      # auto: ONNX CUDA を優先選択
        "directml":     "directml",
        "openvino":     "openvino",
        "pytorch-cpu":  "onnx_cpu",
        "onnx":         "",      # auto
    }
    preferred_backend = _BACKEND_MAP.get(device.backend, "")
    old_backend = os.environ.get("SS_BENCH_BACKEND")
    os.environ["SS_BENCH_BACKEND"] = preferred_backend

    try:
        # pydantic_settings の singleton を更新するために settings を再生成する
        from backend import config as cfg_mod
        cfg_mod.settings = cfg_mod.Settings()
        # デバイスが変わるたびにキャッシュを破棄して正しいバックエンドを再解決する
        from backend.cv import factory as _factory
        _factory.clear_cache()
        yield
    finally:
        # 元の環境変数を復元する
        _restore_env("SS_USE_GPU", old_use_gpu)
        _restore_env("SS_CUDA_DEVICE", old_cuda_dev)
        _restore_env("SS_CV_MOCK", old_cv_mock)
        _restore_env("SS_BENCH_BACKEND", old_backend)
        from backend import config as cfg_mod
        cfg_mod.settings = cfg_mod.Settings()
        from backend.cv import factory as _factory
        _factory.clear_cache()


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
                result = self._run_target(
                    device, target, n_frames, job=job,
                    completed_steps=completed, total_steps=total_steps,
                )
                results[device.device_id][target] = result
                completed += 1
                self._progress[job_id] = completed / max(total_steps, 1)
                if job is not None:
                    job.progress = self._progress[job_id]
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
                    job: "Any | None" = None,
                    completed_steps: int = 0, total_steps: int = 1) -> Dict[str, Any]:
        """対象デバイスが unavailable なら即座にエラーを返す。それ以外は各計測を実行。"""
        if not device.available:
            return {"error": "device unavailable"}
        if job is not None and job.cancelled:
            return {"error": "キャンセルされました"}

        # Ray ワーカーデバイスは別経路で処理する
        is_ray_device = (
            device.device_type == "ray_worker"
            or device.backend == "ray"
            or device.device_id.startswith("ray_")
        )
        if is_ray_device:
            ray_dispatch = {
                TARGET_TRACKNET: self._bench_ray_tracknet,
                TARGET_POSE: self._bench_ray_pose,
                TARGET_YOLO: self._bench_ray_yolo,
            }
            bench_fn = ray_dispatch.get(target)
            if bench_fn is None:
                return {"error": f"Ray ワーカーでは未対応のターゲット: {target}"}
            try:
                return bench_fn(device, n_frames)
            except Exception as exc:
                logger.exception("[runner] Ray 計測例外: device=%s target=%s", device.device_id, target)
                return {"error": str(exc)}

        use_gpu = device.device_type in ("dgpu", "igpu")

        def _progress_cb(frame_i: int) -> None:
            """フレーム単位のサブ進捗を job に反映する。"""
            if job is not None:
                job.progress = (completed_steps + frame_i / max(n_frames, 1)) / max(total_steps, 1)

        dispatch = {
            TARGET_TRACKNET: self._bench_tracknet,
            TARGET_POSE: self._bench_pose,
            TARGET_YOLO: self._bench_yolo,
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
                    return bench_fn(device, n_frames, job=job, progress_cb=_progress_cb)
        except Exception as exc:
            logger.exception("[runner] 計測例外: device=%s target=%s", device.device_id, target)
            return {"error": str(exc)}

    # ── 各ターゲット実装 ──────────────────────────────────────────────────

    def _bench_tracknet(self, device: ComputeDevice, n_frames: int,
                        job: "Any | None" = None,
                        progress_cb=None) -> Dict[str, Any]:
        """TrackNet 推論速度計測。

        1トリプレット（3フレーム→1推論）単位でレイテンシを直接計測する。
        _MEASURE_ITERS 回繰り返して統計を取り、fps = 1000 / avg_ms で報告する。

        反復数を最大 5 に制限することで、ONNX CPU など低速バックエンドでも
        数分以内に完了する。progress は n_frames まで到達するようスケールする。
        """
        from backend.cv import factory
        from backend.tracknet.inference import FRAME_STACK

        # 最大5回の計測（低速CPUでも数分以内に完了）
        _MEASURE_ITERS = min(n_frames, 5)

        inferencer = factory.get_tracknet()

        # バックエンド名をログ（どのエンジンで計測しているか確認用）
        impl = getattr(inferencer, '_impl', None)  # OpenVINOTrackNet._impl = TrackNetInference
        try:
            bname = inferencer.backend_name() if hasattr(inferencer, 'backend_name') else \
                    (impl.backend_name() if impl is not None else '?')
        except Exception:
            bname = '?'
        logger.info("[bench/tracknet] device=%s backend=%s n_iters=%d",
                    device.device_id, bname, _MEASURE_ITERS)

        # GPU バックエンドでは _max_batch を使って大きなバッチで計測する（VRAM 活用）
        # CPU バックエンドでは 1 トリプレット（batch=1）のレイテンシを計測する
        use_gpu = device.device_type in ("dgpu", "igpu")

        # dGPU/iGPU デバイスなのに CPU バックエンドしかロードできていない場合は
        # 計測しても意味がないため、ロード失敗の詳細をエラーとして返す
        if use_gpu and impl is not None:
            actual_backend = ''
            try:
                actual_backend = impl.backend_name().lower()
            except Exception:
                pass
            is_gpu_backend = any(k in actual_backend for k in ('cuda', 'directml', 'openvino'))
            if actual_backend and not is_gpu_backend:
                # GPU ロード失敗理由を取得（TrackNetInference._gpu_load_error に保存済み）
                reason = (
                    getattr(impl, '_gpu_load_error', None)
                    or f"バックエンド: {actual_backend}"
                )
                logger.warning(
                    "[bench/tracknet] dGPU/iGPU デバイスで CPU バックエンドしか使えません: %s",
                    reason,
                )
                return {"error": f"GPU推論不可 — {reason}"}

        if use_gpu and impl is not None and hasattr(impl, '_max_batch'):
            bench_batch = impl._max_batch  # VRAM から自動計算されたバッチサイズ
        else:
            bench_batch = 1  # CPU: 1トリプレットのレイテンシ計測

        # bench_batch トリプレット分のフレームを生成
        # make_frames(FRAME_STACK + bench_batch - 1) → bench_batch 個のトリプレット
        n_bench_frames = FRAME_STACK + bench_batch - 1
        frames = make_frames(n_bench_frames, 512, 288)

        logger.info(
            "[bench/tracknet] device=%s backend=%s bench_batch=%d n_frames_per_run=%d",
            device.device_id, bname, bench_batch, n_bench_frames,
        )

        video_path: str | None = None
        if hasattr(inferencer, 'run_frames'):
            # run_frames 対応実装（OpenVINOTrackNet / MockTrackNet 等）
            def run_one() -> None:
                inferencer.run_frames(list(frames))
        else:
            # CpuTrackNet 等: 最小サイズの動画ファイル経由
            video_path = make_video_file(n=n_bench_frames)
            def run_one(_vp: str = video_path) -> None:
                inferencer.run(_vp)

        latencies: List[float] = []
        try:
            # ウォームアップ 1 回（CUDA JIT / cuDNN アルゴ検索を計測から除外）
            try:
                run_one()
            except Exception:
                pass

            for i in range(_MEASURE_ITERS):
                if job is not None and job.cancelled:
                    break
                t0 = time.perf_counter()
                run_one()
                latencies.append(time.perf_counter() - t0)
                if progress_cb is not None:
                    progress_cb(round((i + 1) * n_frames / _MEASURE_ITERS))
        finally:
            if video_path is not None:
                try:
                    os.remove(video_path)
                except OSError:
                    pass

        if not latencies:
            return {"error": "キャンセルされました"}

        metrics = _compute_metrics(latencies)
        # fps = bench_batch トリプレット / avg_sec（GPU は大バッチのスループット計測）
        if bench_batch > 1:
            metrics["fps"] = round(bench_batch * 1000.0 / metrics["avg_ms"], 2) if metrics["avg_ms"] > 0 else 0.0
        return metrics

    def _bench_pose(self, device: ComputeDevice, n_frames: int,
                    job: "Any | None" = None,
                    progress_cb=None) -> Dict[str, Any]:
        """Pose 推論速度計測。

        MediaPipe はビデオ入力前提のため動画ファイル経由。
        1 ファイルあたり _BATCH_SIZE フレームを計測し、最大 10 回繰り返す。
        """
        from backend.cv import factory
        from backend.benchmark.synthetic import make_video_file

        _BATCH_SIZE = 10
        _MEASURE_ITERS = min(n_frames, 10)

        inferencer = factory.get_pose()
        video_path = make_video_file(n=_BATCH_SIZE)
        latencies: List[float] = []
        try:
            # ウォームアップ 1 回
            try:
                inferencer.run(video_path)
            except Exception:
                pass

            for i in range(_MEASURE_ITERS):
                if job is not None and job.cancelled:
                    break
                t0 = time.perf_counter()
                inferencer.run(video_path)
                latencies.append(time.perf_counter() - t0)
                if progress_cb is not None:
                    progress_cb(round((i + 1) * n_frames / _MEASURE_ITERS))
        finally:
            try:
                os.remove(video_path)
            except OSError:
                pass

        if not latencies:
            return {"error": "キャンセルされました"}

        metrics = _compute_metrics(latencies)
        # fps = _BATCH_SIZE フレーム / avg_ms
        metrics["fps"] = round(_BATCH_SIZE * 1000.0 / metrics["avg_ms"], 2) if metrics["avg_ms"] > 0 else 0.0
        return metrics

    def _bench_yolo(self, device: ComputeDevice, n_frames: int,
                    job: "Any | None" = None,
                    progress_cb=None) -> Dict[str, Any]:
        """YOLOv8n 物体検出速度計測。

        backend/models/yolov8n.onnx が存在する場合のみ計測する。
        入力: (1, 3, 384, 640) float32 合成フレーム。
        EP 選択: CUDA → DirectML → CPU の優先順（デバイスに応じて SS_BENCH_BACKEND で制御）。
        """
        import os as _os
        from pathlib import Path

        _YOLO_MODEL = Path(__file__).parent.parent / "models" / "yolov8n.onnx"
        if not _YOLO_MODEL.exists():
            return {"error": f"モデル未配置: {_YOLO_MODEL.name}"}

        _YOLO_W, _YOLO_H = 640, 384
        _MEASURE_ITERS = min(n_frames, 5)

        try:
            import onnxruntime as ort
        except ImportError:
            return {"error": "onnxruntime 未インストール"}

        # デバイスに応じた EP 選択（SS_BENCH_BACKEND を参照）
        bench_backend = _os.environ.get("SS_BENCH_BACKEND", "")
        if bench_backend == "directml":
            providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
        elif bench_backend in ("", "onnx_cuda") and "CUDAExecutionProvider" in ort.get_available_providers():
            device_id = int(_os.environ.get("SS_CUDA_DEVICE", "0"))
            providers = [("CUDAExecutionProvider", {"device_id": device_id}), "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]

        try:
            sess = ort.InferenceSession(str(_YOLO_MODEL), providers=providers)
        except Exception as exc:
            return {"error": f"セッション初期化失敗: {exc}"}

        input_name = sess.get_inputs()[0].name
        dummy = np.zeros((1, 3, _YOLO_H, _YOLO_W), dtype=np.float32)

        latencies: List[float] = []
        # ウォームアップ
        try:
            sess.run(None, {input_name: dummy})
        except Exception:
            pass

        for i in range(_MEASURE_ITERS):
            if job is not None and job.cancelled:
                break
            t0 = time.perf_counter()
            sess.run(None, {input_name: dummy})
            latencies.append(time.perf_counter() - t0)
            if progress_cb is not None:
                progress_cb(round((i + 1) * n_frames / _MEASURE_ITERS))

        if not latencies:
            return {"error": "キャンセルされました"}

        return _compute_metrics(latencies)

    def _bench_pipeline_full(self, device: ComputeDevice, n_frames: int,
                             job: "Any | None" = None,
                             progress_cb=None) -> Dict[str, Any]:
        """パイプライン全工程（TrackNet + Pose + Gravity）の計測。

        tracknet → pose → gravity の一気通貫時間を計測する。
        最大 3 回の計測に制限して低速環境でも数分以内に完了させる。
        """
        from backend.cv import factory
        from backend.cv.gravity import compute_cog_batch
        from backend.tracknet.inference import FRAME_STACK

        _MEASURE_ITERS = min(n_frames, 3)
        _POSE_FRAMES = 10

        tracknet = factory.get_tracknet()
        pose = factory.get_pose()
        video_path = make_video_file(n=_POSE_FRAMES)
        latencies: List[float] = []

        try:
            # ウォームアップ
            try:
                if hasattr(tracknet, 'run_frames'):
                    tracknet.run_frames(list(make_frames(FRAME_STACK, 512, 288)))
                else:
                    tracknet.run(video_path)
                pose.run(video_path)
            except Exception:
                pass

            for i in range(_MEASURE_ITERS):
                if job is not None and job.cancelled:
                    break
                t0 = time.perf_counter()
                if hasattr(tracknet, 'run_frames'):
                    tracknet.run_frames(list(make_frames(FRAME_STACK, 512, 288)))
                else:
                    tracknet.run(video_path)
                pose_samples = pose.run(video_path)
                landmarks_batch = [s.landmarks for s in pose_samples]
                compute_cog_batch(landmarks_batch)
                latencies.append(time.perf_counter() - t0)
                if progress_cb is not None:
                    progress_cb(round((i + 1) * n_frames / _MEASURE_ITERS))
        finally:
            try:
                os.remove(video_path)
            except OSError:
                pass

        if not latencies:
            return {"error": "キャンセルされました"}

        metrics = _compute_metrics(latencies)
        metrics["fps"] = round(_POSE_FRAMES * 1000.0 / metrics["avg_ms"], 2) if metrics["avg_ms"] > 0 else 0.0
        return metrics

    def _bench_clip_extract(self, device: ComputeDevice, n_frames: int,
                            job: "Any | None" = None,
                            progress_cb=None) -> Dict[str, Any]:
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
                if job is not None and job.cancelled:
                    break
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
                if progress_cb is not None:
                    progress_cb(round((i + 1) * n_frames / min(n_frames, 5)))
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

    def _bench_statistics(self, device: ComputeDevice, n_frames: int,
                          job: "Any | None" = None,
                          progress_cb=None) -> Dict[str, Any]:
        """numpy/scipy を使った統計計算（相関・EPV 模擬）の時間計測（CPU のみ）。

        GPU デバイスでは計測対象外として {"error": "device unavailable"} を返す。
        """
        # statistics は CPU のみ有効
        if device.device_type not in ("cpu",):
            return {"error": "device unavailable"}

        rng = np.random.default_rng(123)
        latencies: List[float] = []

        for i in range(n_frames):
            if job is not None and job.cancelled:
                break
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
            if progress_cb is not None:
                progress_cb(i + 1)

            # 変数を明示的に削除して GC を促す
            del corr, weights, epv

        if not latencies:
            return {"error": "キャンセルされました"}
        return _compute_metrics(latencies)

    # ── Ray ワーカーベンチマーク ──────────────────────────────────────────────

    def _get_ray_worker_model_base(self, device: ComputeDevice) -> str:
        """デバイス IP から cluster.config.yaml の model_base を取得する。"""
        try:
            from backend.cluster.topology import get_worker_model_base
            # device_id の形式: ray_cpu_169_254_140_146 / ray_igpu_169_254_140_146
            # specs.ip があればそちらを使う
            ip = device.specs.get("ip", "")
            if not ip:
                # device_id から IP 復元を試みる (ray_cpu_ / ray_igpu_ プレフィックスを除去)
                raw = device.device_id
                for prefix in ("ray_igpu_", "ray_cpu_", "ray_"):
                    if raw.startswith(prefix):
                        raw = raw[len(prefix):]
                        break
                # アンダースコアをドットに変換して IP を復元
                ip = raw.replace("_", ".")
            return get_worker_model_base(ip)
        except Exception:
            return "C:\\ss-models"

    def _bench_ray_tracknet(self, device: ComputeDevice, n_frames: int) -> Dict[str, Any]:
        """Ray ワーカーで TrackNet ベンチマークを実行する。"""
        from backend.cluster import bootstrap
        from backend.cluster import remote_tasks

        if not bootstrap.is_ray_connected():
            return {"error": "Ray未接続 — 先にRay起動ボタンを押してください"}

        model_base = self._get_ray_worker_model_base(device)
        # TrackNet モデルパス（ワーカー側のパス）
        import os
        model_path = os.path.join(model_base, "tracknet.onnx")
        use_gpu = device.device_id.startswith("ray_igpu")
        n_iters = min(n_frames, 5)

        logger.info(
            "[runner/ray] TrackNet ベンチマーク: device=%s model=%s use_gpu=%s n_iters=%d",
            device.device_id, model_path, use_gpu, n_iters,
        )

        results = remote_tasks.dispatch_benchmark(
            "_run_benchmark_tracknet",
            model_path=model_path,
            n_iters=n_iters,
            use_gpu=use_gpu,
        )
        # 最初のワーカー結果を返す（単一ワーカー構成を想定）
        if isinstance(results, dict) and "error" not in results:
            for v in results.values():
                return v
        return results if isinstance(results, dict) else {"error": str(results)}

    def _bench_ray_pose(self, device: ComputeDevice, n_frames: int) -> Dict[str, Any]:
        """Ray ワーカーで Pose ベンチマークを実行する。"""
        from backend.cluster import bootstrap
        from backend.cluster import remote_tasks

        if not bootstrap.is_ray_connected():
            return {"error": "Ray未接続 — 先にRay起動ボタンを押してください"}

        n_iters = min(n_frames, 10)

        logger.info(
            "[runner/ray] Pose ベンチマーク: device=%s n_iters=%d",
            device.device_id, n_iters,
        )

        results = remote_tasks.dispatch_benchmark(
            "_run_benchmark_pose",
            n_iters=n_iters,
        )
        if isinstance(results, dict) and "error" not in results:
            for v in results.values():
                return v
        return results if isinstance(results, dict) else {"error": str(results)}

    def _bench_ray_yolo(self, device: ComputeDevice, n_frames: int) -> Dict[str, Any]:
        """Ray ワーカーで YOLO ベンチマークを実行する。"""
        from backend.cluster import bootstrap
        from backend.cluster import remote_tasks

        if not bootstrap.is_ray_connected():
            return {"error": "Ray未接続 — 先にRay起動ボタンを押してください"}

        model_base = self._get_ray_worker_model_base(device)
        import os
        model_path = os.path.join(model_base, "yolov8n.onnx")
        use_gpu = device.device_id.startswith("ray_igpu")
        n_iters = min(n_frames, 5)

        logger.info(
            "[runner/ray] YOLO ベンチマーク: device=%s model=%s use_gpu=%s n_iters=%d",
            device.device_id, model_path, use_gpu, n_iters,
        )

        results = remote_tasks.dispatch_benchmark(
            "_run_benchmark_yolo",
            model_path=model_path,
            n_iters=n_iters,
            use_gpu=use_gpu,
        )
        if isinstance(results, dict) and "error" not in results:
            for v in results.values():
                return v
        return results if isinstance(results, dict) else {"error": str(results)}
