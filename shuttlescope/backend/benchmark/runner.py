"""ベンチマーク計測ランナー。

BenchmarkRunner.run_all() が全 device × target を計測し、
jobs.py の進捗 (progress フィールド) を更新しながら結果を集積する。

target 名 (固定):
    tracknet / pose / pipeline_full / clip_extract / statistics

CV 推論は必ず backend.cv.factory 経由で呼ぶ。
"""
from __future__ import annotations

import gc
import json
import logging
import os
import subprocess
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
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
    # 非常に高速な mock / synthetic ベンチでは正の計測値でも
    # 小数 2 桁丸めにより 0.00ms へ潰れることがある。
    # 表示上の 0ms は downstream のテストと可視化に不都合なので、
    # 正の値が存在する場合のみ最小表示値を持たせる。
    if avg_ms > 0:
        avg_ms = max(avg_ms, 0.01)
    if p95_ms > 0:
        p95_ms = max(p95_ms, 0.01)
    fps = 1000.0 / avg_ms if avg_ms > 0 else 0.0
    return {
        "fps": round(fps, 2),
        "avg_ms": round(avg_ms, 2),
        "p95_ms": round(p95_ms, 2),
    }


def _time_budget_sec() -> float:
    """SS_BENCH_TIME_BUDGET_SEC 環境変数から計測予算（秒）を取得。既定 5 秒。"""
    try:
        return max(0.5, float(os.environ.get("SS_BENCH_TIME_BUDGET_SEC", "5")))
    except (TypeError, ValueError):
        return 5.0


def _is_aggressive() -> bool:
    """SS_BENCH_AGGRESSIVE=1 で攻めモード（batch を大きめ固定にして VRAM/GPU util を可視化）。"""
    return os.environ.get("SS_BENCH_AGGRESSIVE", "0") not in ("", "0", "false", "False")


def _find_directml_python() -> str | None:
    """DirectML 専用 venv の Python インタプリタパスを返す。存在しない場合は None。

    優先順:
    1. 環境変数 SS_DIRECTML_PYTHON（テスト・CI 用オーバーライド）
    2. backend/.venv-directml/Scripts/python.exe (Windows)
    """
    override = os.environ.get("SS_DIRECTML_PYTHON", "")
    if override and os.path.isfile(override):
        return override
    candidate = Path(__file__).parent.parent / ".venv-directml" / "Scripts" / "python.exe"
    if candidate.exists():
        return str(candidate)
    return None


