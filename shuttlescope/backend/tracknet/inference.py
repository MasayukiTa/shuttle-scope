"""TrackNet inference wrapper.

Runtime priority (auto モード):
1. ONNX CUDA  — CUDAExecutionProvider（torch cu128 DLL 経由、RTX 5060 Ti sm_120 確認済み）
2. DirectML   — DmlExecutionProvider（onnxruntime-directml 環境のみ）
3. OpenVINO   — Intel GPU / CPU
4. ONNX CPU   — CPUExecutionProvider
5. TensorFlow — CPU / Intel バックエンド

前提: main.py 起動時に torch をインポートして cublasLt64_12.dll 等を PATH に追加済み。
"""

from __future__ import annotations

import contextlib
import logging
import os
import time
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phase-0: ステージタイマー & NVTX 計装
# ---------------------------------------------------------------------------

def _nvtx_push(name: str) -> None:
    """NVTX レンジ開始。nvtx / torch.cuda.nvtx どちらかを使う。利用不可なら無視。"""
    try:
        import torch.cuda.nvtx as nvtx  # type: ignore
        nvtx.range_push(name)
    except Exception:
        pass


def _nvtx_pop() -> None:
    try:
        import torch.cuda.nvtx as nvtx  # type: ignore
        nvtx.range_pop()
    except Exception:
        pass


@contextlib.contextmanager
def _nvtx_range(name: str):
    _nvtx_push(name)
    try:
        yield
    finally:
        _nvtx_pop()


class _StageTimings:
    """_predict_frames_batch() の各ステージ累積時間（秒）を保持する。

    SS_TRACKNET_PROFILE=1 のときのみ計測する。
    reset() で次回計測に備えてクリアする。
    """

    __slots__ = ("preprocess", "stack", "infer", "postproc", "n_chunks")

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.preprocess = 0.0
        self.stack = 0.0
        self.infer = 0.0
        self.postproc = 0.0
        self.n_chunks = 0

    def to_ms_dict(self) -> dict:
        denom = max(self.n_chunks, 1)
        return {
            "preprocess_ms": round(self.preprocess / denom * 1000, 2),
            "stack_ms": round(self.stack / denom * 1000, 2),
            "infer_ms": round(self.infer / denom * 1000, 2),
            "postproc_ms": round(self.postproc / denom * 1000, 2),
            "n_chunks": self.n_chunks,
        }


_PROFILE_ENABLED: bool = os.environ.get("SS_TRACKNET_PROFILE", "0") not in ("", "0", "false")


def _profile_enabled() -> bool:
    """実行時に SS_TRACKNET_PROFILE を再確認する（sweep スクリプトが起動後に設定可能）。"""
    if _PROFILE_ENABLED:
        return True
    return os.environ.get("SS_TRACKNET_PROFILE", "0") not in ("", "0", "false")


# ---------------------------------------------------------------------------
# Phase-4: Confidence-Based Adaptive Skip
# ---------------------------------------------------------------------------

# SS_TRACKNET_SKIP_THRESHOLD: これ以上の confidence が出た次フレームをスキップ
#   1.1 (>1.0) = 無効（デフォルト）、0.92 が推奨開始値
_SKIP_THRESHOLD_DEFAULT: float = 1.1

# SS_TRACKNET_MAX_SKIP: 連続スキップの最大数
_MAX_SKIP_DEFAULT: int = 2


def _skip_config() -> tuple[float, int]:
    """実行時に skip 設定を取得する。"""
    try:
        th = float(os.environ.get("SS_TRACKNET_SKIP_THRESHOLD", str(_SKIP_THRESHOLD_DEFAULT)))
    except (ValueError, TypeError):
        th = _SKIP_THRESHOLD_DEFAULT
    try:
        ms = int(os.environ.get("SS_TRACKNET_MAX_SKIP", str(_MAX_SKIP_DEFAULT)))
    except (ValueError, TypeError):
        ms = _MAX_SKIP_DEFAULT
    return th, ms


def _extrapolate_position(
    prev: dict, pprev: Optional[dict], frame_idx: int
) -> dict:
    """速度ベクトルで次フレームのシャトル位置を外挿する。

    前2フレームの (x_norm, y_norm) から速度を算出し次フレーム位置を予測する。
    pprev が None または座標が欠損している場合は prev をそのままコピーして返す。
    confidence は毎フレーム 0.85 倍に減衰する（外挿の不確かさを反映）。
    """
    from backend.tracknet.zone_mapper import coords_to_zone

    conf_decay = round((prev.get("confidence") or 0.0) * 0.85, 3)

    px = prev.get("x_norm")
    py = prev.get("y_norm")
    if px is None or py is None or pprev is None:
        return {
            "frame_idx": frame_idx,
            "zone": prev.get("zone"),
            "confidence": conf_decay,
            "x_norm": px,
            "y_norm": py,
            "skipped": True,
        }

    qx = pprev.get("x_norm")
    qy = pprev.get("y_norm")
    if qx is None or qy is None:
        return {
            "frame_idx": frame_idx,
            "zone": prev.get("zone"),
            "confidence": conf_decay,
            "x_norm": round(px, 4),
            "y_norm": round(py, 4),
            "skipped": True,
        }

    nx = max(0.0, min(1.0, px + (px - qx)))
    ny = max(0.0, min(1.0, py + (py - qy)))
    return {
        "frame_idx": frame_idx,
        "zone": coords_to_zone(nx, ny),
        "confidence": conf_decay,
        "x_norm": round(nx, 4),
        "y_norm": round(ny, 4),
        "skipped": True,
    }


def _register_cuda_dll_dirs() -> None:
    """PyTorch 同梱の CUDA/cuDNN DLL と TensorRT ランタイム DLL を
    ONNX Runtime GPU から参照可能にする。

    Python 3.8+ は PATH に通っていても依存 DLL を自動解決しないため、
    os.add_dll_directory() で明示登録が必要。OpenVINO 検出を壊さないため
    PATH は変更しない。
    """
    if not hasattr(os, "add_dll_directory"):
        return
    # PyTorch 同梱 CUDA/cuDNN
    try:
        import torch  # type: ignore
        lib_dir = os.path.join(os.path.dirname(torch.__file__), "lib")
        if os.path.isdir(lib_dir):
            try:
                os.add_dll_directory(lib_dir)
            except (FileNotFoundError, OSError):
                pass
    except Exception:
        pass
    # TensorRT bin （SS_TRT_DIR 環境変数 or 既定パス）
    # onnxruntime_providers_tensorrt.dll が nvonnxparser_10.dll 等を
    # 遷移的にロードする際 os.add_dll_directory では解決されないため、
    # PATH の先頭にも TRT bin を追加する（CUDA/cuDNN と衝突しないよう TRT のみ）。
    trt_candidates = [
        os.environ.get("SS_TRT_DIR", "").strip(),
        r"C:\TensorRT\TensorRT-10.16.1.11\bin",
        r"C:\TensorRT\TensorRT-10.16.1.11\lib",
    ]
    _existing_path = os.environ.get("PATH", "")
    for d in trt_candidates:
        if d and os.path.isdir(d):
            try:
                os.add_dll_directory(d)
            except (FileNotFoundError, OSError):
                pass
            if d not in _existing_path:
                os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


