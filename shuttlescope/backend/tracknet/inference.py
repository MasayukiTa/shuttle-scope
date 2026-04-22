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

import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def _register_cuda_dll_dirs() -> None:
    """PyTorch 同梱の CUDA/cuDNN DLL を ONNX Runtime GPU から参照可能にする。

    os.add_dll_directory() のみ使用する。PATH を変更すると OpenVINO が
    CUDA 経由で NVIDIA GPU を検出してしまい AMD/Intel iGPU ベンチが壊れる。
    """
    try:
        import torch  # type: ignore
        lib_dir = os.path.join(os.path.dirname(torch.__file__), "lib")
        if not os.path.isdir(lib_dir):
            return
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(lib_dir)
            except (FileNotFoundError, OSError):
                pass
    except Exception:
        pass


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
        # GPU 実行時は FP16 版があればそちらを優先する
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
                        if _use_trt:
                            trt_opts: dict = {
                                "device_id": self._cuda_device_index,
                                "trt_fp16_enable": True,
                                "trt_engine_cache_enable": True,
                                "trt_engine_cache_path": _trt_cache,
                                "trt_max_workspace_size": 2 * 1024 ** 3,
                                # バッチ範囲: 1〜16、最適化点=8 (実用スループット sweet spot)
                                "trt_profile_min_shapes": f"input:1x{FRAME_STACK}x{INPUT_H}x{INPUT_W}",
                                "trt_profile_opt_shapes": f"input:8x{FRAME_STACK}x{INPUT_H}x{INPUT_W}",
                                "trt_profile_max_shapes": f"input:16x{FRAME_STACK}x{INPUT_H}x{INPUT_W}",
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

                        def _init_sess():
                            try:
                                _sess_holder[0] = ort.InferenceSession(
                                    str(onnx_model_gpu),
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
                                logger.info(
                                    "TrackNet loaded via %s (device=%d, model=%s, max_batch=%d, eps=%s)",
                                    self._backend_name, self._cuda_device_index,
                                    onnx_model_gpu.name, self._max_batch, actual_eps,
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
            if onnx_model_gpu is not None:
                try:
                    import onnxruntime as ort
                    if "DmlExecutionProvider" in ort.get_available_providers():
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

        while chunk_start < n_triplets:
            chunk_end = min(chunk_start + chunk_size, n_triplets)

            # このチャンクで必要なフレームを前処理（未キャッシュ分のみ）
            needed_end = min(chunk_end + FRAME_STACK - 1, len(frames))
            for fi in range(chunk_start, needed_end):
                if fi not in frame_cache:
                    frame_cache[fi] = self._preprocess_frame(frames[fi])
            # 不要になった古いエントリを解放
            for fi in list(frame_cache):
                if fi < chunk_start:
                    del frame_cache[fi]

            batch_inp = np.stack(
                [
                    np.stack([frame_cache[i + j] for j in range(FRAME_STACK)], axis=0)
                    for i in range(chunk_start, chunk_end)
                ],
                axis=0,
            ).astype(np.float32)  # (chunk, 3, H, W)

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
            for j, heatmap in enumerate(heatmaps):
                zone, conf, coords = heatmap_to_zone(heatmap)
                results.append({
                    "frame_idx": chunk_start + j + 1,
                    "zone": zone,
                    "confidence": round(conf, 3),
                    "x_norm": round(coords[0], 4) if coords else None,
                    "y_norm": round(coords[1], 4) if coords else None,
                })
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