def _run_directml_worker(params: dict) -> dict:
    """DirectML ワーカースクリプトをサブプロセスで実行し、JSON 結果を返す。

    params を stdin の JSON として渡し、stdout の JSON を解析して返す。
    エラー時は {"error": "..."} を返す。
    """
    python = _find_directml_python()
    if python is None:
        return {
            "error": (
                "DirectML venv が未セットアップです。"
                "`python backend/benchmark/setup_directml_venv.py` を実行してください。"
            )
        }

    worker = Path(__file__).parent / "workers" / "directml_worker.py"
    if not worker.exists():
        return {"error": f"ワーカースクリプトが見つかりません: {worker}"}

    try:
        proc = subprocess.run(
            [python, str(worker)],
            input=json.dumps(params, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=180,
        )
        if proc.returncode != 0:
            stderr = (proc.stderr or "").strip()[-600:]
            return {"error": f"ワーカー終了コード {proc.returncode}: {stderr}"}
        out = (proc.stdout or "").strip()
        if not out:
            return {"error": "ワーカーが空の出力を返しました"}
        return json.loads(out)
    except subprocess.TimeoutExpired:
        return {"error": "DirectML ワーカータイムアウト（180s）"}
    except json.JSONDecodeError as exc:
        return {"error": f"ワーカー出力 JSON パース失敗: {exc}"}
    except Exception as exc:
        return {"error": f"ワーカー起動失敗: {exc}"}


def _measure_budget(
    run_fn,
    warmup: int = 3,
    min_iters: int = 5,
    max_iters: int = 500,
    budget_sec: float | None = None,
    cancelled_fn=None,
    progress_cb=None,
) -> List[float]:
    """時間予算ベース計測: warmup 後、最低 min_iters を満たしつつ budget_sec 経過まで反復。

    戻り値は秒単位レイテンシ列。GPU 初回のアルゴリズム選択・JIT を warmup で除外し、
    Task Manager の 1-2 秒サンプリングでも GPU/VRAM の上昇が確実に観測できる長さになる。
    """
    budget = _time_budget_sec() if budget_sec is None else budget_sec
    # ウォームアップ（計測に含めない）。失敗しても黙殺して本計測に進む。
    for _ in range(max(0, warmup)):
        try:
            run_fn()
        except Exception:
            break

    lats: List[float] = []
    t_start = time.perf_counter()
    while True:
        if cancelled_fn is not None and cancelled_fn():
            break
        if len(lats) >= max_iters:
            break
        elapsed = time.perf_counter() - t_start
        if len(lats) >= min_iters and elapsed >= budget:
            break
        t0 = time.perf_counter()
        try:
            run_fn()
        except Exception:
            raise
        lats.append(time.perf_counter() - t0)
        if progress_cb is not None:
            # 予算 or 最大 iter の進捗の大きい方をサブ進捗として報告
            frac_time = min(1.0, elapsed / budget) if budget > 0 else 1.0
            frac_iter = len(lats) / max(min_iters, 1)
            progress_cb(min(1.0, max(frac_time, min(frac_iter, 1.0))))
    return lats


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
    # 通常ベンチでは実モデルを使うが、テストなどで明示的に SS_CV_MOCK=1 が
    # 指定されている場合はそれを尊重する。これにより CI では ffmpeg / 実重み
    # 非依存のモック経路を安定して使える。
    os.environ["SS_CV_MOCK"] = "1" if old_cv_mock == "1" else "0"

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

        # SSH / Ray ワーカーデバイスは別経路で処理する
        is_remote_device = (
            device.device_type == "ray_worker"
            or device.backend in ("ray", "ssh")
            or device.device_id.startswith("ray_")
            or device.device_id.startswith("ssh_")
        )
        if is_remote_device:
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
        """TrackNet 推論速度計測（時間予算ベース）。

        GPU は warmup を十分に入れた上で SS_BENCH_TIME_BUDGET_SEC（既定 5 秒）だけ
        連続推論してスループットを採る。攻めモードでは batch を 16 に拡張して
        VRAM/GPU util を可視化する（レイテンシ崖が出てもスループット確認目的）。
        DirectML デバイスで DmlExecutionProvider が現在の env に存在しない場合は
        backend/.venv-directml を使ったサブプロセスで計測する。
        """
        # DirectML サブプロセス経路: onnxruntime-gpu と onnxruntime-directml は共存不可
        _bench_backend = os.environ.get("SS_BENCH_BACKEND", "")
        if _bench_backend == "directml":
            try:
                import onnxruntime as _ort
                if "DmlExecutionProvider" not in _ort.get_available_providers():
                    return self._bench_via_directml_subprocess(
                        device, n_frames, job, progress_cb, target_name="tracknet",
                    )
            except ImportError:
                return self._bench_via_directml_subprocess(
                    device, n_frames, job, progress_cb, target_name="tracknet",
                )

        from backend.cv import factory
        from backend.tracknet.inference import FRAME_STACK

        inferencer = factory.get_tracknet()

        # バックエンド名をログ（どのエンジンで計測しているか確認用）
        impl = getattr(inferencer, '_impl', None)  # OpenVINOTrackNet._impl = TrackNetInference
        try:
            bname = inferencer.backend_name() if hasattr(inferencer, 'backend_name') else \
                    (impl.backend_name() if impl is not None else '?')
        except Exception:
            bname = '?'
        logger.info("[bench/tracknet] device=%s backend=%s budget=%.1fs aggressive=%s",
                    device.device_id, bname, _time_budget_sec(), _is_aggressive())

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
            bench_batch = impl._max_batch
            if _is_aggressive():
                # 攻めモード: FP16 でも VRAM/GPU util を確実に押し上げる狙いで batch=16 に拡張
                bench_batch = max(bench_batch, 16)
                try:
                    impl._max_batch = bench_batch
                except Exception:
                    pass
        else:
            bench_batch = 1  # CPU: 1トリプレットのレイテンシ計測

        # bench_batch トリプレット分のフレームを生成
        n_bench_frames = FRAME_STACK + bench_batch - 1
        frames = make_frames(n_bench_frames, 512, 288)

        logger.info(
            "[bench/tracknet] device=%s backend=%s bench_batch=%d n_frames_per_run=%d",
            device.device_id, bname, bench_batch, n_bench_frames,
        )

        video_path: str | None = None
        if hasattr(inferencer, 'run_frames'):
            def run_one() -> None:
                inferencer.run_frames(list(frames))
        else:
            video_path = make_video_file(n=n_bench_frames)
            def run_one(_vp: str = video_path) -> None:
                inferencer.run(_vp)

        t_wall0 = time.perf_counter()
        latencies: List[float] = []
        try:
            latencies = _measure_budget(
                run_one,
                warmup=5 if use_gpu else 1,
                min_iters=5,
                max_iters=500,
                cancelled_fn=(lambda: job is not None and job.cancelled),
                progress_cb=(lambda f: progress_cb(round(f * n_frames)) if progress_cb else None),
            )
        finally:
            if video_path is not None:
                try:
                    os.remove(video_path)
                except OSError:
                    pass

        if not latencies:
            return {"error": "キャンセルされました"}

        metrics = _compute_metrics(latencies)
        if bench_batch > 1 and metrics["avg_ms"] > 0:
            metrics["fps"] = round(bench_batch * 1000.0 / metrics["avg_ms"], 2)
        metrics["batch"] = bench_batch
        metrics["iters"] = len(latencies)
        metrics["wall_sec"] = round(time.perf_counter() - t_wall0, 2)
        metrics["backend"] = bname
        if _is_aggressive():
            metrics["aggressive"] = True
        return metrics

    def _bench_pose(self, device: ComputeDevice, n_frames: int,
                    job: "Any | None" = None,
                    progress_cb=None) -> Dict[str, Any]:
        """Pose 推論速度計測。

        MediaPipe はビデオ入力前提のため動画ファイル経由。
        1 ファイルあたり _BATCH_SIZE フレームを計測し、最大 10 回繰り返す。
        DirectML デバイスで DmlExecutionProvider が現在の env に存在しない場合は
        backend/.venv-directml を使ったサブプロセスで計測する。
        """
        _bench_backend = os.environ.get("SS_BENCH_BACKEND", "")
        if _bench_backend == "directml":
            try:
                import onnxruntime as _ort
                if "DmlExecutionProvider" not in _ort.get_available_providers():
                    return self._bench_via_directml_subprocess(
                        device, n_frames, job, progress_cb, target_name="pose",
                    )
            except ImportError:
                return self._bench_via_directml_subprocess(
                    device, n_frames, job, progress_cb, target_name="pose",
                )

        from backend.cv import factory
        from backend.benchmark.synthetic import make_video_file

        # 攻めモードでは 1 回のビデオを長くして GPU/CPU 負荷を可視化する
        _BATCH_SIZE = 60 if _is_aggressive() else 10

        inferencer = factory.get_pose()
        video_path = make_video_file(n=_BATCH_SIZE)
        t_wall0 = time.perf_counter()
        try:
            latencies = _measure_budget(
                lambda: inferencer.run(video_path),
                warmup=2,
                min_iters=3,
                max_iters=200,
                cancelled_fn=(lambda: job is not None and job.cancelled),
                progress_cb=(lambda f: progress_cb(round(f * n_frames)) if progress_cb else None),
            )
        finally:
            try:
                os.remove(video_path)
            except OSError:
                pass

        if not latencies:
            return {"error": "キャンセルされました"}

        metrics = _compute_metrics(latencies)
        metrics["fps"] = round(_BATCH_SIZE * 1000.0 / metrics["avg_ms"], 2) if metrics["avg_ms"] > 0 else 0.0
        metrics["batch"] = _BATCH_SIZE
        metrics["iters"] = len(latencies)
        metrics["wall_sec"] = round(time.perf_counter() - t_wall0, 2)
        if _is_aggressive():
            metrics["aggressive"] = True
        return metrics

    def _bench_yolo(self, device: ComputeDevice, n_frames: int,
                    job: "Any | None" = None,
                    progress_cb=None) -> Dict[str, Any]:
        """YOLOv8n 物体検出速度計測（FP16 + 適応バッチ）。

        GPU 経路では backend/models/yolov8n_fp16.onnx（dynamic batch）を優先し、
        batch=[1, 4, 16, 32, 64] の中から実デバイスで最速のスループットを採用する。
        CPU 経路は FP32 を batch=1 で計測する。
        DirectML デバイスで DmlExecutionProvider が現在の env に存在しない場合は
        backend/.venv-directml を使ったサブプロセスで計測する。
        """
        import os as _os

        _MODELS_DIR = Path(__file__).parent.parent / "models"
        _YOLO_FP32 = _MODELS_DIR / "yolov8n.onnx"
        _YOLO_FP16 = _MODELS_DIR / "yolov8n_fp16.onnx"

        use_gpu = device.device_type in ("dgpu", "igpu")
        # GPU なら FP16（dynamic batch）を優先、無ければ FP32
        target = _YOLO_FP16 if (use_gpu and _YOLO_FP16.exists()) else _YOLO_FP32

        if not target.exists():
            # ultralytics で自動エクスポート（dynamic batch、必要なら half=True）
            try:
                from ultralytics import YOLO as _YOLO
                import shutil as _sh
                want_half = use_gpu
                logger.info(
                    "YOLO モデル未配置 — 自動エクスポート (half=%s, dynamic=True)", want_half
                )
                _m = _YOLO("yolov8n.pt")
                _exported = _m.export(
                    format="onnx", imgsz=(384, 640), opset=17,
                    simplify=True, dynamic=True, half=want_half,
                )
                _exported_path = Path(str(_exported))
                if not _exported_path.exists():
                    return {"error": "yolov8n.onnx エクスポート失敗: 出力ファイル無し"}
                _sh.move(str(_exported_path), str(target))
            except Exception as _e:
                logger.warning("YOLO 自動エクスポート失敗: %s", _e)
                return {"error": f"モデル未配置: {target.name}"}

        try:
            import onnxruntime as ort
        except ImportError:
            return {"error": "onnxruntime 未インストール"}

        bench_backend = _os.environ.get("SS_BENCH_BACKEND", "")
        avail = ort.get_available_providers()
        device_id = int(_os.environ.get("SS_CUDA_DEVICE", "0"))
        _trt_cache = str(Path(__file__).parent.parent / "models" / "trt_cache")
        _os.makedirs(_trt_cache, exist_ok=True)
        use_trt = False  # CUDA Graph 判定用: TRT 経路に入った場合のみ True に更新

        if bench_backend == "directml":
            if "DmlExecutionProvider" not in avail:
                # onnxruntime-directml が現在の env にない → サブプロセスで計測
                return self._bench_via_directml_subprocess(
                    device, n_frames, job, progress_cb, target_name="yolo",
                )
            providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
        elif bench_backend == "openvino":
            providers = (["OpenVINOExecutionProvider", "CPUExecutionProvider"]
                         if "OpenVINOExecutionProvider" in avail else ["CPUExecutionProvider"])
        elif bench_backend in ("", "onnx_cuda") and use_gpu and "CUDAExecutionProvider" in avail:
            cuda_opts = {
                "device_id": device_id,
                "cudnn_conv_algo_search": "HEURISTIC",
                "arena_extend_strategy": "kNextPowerOfTwo",
                "do_copy_in_default_stream": "1",
            }
            # TRT EP: nvinfer_10.dll が存在する場合のみ有効化（DLL 未インストールなら CUDA にフォールバック）
            _trt_dll_ok = False
            try:
                import ctypes as _ct
                _ct.WinDLL("nvinfer_10.dll")
                _trt_dll_ok = True
            except OSError:
                pass
            use_trt = (
                _trt_dll_ok
                and "TensorrtExecutionProvider" in avail
                and _os.environ.get("SS_DISABLE_TRT", "0") not in ("1", "true", "True")
            )
            if use_trt:
                in_h, in_w = 384, 640
                opt_b = 64 if _is_aggressive() else 32
                # ultralytics YOLO ONNX の input tensor 名は常に "images"
                _trt_in = "images"
                trt_opts = {
                    "device_id": device_id,
                    "trt_fp16_enable": True,
                    "trt_engine_cache_enable": True,
                    "trt_engine_cache_path": _trt_cache,
                    "trt_max_workspace_size": 2 * 1024 ** 3,
                    "trt_profile_min_shapes": f"{_trt_in}:1x3x{in_h}x{in_w}",
                    "trt_profile_opt_shapes": f"{_trt_in}:{opt_b}x3x{in_h}x{in_w}",
                    "trt_profile_max_shapes": f"{_trt_in}:128x3x{in_h}x{in_w}",
                }
                providers = [
                    ("TensorrtExecutionProvider", trt_opts),
                    ("CUDAExecutionProvider", cuda_opts),
                    "CPUExecutionProvider",
                ]
            else:
                providers = [("CUDAExecutionProvider", cuda_opts), "CPUExecutionProvider"]
        else:
            providers = ["CPUExecutionProvider"]
            use_trt = False

        # ── CPU 経路: OpenVINO ネイティブ API で推論（onnxruntime-gpu と競合しないため EP 経由は不可）
        _ov_compiled = None
        _ov_input_name: str = ""
        if not use_gpu:
            try:
                import openvino as _ov
                _ov_core = _ov.Core()
                _ov_model = _ov_core.read_model(str(target))
                _ov_compiled = _ov_core.compile_model(
                    _ov_model, "CPU",
                    {"PERFORMANCE_HINT": "LATENCY", "INFERENCE_NUM_THREADS": str(_os.cpu_count() or 4)},
                )
                _ov_input_name = next(iter(_ov_compiled.input(0).get_names()))
                logger.info("[bench/yolo] OpenVINO ネイティブ CPU 経路を使用 (model=%s)", target.name)
            except Exception as _ov_e:
                logger.warning("[bench/yolo] OpenVINO ネイティブ初期化失敗、ORT CPU にフォールバック: %s", _ov_e)
                _ov_compiled = None

        import os as _os2
        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        so.enable_mem_reuse = True
        so.intra_op_num_threads = int(_os2.cpu_count() or 4)
        # CUDA Graph: バッチが固定（スイープ後に固定）されるため Python dispatch
        # オーバーヘッドを除去できる。TRT EP は独自の実行グラフを持つため対象外。
        # enable_mem_pattern は CUDA Graph 使用時に False が必須。
        _use_cuda_graph = (
            use_gpu
            and not use_trt
            and bench_backend not in ("directml", "openvino")
            and "CUDAExecutionProvider" in avail
        )
        if _use_cuda_graph:
            so.enable_mem_pattern = False
            so.add_session_config_entry("session.use_cuda_graphs", "1")
            logger.info("[bench/yolo] CUDA Graph 有効")
        else:
            so.enable_mem_pattern = True

        # ── OpenVINO ネイティブ CPU 経路 ────────────────────────────────────
        if _ov_compiled is not None:
            x_ov = np.zeros((1, 3, 384, 640), dtype=np.float32)
            t_wall0 = time.perf_counter()
            try:
                lats = _measure_budget(
                    lambda: _ov_compiled({_ov_input_name: x_ov}),
                    warmup=3,
                    min_iters=5,
                    max_iters=500,
                    cancelled_fn=(lambda: job is not None and job.cancelled),
                    progress_cb=(lambda f: progress_cb(round(f * n_frames)) if progress_cb else None),
                )
            except Exception as exc:
                return {"error": f"OpenVINO 推論失敗: {exc}"}
            if not lats:
                return {"error": "キャンセルされました"}
            metrics = _compute_metrics(lats)
            if metrics["avg_ms"] > 0:
                metrics["fps"] = round(1000.0 / metrics["avg_ms"], 2)
            metrics["batch"] = 1
            metrics["iters"] = len(lats)
            metrics["wall_sec"] = round(time.perf_counter() - t_wall0, 2)
            metrics["model"] = target.name
            metrics["providers"] = ["OpenVINO/CPU"]
            return metrics

        # ── ORT 経路（GPU / OpenVINO 非対応環境）────────────────────────────
        try:
            sess = ort.InferenceSession(str(target), sess_options=so, providers=providers)
        except Exception as exc:
            return {"error": f"セッション初期化失敗: {exc}"}

        input_meta = sess.get_inputs()[0]
        input_name = input_meta.name
        # 入力 dtype を ONNX メタから自動判定（FP16 モデルは float16）
        in_dtype = np.float16 if "float16" in input_meta.type else np.float32

        # 動的バッチ対応か判定（shape に 'batch' 等の文字列があれば可変）
        dyn_batch = not isinstance(input_meta.shape[0], int)
        if _is_aggressive() and dyn_batch and use_gpu:
            candidates = [64]
        elif dyn_batch and use_gpu:
            candidates = [1, 4, 16, 32]
        else:
            candidates = [1]

        # ── 短いスイープで最適バッチを決定（各 3 iter・ウォームアップ込）
        best = None  # (per_sample_sec, batch)
        if len(candidates) > 1:
            for b in candidates:
                if job is not None and job.cancelled:
                    break
                x = np.zeros((b, 3, 384, 640), dtype=in_dtype)
                try:
                    sess.run(None, {input_name: x})
                    sess.run(None, {input_name: x})
                    lats: List[float] = []
                    for _ in range(3):
                        t0 = time.perf_counter()
                        sess.run(None, {input_name: x})
                        lats.append(time.perf_counter() - t0)
                    avg = float(np.mean(lats))
                    per_sample = avg / b
                    logger.info(
                        "[bench/yolo] sweep batch=%d avg=%.2fms per_sample=%.2fms fps=%.1f",
                        b, avg * 1000, per_sample * 1000, b / avg,
                    )
                    if best is None or per_sample < best[0]:
                        best = (per_sample, b)
                except Exception as exc:
                    logger.warning("[bench/yolo] batch=%d 失敗: %s", b, exc)
                    break
            chosen = best[1] if best else candidates[0]
        else:
            chosen = candidates[0]

        # ── 時間予算ベースで本計測
        x = np.zeros((chosen, 3, 384, 640), dtype=in_dtype)
        t_wall0 = time.perf_counter()
        try:
            lats = _measure_budget(
                lambda: sess.run(None, {input_name: x}),
                warmup=5 if use_gpu else 2,
                min_iters=5,
                max_iters=2000,
                cancelled_fn=(lambda: job is not None and job.cancelled),
                progress_cb=(lambda f: progress_cb(round(f * n_frames)) if progress_cb else None),
            )
        except Exception as exc:
            return {"error": f"推論失敗: {exc}"}

        if not lats:
            return {"error": "キャンセルされました"}

        metrics = _compute_metrics(lats)
        if metrics["avg_ms"] > 0:
            metrics["fps"] = round(chosen * 1000.0 / metrics["avg_ms"], 2)
        metrics["batch"] = chosen
        metrics["iters"] = len(lats)
        metrics["wall_sec"] = round(time.perf_counter() - t_wall0, 2)
        metrics["model"] = target.name
        metrics["providers"] = sess.get_providers()
        if _is_aggressive():
            metrics["aggressive"] = True
        return metrics

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

        _POSE_FRAMES = 30 if _is_aggressive() else 10

        tracknet = factory.get_tracknet()
        pose = factory.get_pose()
        video_path = make_video_file(n=_POSE_FRAMES)
        t_wall0 = time.perf_counter()

        def _run_once() -> None:
            if hasattr(tracknet, 'run_frames'):
                tracknet.run_frames(list(make_frames(FRAME_STACK, 512, 288)))
            else:
                tracknet.run(video_path)
            pose_samples = pose.run(video_path)
            landmarks_batch = [s.landmarks for s in pose_samples]
            compute_cog_batch(landmarks_batch)

        try:
            latencies = _measure_budget(
                _run_once,
                warmup=2,
                min_iters=3,
                max_iters=100,
                cancelled_fn=(lambda: job is not None and job.cancelled),
                progress_cb=(lambda f: progress_cb(round(f * n_frames)) if progress_cb else None),
            )
        finally:
            try:
                os.remove(video_path)
            except OSError:
                pass

        if not latencies:
            return {"error": "キャンセルされました"}

        metrics = _compute_metrics(latencies)
        metrics["fps"] = round(_POSE_FRAMES * 1000.0 / metrics["avg_ms"], 2) if metrics["avg_ms"] > 0 else 0.0
        metrics["batch"] = _POSE_FRAMES
        metrics["iters"] = len(latencies)
        metrics["wall_sec"] = round(time.perf_counter() - t_wall0, 2)
        if _is_aggressive():
            metrics["aggressive"] = True
        return metrics

    def _bench_clip_extract(self, device: ComputeDevice, n_frames: int,
                            job: "Any | None" = None,
                            progress_cb=None) -> Dict[str, Any]:
        """ffmpeg による合成 mp4 → クリップ切り出し時間の計測。

        ffmpeg -c copy は CPU/ファイル I/O 処理のため GPU の種類によらず同じ結果になるが、
        ベンチマークとしてすべての device × target を計測する。
        """

        # 合成 mp4 を生成（失敗したら計測不能）
        video_path, created = _make_video_path(n_frames)
        if not created:
            return {"error": "ffmpeg unavailable"}

        t_wall0 = time.perf_counter()
        budget = _time_budget_sec()
        max_iters = 50
        latencies: List[float] = []
        err: str | None = None
        try:
            i = 0
            while True:
                if job is not None and job.cancelled:
                    break
                if len(latencies) >= max_iters:
                    break
                if len(latencies) >= 3 and (time.perf_counter() - t_wall0) >= budget:
                    break
                with tempfile.NamedTemporaryFile(suffix=f"_clip_{i}.mp4", delete=False) as _tmp:
                    out_path = _tmp.name
                cmd = [
                    "ffmpeg", "-y", "-ss", "0", "-i", video_path,
                    "-t", "1", "-c", "copy", out_path,
                ]
                t0 = time.perf_counter()
                result = subprocess.run(cmd, capture_output=True, timeout=30)
                latencies.append(time.perf_counter() - t0)
                try:
                    os.remove(out_path)
                except OSError:
                    pass
                if progress_cb is not None:
                    frac = min(1.0, (time.perf_counter() - t_wall0) / max(budget, 0.001))
                    progress_cb(round(frac * n_frames))
                if result.returncode != 0:
                    err = f"ffmpeg clip 失敗 (code={result.returncode})"
                    break
                i += 1
        finally:
            try:
                os.remove(video_path)
            except OSError:
                pass

        if err:
            return {"error": err}
        if not latencies:
            return {"error": "キャンセルされました"}
        metrics = _compute_metrics(latencies)
        metrics["iters"] = len(latencies)
        metrics["wall_sec"] = round(time.perf_counter() - t_wall0, 2)
        return metrics

    def _bench_statistics(self, device: ComputeDevice, n_frames: int,
                          job: "Any | None" = None,
                          progress_cb=None) -> Dict[str, Any]:
        """numpy/scipy を使った統計計算（相関・EPV 模擬）の時間計測。

        実際には CPU 処理のため、CPU 以外のデバイスに紐づけて計測しても
        意味のある差は出ない。UI / テストの契約上も CPU 限定ターゲットとして扱う。
        """
        if device.device_type != "cpu":
            return {"error": "device unavailable"}

        rng = np.random.default_rng(123)
        try:
            from scipy import stats as scipy_stats
        except ImportError:
            scipy_stats = None

        def _run_one() -> None:
            data = rng.standard_normal((200, 10))
            np.corrcoef(data.T)
            w = np.exp(data[:, 0]); w /= w.sum()
            float(np.dot(w, data[:, 1]))
            if scipy_stats is not None:
                scipy_stats.linregress(data[:, 0], data[:, 1])

        t_wall0 = time.perf_counter()
        latencies = _measure_budget(
            _run_one,
            warmup=5,
            min_iters=max(50, n_frames),
            max_iters=200000,
            cancelled_fn=(lambda: job is not None and job.cancelled),
            progress_cb=(lambda f: progress_cb(round(f * n_frames)) if progress_cb else None),
        )
        if not latencies:
            return {"error": "キャンセルされました"}
        metrics = _compute_metrics(latencies)
        metrics["iters"] = len(latencies)
        metrics["wall_sec"] = round(time.perf_counter() - t_wall0, 2)
        return metrics

    # ── DirectML サブプロセスベンチマーク ─────────────────────────────────────

    def _bench_via_directml_subprocess(
        self, device: ComputeDevice, n_frames: int,
        job: "Any | None", progress_cb,
        target_name: str,
    ) -> Dict[str, Any]:
        """DirectML 専用 venv をサブプロセスで呼び出してベンチマーク計測する。

        onnxruntime-directml は onnxruntime-gpu と同一 venv に共存できないため
        backend/.venv-directml 内の Python で directml_worker.py を実行する。
        raw tensor 推論（ビデオデコード除外）でスループットを計測する。
        """
        _MODELS_DIR = Path(__file__).parent.parent / "models"
        _WEIGHTS_DIR = Path(__file__).parent.parent / "tracknet" / "weights"

        if target_name == "tracknet":
            _fp16 = _WEIGHTS_DIR / "tracknet_fp16.onnx"
            _fp32_cands = [_WEIGHTS_DIR / "tracknet.onnx", _WEIGHTS_DIR / "tracknet_v2.onnx"]
            model = _fp16 if _fp16.exists() else next((p for p in _fp32_cands if p.exists()), None)
            if model is None:
                return {"error": "TrackNet ONNX モデルが見つかりません"}
            # tracknet_fp16.onnx は keep_io_types=True → IO は float32
            params: dict = {
                "model_path": str(model),
                "input_shape": [8, 3, 288, 512],
                "in_dtype": "float32",
                "batch_sweep": [1, 2, 4, 8, 16, 32],
                "warmup": 3,
                "min_iters": 5,
                "budget_sec": _time_budget_sec(),
                "max_iters": 300,
            }

        elif target_name == "yolo":
            _yolo_fp16 = _MODELS_DIR / "yolov8n_fp16.onnx"
            _yolo_fp32 = _MODELS_DIR / "yolov8n.onnx"
            model = _yolo_fp16 if _yolo_fp16.exists() else (_yolo_fp32 if _yolo_fp32.exists() else None)
            if model is None:
                return {"error": "YOLO ONNX モデルが見つかりません"}
            in_dtype = "float16" if model.suffix == ".onnx" and "fp16" in model.name else "float32"
            params = {
                "model_path": str(model),
                "input_shape": [16, 3, 384, 640],
                "in_dtype": in_dtype,
                "batch_sweep": [1, 4, 16, 32] if not _is_aggressive() else [64],
                "warmup": 3,
                "min_iters": 5,
                "budget_sec": _time_budget_sec(),
                "max_iters": 500,
            }

        elif target_name == "pose":
            _pose_fp16 = _MODELS_DIR / "yolov8n_pose_fp16.onnx"
            _pose_fp32 = _MODELS_DIR / "yolov8n_pose.onnx"
            model = _pose_fp16 if _pose_fp16.exists() else (_pose_fp32 if _pose_fp32.exists() else None)
            if model is None:
                return {"error": "Pose ONNX モデルが見つかりません"}
            # yolov8n_pose_fp16.onnx: ultralytics half=True → IO は float32
            params = {
                "model_path": str(model),
                "input_shape": [16, 3, 384, 640],
                "in_dtype": "float32",
                "batch_sweep": [1, 4, 8, 16] if not _is_aggressive() else [32],
                "warmup": 3,
                "min_iters": 5,
                "budget_sec": _time_budget_sec(),
                "max_iters": 300,
            }

        else:
            return {"error": f"不明なターゲット: {target_name}"}

        logger.info(
            "[bench/directml] target=%s model=%s batch_sweep=%s budget=%.1fs",
            target_name, params["model_path"], params.get("batch_sweep"), params["budget_sec"],
        )

        if job is not None and job.cancelled:
            return {"error": "キャンセルされました"}

        result = _run_directml_worker(params)
        if "error" in result:
            logger.warning("[bench/directml] ワーカーエラー: %s", result["error"])
            return result

        lats: list[float] = result.get("latencies", [])
        if not lats:
            return {"error": "計測結果なし"}

        chosen_batch: int = result.get("chosen_batch", params["input_shape"][0])
        metrics = _compute_metrics(lats)
        if chosen_batch > 1 and metrics["avg_ms"] > 0:
            metrics["fps"] = round(chosen_batch * 1000.0 / metrics["avg_ms"], 2)
        metrics["batch"] = chosen_batch
        metrics["iters"] = len(lats)
        metrics["backend"] = "directml"
        metrics["providers"] = result.get("providers", [])
        metrics["note"] = "raw tensor inference"
        if _is_aggressive():
            metrics["aggressive"] = True
        return metrics

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
        """SSH / Ray ワーカーで TrackNet ベンチマークを実行する。"""
        from backend.cluster import bootstrap
        from backend.cluster import remote_tasks

        model_base = self._get_ray_worker_model_base(device)
        import os
        model_path = os.path.join(model_base, "tracknet.onnx")
        use_gpu = device.device_id.startswith(("ray_igpu", "ssh_igpu"))
        n_iters = min(n_frames, 5)

        logger.info(
            "[runner/worker] TrackNet bench: device=%s model=%s use_gpu=%s n_iters=%d",
            device.device_id, model_path, use_gpu, n_iters,
        )

        # SSH ワーカーは直接 SSH 経由で実行
        ip = (device.specs or {}).get("ip", "")
        if device.backend == "ssh" and ip:
            creds = remote_tasks._get_worker_ssh_creds(ip)
            if creds:
                return remote_tasks.dispatch_benchmark_ssh(
                    "_run_benchmark_tracknet",
                    creds["host"], creds["username"], creds["password"],
                    model_path=model_path, n_iters=n_iters, use_gpu=use_gpu,
                )

        if not bootstrap.is_ray_connected():
            return {"error": "Ray未接続 — 先にRay起動ボタンを押してください"}

        results = remote_tasks.dispatch_benchmark(
            "_run_benchmark_tracknet",
            model_path=model_path,
            n_iters=n_iters,
            use_gpu=use_gpu,
        )
        if isinstance(results, dict) and "error" not in results:
            for v in results.values():
                return v
        return results if isinstance(results, dict) else {"error": str(results)}

    def _bench_ray_pose(self, device: ComputeDevice, n_frames: int) -> Dict[str, Any]:
        """SSH / Ray ワーカーで Pose ベンチマークを実行する。"""
        from backend.cluster import bootstrap
        from backend.cluster import remote_tasks

        n_iters = min(n_frames, 10)

        logger.info(
            "[runner/worker] Pose bench: device=%s n_iters=%d",
            device.device_id, n_iters,
        )

        ip = (device.specs or {}).get("ip", "")
        if device.backend == "ssh" and ip:
            creds = remote_tasks._get_worker_ssh_creds(ip)
            if creds:
                return remote_tasks.dispatch_benchmark_ssh(
                    "_run_benchmark_pose",
                    creds["host"], creds["username"], creds["password"],
                    n_iters=n_iters,
                )

        if not bootstrap.is_ray_connected():
            return {"error": "Ray未接続 — 先にRay起動ボタンを押してください"}

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