# ONNX Runtime をロードする前に DLL 検索パスを整備する
_register_cuda_dll_dirs()


def _trt_available() -> bool:
    """TensorRT ランタイム DLL (nvinfer_10.dll) が使用可能かチェック（1 回だけ実行）。"""
    try:
        import ctypes
        ctypes.WinDLL("nvinfer_10.dll")
        return True
    except OSError:
        return False
    except Exception:
        return False


_TRT_AVAILABLE: bool = _trt_available()


def _get_gpu_vram_limit_bytes() -> int:
    """cluster.config.yaml の resources.gpu_vram_limit_gb をバイト単位で返す。
    0 = ORT 自動管理（上限なし）。"""
    try:
        from backend.cluster.topology import load_config
        gb = load_config().get("resources", {}).get("gpu_vram_limit_gb", 0) or 0
        return int(float(gb) * 1024 ** 3) if gb > 0 else 0
    except Exception:
        return 0


def _get_free_vram_bytes(device_index: int) -> int:
    """指定デバイスの空き VRAM 量をバイト単位で返す。取得失敗時は 0。"""
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        pynvml.nvmlShutdown()
        return int(info.free)
    except Exception:
        return 0


def _vram_based_max_batch(device_index: int, per_sample_mb: int = 800) -> int:
    """空き VRAM から安全な最大バッチサイズを推定する。

    per_sample_mb: 1 トリプレットあたりの VRAM 消費量（MB）。
    TrackNet デコーダ最大層: (N, 1024, 288, 512) float32 = 576MB/sample。
    cuDNN ワークスペース・モデルバッファ込みで 800MB/sample が安全上限。
    残り VRAM の 65% を使用（OOM 発生時は _predict_frames_batch 内で半減再試行）。
    下限 1、上限 20。
    """
    free_mb = _get_free_vram_bytes(device_index) // (1024 * 1024)
    if free_mb <= 0:
        return 8  # 取得失敗時のデフォルト
    usable_mb = int(free_mb * 0.65)
    batch = max(1, min(20, usable_mb // per_sample_mb))
    return batch

INPUT_W, INPUT_H = 512, 288
FRAME_STACK = 3

WEIGHTS_DIR = Path(__file__).resolve().parent / "weights"
TF_CKPT_PREFIX = WEIGHTS_DIR / "TrackNet"

ONNX_CANDIDATES = [
    WEIGHTS_DIR / "tracknet.onnx",
    WEIGHTS_DIR / "tracknet_v2.onnx",
]
# GPU（CUDA/DirectML）実行時に優先的に使う FP16 モデル。
# keep_io_types=True で保存されているため入出力は float32 のまま、内部演算のみ FP16。
# RTX 5060 Ti 実測: batch=8 で FP32 40fps → FP16 64fps（1.6x）。batch=12 以上で急激なレイテンシ崖あり。
ONNX_FP16_CANDIDATES = [
    WEIGHTS_DIR / "tracknet_fp16.onnx",
]
OPENVINO_XML_CANDIDATES = [
    WEIGHTS_DIR / "tracknet.xml",
    WEIGHTS_DIR / "tracknet_v2.xml",
]


def _existing_path(paths: list[Path]) -> Optional[Path]:
    for path in paths:
        if path.exists():
            return path
    return None


class TrackNetInference:
    def __init__(self, backend: str = "auto", device: str = "GPU",
                 cuda_device_index: int = 0, openvino_device: str = "GPU"):
        self._infer_fn = None
        self._batch_infer_fn = None  # バッチ推論関数 (N,3,H,W)→(N,H,W)、None=シリアルのみ
        self._backend_name = "unloaded"
        self._device = device
        self._backend = backend
        self._cuda_device_index = cuda_device_index
        self._openvino_device = openvino_device  # "GPU" / "GPU.0" / "GPU.1" / "CPU"
        self._load_error: Optional[str] = None
        # GPU バックエンドのロード失敗理由（CPU フォールバック後も残す）
        self._gpu_load_error: Optional[str] = None
        # バックエンド初期化後に設定される最大バッチサイズ
        self._max_batch: int = 4
        # Phase-0: ステージタイマー（SS_TRACKNET_PROFILE=1 で収集）
        self._stage_timings = _StageTimings()
        # Phase-1: GPU 前処理 + IOBinding
        self._gpu_preproc: bool = False          # torch.cuda 前処理が有効か
        self._cuda_device_obj: Optional[object] = None  # torch.device
        self._sess_onnx_cuda: Optional[object] = None   # IOBinding 用セッション参照
        self._io_binding: Optional[object] = None       # ort.IOBinding
        self._iob_input_name: str = ""
        self._iob_output_name: str = ""
        # Phase-3: CUDA Stream 非同期プリフェッチ
        self._preproc_stream: Optional[object] = None   # torch.cuda.Stream

    def get_stage_timings(self) -> dict:
        """最後の predict_frames() 呼び出しのステージ別平均時間を ms 単位で返す。"""
        return self._stage_timings.to_ms_dict()

    def reset_stage_timings(self) -> None:
        """ステージタイマーをリセットする（計測開始前に呼ぶ）。"""
        self._stage_timings.reset()

    def get_load_error(self) -> Optional[str]:
        """ロード失敗時の具体的な理由を返す。成功時または未試行時は None。"""
        return self._load_error

    def is_available(self) -> bool:
        tf_ckpt_exists = (TF_CKPT_PREFIX.with_suffix(".index").exists() and
                          TF_CKPT_PREFIX.parent.joinpath("TrackNet.data-00000-of-00001").exists())
        return (
            tf_ckpt_exists
            or _existing_path(ONNX_CANDIDATES) is not None
            or _existing_path(OPENVINO_XML_CANDIDATES) is not None
        )

    def load(self) -> bool:
        if self._infer_fn is not None:
            return True

        if not self.is_available():
            logger.warning("TrackNet weights not found at %s", WEIGHTS_DIR)
            self._load_error = "重みファイルが見つかりません"
            return False

        tried: list[str] = []
        # 指定バックエンドのファイルが存在しない場合は auto にフォールバックして他を試みる
        effective_backend = self._backend

        # SS_BENCH_BACKEND が設定されている場合はそれを優先する（ベンチマーク専用）。
        # 未設定の場合は SS_USE_GPU=0 なら ONNX CPU へ直行する。
        if effective_backend == "auto":
            bench_override = os.environ.get("SS_BENCH_BACKEND", "")
            if bench_override:
                effective_backend = bench_override
                logger.info("TrackNet: SS_BENCH_BACKEND=%s を使用", bench_override)
            else:
                try:
                    from backend import config as _cfg
                    if int(_cfg.settings.ss_use_gpu) == 0:
                        effective_backend = "onnx_cpu"
                        logger.info("TrackNet: SS_USE_GPU=0 のため ONNX CPU を直接選択")
                except Exception:
                    pass

        onnx_model = _existing_path(ONNX_CANDIDATES)
        # GPU 実行時: TRT は FP32 ONNX + trt_fp16_enable=True の方が安定（FP16 ONNX の
        # 先頭/末尾 Cast が TRT で巨大 ForeignNode 化して tactic 不在になる）。
        # CUDA/DirectML は FP16 ONNX を優先（既存通り）。
        onnx_model_gpu_trt = onnx_model or _existing_path(ONNX_FP16_CANDIDATES)
        onnx_model_gpu = _existing_path(ONNX_FP16_CANDIDATES) or onnx_model

        # ── TensorRT → CUDA → CPU の順で試みる ──────────────────────────────────
        if effective_backend in ("auto", "cuda", "onnx_cuda"):
            if onnx_model_gpu is None:
                if effective_backend in ("cuda", "onnx_cuda"):
                    tried.append("onnx_cuda: ONNXファイルが見つかりません")
                    effective_backend = "auto"
            else:
                try:
                    import onnxruntime as ort
                    available_providers = ort.get_available_providers()
                    if "CUDAExecutionProvider" in available_providers:
                        gpu_mem_limit = _get_gpu_vram_limit_bytes()

                        cuda_opts: dict = {
                            "device_id": self._cuda_device_index,
                            "cudnn_conv_algo_search": "HEURISTIC",
                            "arena_extend_strategy": "kNextPowerOfTwo",
                            "do_copy_in_default_stream": "1",
                        }
                        if gpu_mem_limit > 0:
                            cuda_opts["gpu_mem_limit"] = gpu_mem_limit

                        sess_opts = ort.SessionOptions()
                        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
                        sess_opts.enable_mem_pattern = True
                        sess_opts.enable_mem_reuse = True

                        # TensorRT EP を最優先で試みる（エンジンキャッシュがあれば高速ロード）。
                        # 初回はエンジンコンパイルに数分かかるが 2 回目以降はキャッシュから即ロード。
                        _trt_cache = str(WEIGHTS_DIR / "trt_cache")
                        os.makedirs(_trt_cache, exist_ok=True)
                        _use_trt = (
                            _TRT_AVAILABLE
                            and "TensorrtExecutionProvider" in available_providers
                            and os.environ.get("SS_DISABLE_TRT", "0") not in ("1", "true", "True")
                        )
                        # TRT 向けモデル: FP32 ONNX を優先（TRT 側で FP16 化）。
                        # リアルタイム目的のため opt_shapes は batch=1、max=8。
                        # 実測: opt=8/max=16/ws=6GB が RTX 5060 Ti で最速 (133 fps / 7.5ms per batch=8)
                        _trt_opt_batch = int(os.environ.get("SS_TRACKNET_TRT_OPT_BATCH", "8") or "8")
                        _trt_max_batch = int(os.environ.get("SS_TRACKNET_TRT_MAX_BATCH", "16") or "16")
                        _trt_workspace_gb = int(os.environ.get("SS_TRACKNET_TRT_WORKSPACE_GB", "6") or "6")
                        if _use_trt:
                            trt_opts: dict = {
                                "device_id": self._cuda_device_index,
                                "trt_fp16_enable": True,
                                "trt_engine_cache_enable": True,
                                "trt_engine_cache_path": _trt_cache,
                                "trt_max_workspace_size": _trt_workspace_gb * 1024 ** 3,
                                "trt_builder_optimization_level": 5,
                                "trt_profile_min_shapes": f"input:1x{FRAME_STACK}x{INPUT_H}x{INPUT_W}",
                                "trt_profile_opt_shapes": f"input:{_trt_opt_batch}x{FRAME_STACK}x{INPUT_H}x{INPUT_W}",
                                "trt_profile_max_shapes": f"input:{_trt_max_batch}x{FRAME_STACK}x{INPUT_H}x{INPUT_W}",
                            }
                            providers = [
                                ("TensorrtExecutionProvider", trt_opts),
                                ("CUDAExecutionProvider", cuda_opts),
                                "CPUExecutionProvider",
                            ]
                        else:
                            providers = [
                                ("CUDAExecutionProvider", cuda_opts),
                                "CPUExecutionProvider",
                            ]
                        # 新世代 GPU（Blackwell sm_120 等）で CUDA カーネルコンパイルが
                        # 長時間化・ハングすることがあるためタイムアウト付きで初期化する。
                        import threading
                        _sess_holder: list = [None]
                        _err_holder: list = [None]

                        # TRT 時は FP32 ONNX、CUDA 時は FP16 ONNX を使用
                        _model_for_init = (
                            str(onnx_model_gpu_trt) if _use_trt and onnx_model_gpu_trt is not None
                            else str(onnx_model_gpu)
                        )

                        def _init_sess():
                            try:
                                _sess_holder[0] = ort.InferenceSession(
                                    _model_for_init,
                                    sess_options=sess_opts,
                                    providers=providers,
                                )
                            except Exception as _e:
                                _err_holder[0] = _e

                        _t = threading.Thread(target=_init_sess, daemon=True)
                        _t.start()
                        _t.join(timeout=120)  # 120 秒でタイムアウト（Blackwell 初期化を考慮）

                        if _t.is_alive():
                            tried.append(
                                f"onnx_cuda: 初期化タイムアウト（120s）— Blackwell 等の新 GPU は"
                                " onnxruntime のバージョンアップを待つか ONNX CPU を使用してください"
                            )
                            if effective_backend in ("cuda", "onnx_cuda"):
                                effective_backend = "auto"
                        elif _err_holder[0] is not None:
                            # TRT 付きで失敗した場合、TRT を外して CUDA EP 単体で再試行
                            # （TrackNet の FP16 ONNX は TRT の ForeignNode 実装が無い）
                            _retry_ok = False
                            if _use_trt:
                                tried.append(f"onnx_trt: {_err_holder[0]} — CUDA EP にフォールバック")
                                try:
                                    # CUDA 再試行時は FP16 ONNX を使用
                                    _sess_holder[0] = ort.InferenceSession(
                                        str(onnx_model_gpu),
                                        sess_options=sess_opts,
                                        providers=[
                                            ("CUDAExecutionProvider", cuda_opts),
                                            "CPUExecutionProvider",
                                        ],
                                    )
                                    _err_holder[0] = None
                                    _retry_ok = True
                                except Exception as _e2:
                                    tried.append(f"onnx_cuda retry: {_e2}")
                            if not _retry_ok:
                                tried.append(f"onnx_cuda: {_err_holder[0]}")
                                if effective_backend in ("cuda", "onnx_cuda"):
                                    effective_backend = "auto"
                        else:
                            sess = _sess_holder[0]
                            input_name = sess.get_inputs()[0].name

                            # セッション init 成功後、実際に sess.run() が動くか確認する。
                            # Blackwell (sm_120) 等の新世代 GPU では init は通るが
                            # 最初の sess.run() で CUDA カーネルエラーが出るケースがある。
                            _run_ok = threading.Event()
                            _run_err: list = [None]

                            def _verify_run():
                                try:
                                    dummy = np.zeros(
                                        (1, FRAME_STACK, INPUT_H, INPUT_W), dtype=np.float32
                                    )
                                    sess.run(None, {input_name: dummy})
                                except Exception as _e:
                                    _run_err[0] = _e
                                finally:
                                    _run_ok.set()

                            threading.Thread(target=_verify_run, daemon=True).start()
                            _run_ok.wait(timeout=60)  # 60s: cuDNN アルゴリズム初回選択を考慮

                            if not _run_ok.is_set():
                                _reason = (
                                    "CUDA 初回推論タイムアウト（60s）— Blackwell 等の新 GPU は"
                                    " onnxruntime のバージョンアップが必要な場合があります"
                                )
                                tried.append(_reason)
                                self._gpu_load_error = _reason
                                if effective_backend in ("cuda", "onnx_cuda"):
                                    effective_backend = "auto"
                            elif _run_err[0] is not None:
                                _reason = (
                                    f"CUDA 初回推論失敗: {_run_err[0]}"
                                )
                                tried.append(_reason)
                                self._gpu_load_error = _reason
                                if effective_backend in ("cuda", "onnx_cuda"):
                                    effective_backend = "auto"
                            else:
                                # FP16 使用時はバッチ=8 固定（batch>=12 で約 5-6 倍の急激なレイテンシ劣化を実測）。
                                # FP32 のみの場合は VRAM から推定するが、同様の劣化があるため 8 で頭打ちにする。
                                is_fp16 = onnx_model_gpu is not None and "fp16" in onnx_model_gpu.name.lower()
                                if is_fp16:
                                    self._max_batch = 8
                                else:
                                    self._max_batch = min(8, _vram_based_max_batch(self._cuda_device_index))
                                self._infer_fn = lambda frames, _s=sess, _n=input_name: self._run_onnx(_s, _n, frames)
                                self._batch_infer_fn = lambda batch, _s=sess, _n=input_name: self._run_onnx_batch(_s, _n, batch)
                                actual_eps = sess.get_providers()
                                _ep_short = "trt" if any("Tensorrt" in e for e in actual_eps) else "cuda"
                                self._backend_name = f"onnx_{_ep_short}:{self._cuda_device_index}"
                                self._load_error = None
                                # Phase-1: GPU 前処理 + IOBinding を試みる
                                self._sess_onnx_cuda = sess
                                self._init_gpu_preproc(sess, input_name, self._cuda_device_index)
                                logger.info(
                                    "TrackNet loaded via %s (device=%d, model=%s, max_batch=%d, eps=%s, gpu_preproc=%s)",
                                    self._backend_name, self._cuda_device_index,
                                    onnx_model_gpu.name, self._max_batch, actual_eps,
                                    self._gpu_preproc,
                                )
                                return True
                    elif effective_backend in ("cuda", "onnx_cuda"):
                        tried.append("onnx_cuda: CUDAExecutionProvider が利用不可（onnxruntime-gpu 未インストール）")
                        effective_backend = "auto"
                    # auto の場合は次の候補へ続行
                except Exception as exc:
                    tried.append(f"onnxruntime: {exc}")
                    if effective_backend in ("cuda", "onnx_cuda"):
                        effective_backend = "auto"

        # ── DirectML（AMD/NVIDIA Windows）──────────────────────────────────────
        if effective_backend in ("auto", "directml"):
            if onnx_model_gpu is None:
                if effective_backend == "directml":
                    tried.append("directml: ONNXファイルが見つかりません（自動フォールバック）")
                    effective_backend = "auto"
            else:
                try:
                    import onnxruntime as ort
                    _dml_available = "DmlExecutionProvider" in ort.get_available_providers()
                    if not _dml_available:
                        # onnxruntime-directml が未インストール（メイン venv は ONNX CPU 版のみ）
                        # → 他バックエンドへフォールバック可能にする
                        if effective_backend == "directml":
                            tried.append("directml: DmlExecutionProvider が onnxruntime に含まれていません (pip install onnxruntime-directml が必要)")
                            effective_backend = "auto"
                    if _dml_available:
                        providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
                        sess = ort.InferenceSession(str(onnx_model_gpu), providers=providers)
                        input_name = sess.get_inputs()[0].name

                        # Blackwell 等の新 GPU では sess.run() の初回 DirectML シェーダ
                        # コンパイルが数分〜永続ハングすることがある。
                        # ウォームアップ推論をタイムアウト付きスレッドで実行し、
                        # 完了しない場合は ONNX CPU にフォールバックする。
                        import threading
                        _wu_done = threading.Event()
                        _wu_err: list = [None]

                        def _warmup_dml():
                            try:
                                dummy = np.zeros(
                                    (1, FRAME_STACK, INPUT_H, INPUT_W), dtype=np.float32
                                )
                                sess.run(None, {input_name: dummy})
                            except Exception as _e:
                                _wu_err[0] = _e
                            finally:
                                _wu_done.set()

                        _wu_t = threading.Thread(target=_warmup_dml, daemon=True)
                        _wu_t.start()
                        _wu_done.wait(timeout=30)  # 30 秒以内に完了しなければ諦める

                        if not _wu_done.is_set():
                            tried.append(
                                "directml: ウォームアップ推論タイムアウト（30s）— "
                                "Blackwell 等の新 GPU は onnxruntime-directml の"
                                "バージョンアップを待つか ONNX CPU を使用してください"
                            )
                            if effective_backend == "directml":
                                effective_backend = "auto"
                        elif _wu_err[0] is not None:
                            tried.append(f"directml: ウォームアップ失敗: {_wu_err[0]}")
                            if effective_backend == "directml":
                                effective_backend = "auto"
                        else:
                            # DirectML: VRAM 量が不明なため OOM 回復前提で 32 を初期値とする
                            self._max_batch = 32
                            self._infer_fn = lambda frames, _s=sess, _n=input_name: self._run_onnx(_s, _n, frames)
                            self._batch_infer_fn = lambda batch, _s=sess, _n=input_name: self._run_onnx_batch(_s, _n, batch)
                            self._backend_name = "onnx_directml"
                            self._load_error = None
                            logger.info("TrackNet loaded via ONNX DirectML (warmup OK, max_batch=%d)", self._max_batch)
                            return True
                except Exception as exc:
                    tried.append(f"directml: {exc}")

        # ── OpenVINO ──────────────────────────────────────────────────────────
        openvino_xml = _existing_path(OPENVINO_XML_CANDIDATES)
        if effective_backend in ("auto", "openvino"):
            if openvino_xml is None:
                if effective_backend == "openvino":
                    tried.append("openvino: XMLファイルが見つかりません（自動フォールバック）")
                    effective_backend = "auto"
            else:
                try:
                    import threading as _ov_threading
                    import openvino as ov
                    core = ov.Core()
                    available = core.available_devices
                    device_candidates: list[str] = []
                    if self._openvino_device and self._openvino_device in available:
                        device_candidates.append(self._openvino_device)
                    for fallback in ("GPU", "CPU"):
                        if fallback in available and fallback not in device_candidates:
                            device_candidates.append(fallback)
                    if not device_candidates:
                        device_candidates = ["CPU"]
                    ov_model = core.read_model(str(openvino_xml))
                    # dynamic shape モデルを静的シェイプに固定（K10等で必須）
                    try:
                        _inp = ov_model.input(0)
                        _inp_name = _inp.any_name
                        ov_model.reshape({_inp_name: [1, FRAME_STACK, INPUT_H, INPUT_W]})
                    except Exception:
                        pass
                    for dev in device_candidates:
                        try:
                            # compile_model は初回に数分かかることがあるためタイムアウト付きで実行
                            _ov_result: list = [None]
                            _ov_err: list = [None]
                            _ov_done = _ov_threading.Event()

                            def _compile_ov(d=dev):
                                try:
                                    config = {"PERFORMANCE_HINT": "THROUGHPUT"}
                                    _ov_result[0] = core.compile_model(ov_model, d, config)
                                except Exception as _e:
                                    _ov_err[0] = _e
                                finally:
                                    _ov_done.set()

                            _ov_threading.Thread(target=_compile_ov, daemon=True).start()
                            _ov_done.wait(timeout=60)

                            if not _ov_done.is_set():
                                tried.append(f"openvino:{dev}: compile_model タイムアウト（60s）")
                                continue
                            if _ov_err[0] is not None:
                                tried.append(f"openvino:{dev}: {_ov_err[0]}")
                                continue

                            compiled = _ov_result[0]
                            input_name = compiled.input(0).any_name
                            req = compiled.create_infer_request()
                            self._infer_fn = lambda frames, _req=req, _name=input_name: \
                                self._run_openvino(_req, _name, frames)
                            self._backend_name = f"openvino:{dev}"
                            self._load_error = None
                            logger.info("TrackNet loaded via OpenVINO on %s", dev)
                            return True
                        except Exception as exc:
                            tried.append(f"openvino:{dev}: {exc}")
                            continue
                except ImportError:
                    logger.info("openvino not installed, falling back")
                    tried.append("openvino: パッケージ未インストール")
                    effective_backend = "auto"

        # ── ONNX CPU ──────────────────────────────────────────────────────────
        if effective_backend in ("auto", "onnx_cpu"):
            if onnx_model is None:
                tried.append("onnx_cpu: ONNXファイルが見つかりません")
            else:
                try:
                    import onnxruntime as ort
                    sess = ort.InferenceSession(str(onnx_model), providers=["CPUExecutionProvider"])
                    input_name = sess.get_inputs()[0].name
                    self._infer_fn = lambda frames, _s=sess, _n=input_name: self._run_onnx(_s, _n, frames)
                    # CPU EP はバッチ化すると中間バッファが数GB になりメモリ帯域が詰まる。
                    # OCLink 往復削減の恩恵もないため serial のみ（_batch_infer_fn = None のまま）。
                    self._backend_name = "onnx_cpu"
                    self._load_error = None
                    logger.info("TrackNet loaded via ONNX Runtime CPU")
                    return True
                except ImportError:
                    tried.append("onnxruntime: パッケージ未インストール")
                    logger.info("onnxruntime not installed, falling back")
                except Exception as exc:
                    tried.append(f"onnxruntime: {exc}")

        if effective_backend in ("auto", "tensorflow_cpu") and TF_CKPT_PREFIX.with_suffix(".index").exists():
            try:
                from backend.tracknet.model import build_tracknet_model

                model = build_tracknet_model()
                model.load_weights(str(TF_CKPT_PREFIX)).expect_partial()
                self._infer_fn = lambda frames: self._run_tensorflow(model, frames)
                # TF CPU も中間バッファが大きいため serial のみ
                self._backend_name = "tensorflow_cpu"
                self._load_error = None
                logger.info("TrackNet loaded via TensorFlow CPU/Intel backend")
                return True
            except ImportError:
                tried.append("tensorflow: パッケージ未インストール")
                logger.warning("tensorflow is not installed")
            except Exception as exc:
                tried.append(f"tensorflow: {exc}")
                logger.exception("TrackNet TensorFlow load failed: %s", exc)

        self._load_error = "使えるバックエンドがありません。試みたバックエンド: " + "; ".join(tried) if tried else "重みファイルが見つかりません"
        logger.error("TrackNet: no usable inference backend found. %s", self._load_error)
        return False

    def backend_name(self) -> str:
        return self._backend_name

    def predict_frames(self, frames: list[np.ndarray]) -> list[dict]:
        if self._infer_fn is None and not self.load():
            return []

        n_triplets = len(frames) - FRAME_STACK + 1
        if n_triplets <= 0:
            return []

        # バッチ対応バックエンド（ONNX CUDA/DML/CPU・TF）は全トリプレットを
        # 1 回の sess.run() で処理 → OCLink/PCIe 往復を N 回 → 1 回に削減
        if self._batch_infer_fn is not None:
            # Phase-1: GPU 前処理 + IOBinding が有効ならフル GPU パスで実行
            if self._gpu_preproc:
                return self._predict_frames_batch_gpu(frames, n_triplets)
            return self._predict_frames_batch(frames, n_triplets)
        return self._predict_frames_serial(frames, n_triplets)

    def _predict_frames_batch(self, frames: list[np.ndarray], n_triplets: int) -> list[dict]:
        """トリプレットを _max_batch 件ずつバッチ推論。

        隣接トリプレット間でフレームが重複するため各フレームは 1 回だけ前処理する
        （例: batch=25 なら最大 75 回 → 27 回に削減）。
        OOM が発生した場合はバッチサイズを半減して再試行する（最小 1）。
        """
        from backend.tracknet.zone_mapper import heatmap_to_zone

        chunk_size = max(1, self._max_batch)
        results = []
        chunk_start = 0
        # フレームキャッシュ: インデックス → 前処理済み (H, W) float32
        frame_cache: dict[int, np.ndarray] = {}

        # Phase-4: adaptive skip state
        skip_threshold, max_skip = _skip_config()
        skip_enabled = skip_threshold <= 1.0
        prev_result: Optional[dict] = None
        pprev_result: Optional[dict] = None
        skip_count = 0

        _profile = _profile_enabled()
        _st = self._stage_timings
        if _profile:
            _st.reset()

        while chunk_start < n_triplets:
            chunk_end = min(chunk_start + chunk_size, n_triplets)

            # ── preprocess ──────────────────────────────────────────────────
            with _nvtx_range("tracknet/preprocess"):
                _t0 = time.perf_counter() if _profile else 0.0
                needed_end = min(chunk_end + FRAME_STACK - 1, len(frames))
                for fi in range(chunk_start, needed_end):
                    if fi not in frame_cache:
                        frame_cache[fi] = self._preprocess_frame(frames[fi])
                for fi in list(frame_cache):
                    if fi < chunk_start:
                        del frame_cache[fi]
                if _profile:
                    _st.preprocess += time.perf_counter() - _t0

            # ── stack ────────────────────────────────────────────────────────
            with _nvtx_range("tracknet/stack"):
                _t0 = time.perf_counter() if _profile else 0.0
                batch_inp = np.stack(
                    [
                        np.stack([frame_cache[i + j] for j in range(FRAME_STACK)], axis=0)
                        for i in range(chunk_start, chunk_end)
                    ],
                    axis=0,
                ).astype(np.float32)  # (chunk, 3, H, W)
                if _profile:
                    _st.stack += time.perf_counter() - _t0

            # ── infer ────────────────────────────────────────────────────────
            with _nvtx_range("tracknet/infer"):
                _t0 = time.perf_counter() if _profile else 0.0
                try:
                    heatmaps = self._batch_infer_fn(batch_inp)  # (chunk, H, W)
                except Exception as exc:
                    err_msg = str(exc).lower()
                    if chunk_size > 1 and ("memory" in err_msg or "alloc" in err_msg or "oom" in err_msg):
                        chunk_size = max(1, chunk_size // 2)
                        self._max_batch = chunk_size
                        logger.warning(
                            "TrackNet batch OOM — バッチサイズを %d に削減して再試行", chunk_size
                        )
                        continue
                    raise
                if _profile:
                    _st.infer += time.perf_counter() - _t0

            # ── postproc ─────────────────────────────────────────────────────
            with _nvtx_range("tracknet/postproc"):
                _t0 = time.perf_counter() if _profile else 0.0
                for j, heatmap in enumerate(heatmaps):
                    zone, conf, coords = heatmap_to_zone(heatmap)
                    results.append({
                        "frame_idx": chunk_start + j + 1,
                        "zone": zone,
                        "confidence": round(conf, 3),
                        "x_norm": round(coords[0], 4) if coords else None,
                        "y_norm": round(coords[1], 4) if coords else None,
                    })
                # Phase-4: prev/pprev を実推論結果で更新
                if results:
                    pprev_result = prev_result
                    prev_result = results[-1]
                if _profile:
                    _st.postproc += time.perf_counter() - _t0

            # ── Phase-4: confidence-based adaptive skip ──────────────────────
            if skip_enabled and prev_result is not None:
                while (
                    chunk_end < n_triplets
                    and (prev_result.get("confidence") or 0.0) >= skip_threshold
                    and skip_count < max_skip
                ):
                    extra = _extrapolate_position(prev_result, pprev_result, chunk_end + 1)
                    results.append(extra)
                    pprev_result = prev_result
                    prev_result = extra
                    skip_count += 1
                    chunk_end += 1
            skip_count = 0  # 実推論後はリセット

            if _profile:
                _st.n_chunks += 1
            chunk_start = chunk_end
        return results

    def _predict_frames_serial(self, frames: list[np.ndarray], n_triplets: int) -> list[dict]:
        """トリプレットを 1 件ずつ推論（OpenVINO 等バッチ非対応バックエンド向け）。"""
        from backend.tracknet.zone_mapper import heatmap_to_zone

        results = []
        for i in range(n_triplets):
            inp = self._preprocess(frames[i: i + FRAME_STACK])
            heatmap = self._infer_fn(inp)
            zone, conf, coords = heatmap_to_zone(heatmap)
            results.append({
                "frame_idx": i + 1,
                "zone": zone,
                "confidence": round(conf, 3),
                "x_norm": round(coords[0], 4) if coords else None,
                "y_norm": round(coords[1], 4) if coords else None,
            })
        return results

    def _preprocess_frame(self, frame: np.ndarray) -> np.ndarray:
        """1 フレームをリサイズ + グレースケール変換。(H, W) float32 を返す。"""
        import cv2
        resized = cv2.resize(frame, (INPUT_W, INPUT_H))
        return cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0

    def _preprocess(self, frames: list[np.ndarray]) -> np.ndarray:
        stacked = np.stack([self._preprocess_frame(f) for f in frames], axis=0)  # (3, H, W)
        return stacked[np.newaxis].astype(np.float32)  # (1, 3, H, W)

    def _run_openvino(self, req, input_name: str, inp: np.ndarray) -> np.ndarray:
        req.infer(inputs={input_name: inp})
        out = req.get_output_tensor(0).data
        return out[0, 0]

    def _run_onnx(self, sess, input_name: str, inp: np.ndarray) -> np.ndarray:
        out = sess.run(None, {input_name: inp})[0]
        return out[0, 0]

    def _run_onnx_batch(self, sess, input_name: str, batch_inp: np.ndarray) -> np.ndarray:
        """バッチ ONNX 推論: (N, 3, H, W) → (N, H, W)。OCLink 往復 1 回で N トリプレット処理。"""
        out = sess.run(None, {input_name: batch_inp})[0]  # (N, 1, H, W)
        return out[:, 0]  # (N, H, W)

    def _run_tensorflow(self, model, inp: np.ndarray) -> np.ndarray:
        out = model(inp, training=False).numpy()
        return out[0, 0]

    def _run_tensorflow_batch(self, model, batch_inp: np.ndarray) -> np.ndarray:
        """バッチ TF 推論: (N, 3, H, W) → (N, H, W)。"""
        out = model(batch_inp, training=False).numpy()  # (N, 1, H, W)
        return out[:, 0]  # (N, H, W)

    # ── Phase-1: GPU 前処理 + IOBinding ─────────────────────────────────────

    def _init_gpu_preproc(self, sess, input_name: str, device_idx: int) -> None:
        """torch.cuda 前処理と ONNX Runtime IOBinding を初期化する。

        初期化に失敗しても self._gpu_preproc = False のまま CPU パスにフォールバックする。
        SS_DISABLE_GPU_PREPROC=1 で強制無効化（デバッグ用）。
        """
        if os.environ.get("SS_DISABLE_GPU_PREPROC", "0") in ("1", "true", "True"):
            logger.info("TrackNet: SS_DISABLE_GPU_PREPROC=1 — GPU前処理を無効化")
            return
        try:
            import torch
            if not torch.cuda.is_available():
                logger.info("TrackNet: torch.cuda 不可 — GPU前処理を無効化")
                return
            self._cuda_device_obj = torch.device(f"cuda:{device_idx}")
            # IOBinding の動作確認（ダミー推論）
            iob = sess.io_binding()
            dummy = torch.zeros(
                (1, FRAME_STACK, INPUT_H, INPUT_W),
                dtype=torch.float32,
                device=self._cuda_device_obj,
            ).contiguous()
            output_name = sess.get_outputs()[0].name
            iob.bind_input(
                name=input_name,
                device_type="cuda",
                device_id=device_idx,
                element_type=np.float32,
                shape=(1, FRAME_STACK, INPUT_H, INPUT_W),
                buffer_ptr=dummy.data_ptr(),
            )
            iob.bind_output(
                name=output_name,
                device_type="cuda",
                device_id=device_idx,
            )
            sess.run_with_iobinding(iob)
            # 確認 OK → 本番用 IOBinding をセット
            self._io_binding = sess.io_binding()
            self._iob_input_name = input_name
            self._iob_output_name = output_name
            self._gpu_preproc = True
            # Phase-3: 前処理専用 CUDA Stream を作成（推論の default stream と独立）
            self._preproc_stream = torch.cuda.Stream(device=self._cuda_device_obj)
            logger.info(
                "TrackNet: GPU前処理 (torch.cuda) + IOBinding + CUDA Stream 有効 (device=cuda:%d)",
                device_idx,
            )
        except Exception as exc:
            logger.warning("TrackNet: GPU前処理初期化失敗 — CPU前処理にフォールバック: %s", exc)
            self._gpu_preproc = False

    def _preprocess_batch_gpu(
        self, frames: list, indices: list[int]
    ):
        """numpy uint8 BGR フレームを GPU で一括前処理する。

        resize + BGR→Gray + normalize を torch.cuda 上で実行し
        (N, INPUT_H, INPUT_W) float32 CUDA tensor を返す。
        CPU 前処理と等価: cv2.resize(BGR2GRAY) / 255.0
        """
        import torch
        import torch.nn.functional as F

        raw = np.stack([frames[i] for i in indices], axis=0)  # (N, H, W, 3) uint8
        # numpy → CUDA tensor (non_blocking H2D)
        t = torch.from_numpy(raw).to(self._cuda_device_obj, non_blocking=True)
        # (N, H, W, 3) → (N, 3, H, W)、float に変換
        t = t.permute(0, 3, 1, 2).float()
        # GPU resize (bilinear)
        t = F.interpolate(
            t, size=(INPUT_H, INPUT_W), mode="bilinear", align_corners=False
        )  # (N, 3, INPUT_H, INPUT_W)
        # BGR → Gray: 0.299*R + 0.587*G + 0.114*B (B=ch0, G=ch1, R=ch2)
        gray = (0.114 * t[:, 0] + 0.587 * t[:, 1] + 0.299 * t[:, 2]) / 255.0
        return gray  # (N, INPUT_H, INPUT_W) float32 CUDA

    def _run_onnx_batch_iobinding(self, batch_tensor):
        """IOBinding で CUDA tensor を直接 ONNX Runtime に渡す。

        batch_tensor: (N, FRAME_STACK, H, W) float32 CUDA tensor
        戻り値: (N, H, W) float32 CUDA tensor（Phase-2 GPU argmax 用）
               DLPack 非対応環境は numpy を torch tensor に変換して返す。
        """
        import torch
        batch_tensor = batch_tensor.contiguous()
        iob = self._io_binding
        iob.bind_input(
            name=self._iob_input_name,
            device_type="cuda",
            device_id=self._cuda_device_index,
            element_type=np.float32,
            shape=tuple(batch_tensor.shape),
            buffer_ptr=batch_tensor.data_ptr(),
        )
        iob.bind_output(
            name=self._iob_output_name,
            device_type="cuda",
            device_id=self._cuda_device_index,
        )
        self._sess_onnx_cuda.run_with_iobinding(iob)
        out_ort = iob.get_outputs()[0]
        try:
            # DLPack 経由: D2H なしで CUDA tensor に変換（Phase-2 GPU argmax 用）
            out_tensor = torch.from_dlpack(out_ort.to_dlpack())  # (N, 1, H, W) CUDA
            return out_tensor[:, 0].contiguous()  # (N, H, W) CUDA
        except Exception:
            # to_dlpack() 未対応 → numpy 経由（D2H 1 回）→ GPU に戻す
            out_np = out_ort.numpy()  # (N, 1, H, W)
            return torch.from_numpy(out_np[:, 0]).to(self._cuda_device_obj)

    def _preprocess_chunk_to_cache(
        self,
        frames: list,
        frame_cache_gpu: dict,
        chunk_start: int,
        chunk_end: int,
    ) -> None:
        """chunk_start..chunk_end のトリプレットに必要なフレームを前処理してキャッシュする。

        呼び出し元が torch.cuda.stream() コンテキストを制御する（Stream 非同期化のため）。
        """
        needed_end = min(chunk_end + FRAME_STACK - 1, len(frames))
        uncached = [fi for fi in range(chunk_start, needed_end) if fi not in frame_cache_gpu]
        if uncached:
            gpu_tensors = self._preprocess_batch_gpu(frames, uncached)
            for k, fi in enumerate(uncached):
                frame_cache_gpu[fi] = gpu_tensors[k]

    def _predict_frames_batch_gpu(
        self, frames: list, n_triplets: int
    ) -> list[dict]:
        """フル GPU パス: torch.cuda 前処理 + IOBinding 推論 + CUDA Stream プリフェッチ。

        Phase-3 パイプライン:
          preproc_stream: [PRE_0]      [PRE_1]        [PRE_2] …
          default stream:      [INF_0]       [INF_1]        …
          CPU:                       [POST_0]      [POST_1]  …

        PRE_{N+1} が INF_N と同時に実行されるため前処理オーバーヘッドが隠蔽される。
        _preproc_stream が None (CUDA なし) の場合は同期版にフォールバックする。
        IOBinding 非対応時は _batch_infer_fn で numpy 経由に fallback する。
        OOM 時はバッチサイズを半減して再試行する（最小 1）。
        """
        import torch
        from backend.tracknet.zone_mapper import batch_heatmap_argmax

        chunk_size = max(1, self._max_batch)
        results: list[dict] = []
        chunk_start = 0
        frame_cache_gpu: dict[int, object] = {}

        # Phase-4: adaptive skip state
        skip_threshold, max_skip = _skip_config()
        skip_enabled = skip_threshold <= 1.0
        prev_result: Optional[dict] = None
        pprev_result: Optional[dict] = None
        skip_count = 0

        _profile = _profile_enabled()
        _st = self._stage_timings
        if _profile:
            _st.reset()

        preproc_stream = self._preproc_stream  # None → 同期フォールバック
        default_stream = (
            torch.cuda.default_stream(self._cuda_device_obj)
            if preproc_stream is not None else None
        )

        # ── Phase-3: 最初のチャンクを preproc_stream で先行投入 ─────────────
        with _nvtx_range("tracknet/preprocess"):
            _t0 = time.perf_counter() if _profile else 0.0
            first_end = min(chunk_size, n_triplets)
            if preproc_stream is not None:
                with torch.cuda.stream(preproc_stream):
                    self._preprocess_chunk_to_cache(frames, frame_cache_gpu, 0, first_end)
                # default stream が最初の推論を開始する前に preproc 完了を待つ
                default_stream.wait_stream(preproc_stream)
            else:
                self._preprocess_chunk_to_cache(frames, frame_cache_gpu, 0, first_end)
            if _profile:
                _st.preprocess += time.perf_counter() - _t0

        while chunk_start < n_triplets:
            chunk_end = min(chunk_start + chunk_size, n_triplets)
            next_start = chunk_end
            next_end = min(next_start + chunk_size, n_triplets)

            # 古いキャッシュエントリを解放
            for fi in list(frame_cache_gpu):
                if fi < chunk_start:
                    del frame_cache_gpu[fi]

            # ── stack (GPU default stream) ───────────────────────────────────
            with _nvtx_range("tracknet/stack"):
                _t0 = time.perf_counter() if _profile else 0.0
                batch_tensor = torch.stack(
                    [
                        torch.stack(
                            [frame_cache_gpu[i + j] for j in range(FRAME_STACK)], dim=0
                        )
                        for i in range(chunk_start, chunk_end)
                    ],
                    dim=0,
                ).contiguous()  # (chunk, FRAME_STACK, H, W) CUDA float32
                if _profile:
                    _st.stack += time.perf_counter() - _t0

            # ── Phase-3: 次チャンクを preproc_stream で先行投入（infer と並走）─
            with _nvtx_range("tracknet/preprocess"):
                _t0 = time.perf_counter() if _profile else 0.0
                if next_start < n_triplets:
                    if preproc_stream is not None:
                        with torch.cuda.stream(preproc_stream):
                            self._preprocess_chunk_to_cache(
                                frames, frame_cache_gpu, next_start, next_end
                            )
                    else:
                        self._preprocess_chunk_to_cache(
                            frames, frame_cache_gpu, next_start, next_end
                        )
                if _profile:
                    _st.preprocess += time.perf_counter() - _t0

            # ── infer (IOBinding, default stream) ────────────────────────────
            with _nvtx_range("tracknet/infer"):
                _t0 = time.perf_counter() if _profile else 0.0
                try:
                    if self._io_binding is not None:
                        heatmaps = self._run_onnx_batch_iobinding(batch_tensor)
                    else:
                        heatmaps = self._batch_infer_fn(batch_tensor.cpu().numpy())
                except Exception as exc:
                    err_msg = str(exc).lower()
                    if chunk_size > 1 and (
                        "memory" in err_msg or "alloc" in err_msg or "oom" in err_msg
                    ):
                        chunk_size = max(1, chunk_size // 2)
                        self._max_batch = chunk_size
                        logger.warning(
                            "TrackNet GPU batch OOM — バッチサイズを %d に削減して再試行", chunk_size
                        )
                        continue
                    raise
                if _profile:
                    _st.infer += time.perf_counter() - _t0

            # ── postproc: GPU argmax + CPU zone 分類 ─────────────────────────
            # この CPU ブロック中に preproc_stream 上の次チャンク前処理が進行する
            with _nvtx_range("tracknet/postproc"):
                _t0 = time.perf_counter() if _profile else 0.0
                zone_results = batch_heatmap_argmax(heatmaps)
                for j, (zone, conf, coords) in enumerate(zone_results):
                    results.append({
                        "frame_idx": chunk_start + j + 1,
                        "zone": zone,
                        "confidence": round(conf, 3),
                        "x_norm": round(coords[0], 4) if coords else None,
                        "y_norm": round(coords[1], 4) if coords else None,
                    })
                # Phase-4: prev/pprev を実推論結果で更新
                if zone_results:
                    pprev_result = prev_result
                    prev_result = results[-1]
                if _profile:
                    _st.postproc += time.perf_counter() - _t0

            # ── Phase-4: confidence-based adaptive skip ──────────────────────
            # prev_result の confidence が skip_threshold 以上なら次のトリプレットを
            # 推論スキップし、速度外挿で位置を予測する。chunk_end を進めることで
            # while ループの次イテレーションがスキップ済みトリプレットを飛ばす。
            if skip_enabled and prev_result is not None:
                while (
                    chunk_end < n_triplets
                    and (prev_result.get("confidence") or 0.0) >= skip_threshold
                    and skip_count < max_skip
                ):
                    extra = _extrapolate_position(prev_result, pprev_result, chunk_end + 1)
                    results.append(extra)
                    pprev_result = prev_result
                    prev_result = extra
                    skip_count += 1
                    chunk_end += 1
            skip_count = 0  # 実推論後はリセット

            # ── Phase-3: 次イテレーションの infer 前に preproc 完了を保証 ────
            if preproc_stream is not None and next_start < n_triplets:
                with _nvtx_range("tracknet/stream_sync"):
                    default_stream.wait_stream(preproc_stream)

            if _profile:
                _st.n_chunks += 1
            chunk_start = chunk_end
        return results


_instance: Optional[TrackNetInference] = None


def get_inference(backend: str = "auto", cuda_device_index: int = 0,
                  openvino_device: str = "GPU") -> TrackNetInference:
    global _instance
    config_changed = (
        _instance is None
        or (_instance._backend != backend and backend != "auto")
        or _instance._cuda_device_index != cuda_device_index
        or _instance._openvino_device != openvino_device
    )
    if config_changed:
        _instance = TrackNetInference(
            backend=backend,
            cuda_device_index=cuda_device_index,
            openvino_device=openvino_device,
        )
    return _instance
