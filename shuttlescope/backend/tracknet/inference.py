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
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

INPUT_W, INPUT_H = 512, 288
FRAME_STACK = 3

WEIGHTS_DIR = Path(__file__).parent / "weights"
TF_CKPT_PREFIX = WEIGHTS_DIR / "TrackNet"

ONNX_CANDIDATES = [
    WEIGHTS_DIR / "tracknet.onnx",
    WEIGHTS_DIR / "tracknet_v2.onnx",
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

        # SS_USE_GPU=0 のとき auto モードでも CUDA/DirectML をスキップして CPU 系へ直行する。
        # CPU デバイスのベンチマークが誤って CUDA EP で計測されることを防ぐ。
        if effective_backend == "auto":
            try:
                from backend import config as _cfg
                if int(_cfg.settings.ss_use_gpu) == 0:
                    effective_backend = "onnx_cpu"
                    logger.info("TrackNet: SS_USE_GPU=0 のため ONNX CPU を直接選択")
            except Exception:
                pass

        onnx_model = _existing_path(ONNX_CANDIDATES)

        # ── CUDA / ONNX CUDA ──────────────────────────────────────────────────
        if effective_backend in ("auto", "cuda", "onnx_cuda"):
            if onnx_model is None:
                if effective_backend in ("cuda", "onnx_cuda"):
                    tried.append("onnx_cuda: ONNXファイルが見つかりません")
                    effective_backend = "auto"
            else:
                try:
                    import onnxruntime as ort
                    available_providers = ort.get_available_providers()
                    if "CUDAExecutionProvider" in available_providers:
                        providers = [
                            ("CUDAExecutionProvider", {"device_id": self._cuda_device_index}),
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
                                    str(onnx_model), providers=providers
                                )
                            except Exception as _e:
                                _err_holder[0] = _e

                        _t = threading.Thread(target=_init_sess, daemon=True)
                        _t.start()
                        _t.join(timeout=120)  # 120 秒でタイムアウト（スレッドプール内での CUDA 初期化を考慮）

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
                            self._infer_fn = lambda frames, _s=sess, _n=input_name: self._run_onnx(_s, _n, frames)
                            self._batch_infer_fn = lambda batch, _s=sess, _n=input_name: self._run_onnx_batch(_s, _n, batch)
                            self._backend_name = f"onnx_cuda:{self._cuda_device_index}"
                            self._load_error = None
                            logger.info("TrackNet loaded via ONNX CUDA (device=%d)", self._cuda_device_index)
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
            if onnx_model is not None:
                try:
                    import onnxruntime as ort
                    if "DmlExecutionProvider" in ort.get_available_providers():
                        providers = ["DmlExecutionProvider", "CPUExecutionProvider"]
                        sess = ort.InferenceSession(str(onnx_model), providers=providers)
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
                            self._infer_fn = lambda frames, _s=sess, _n=input_name: self._run_onnx(_s, _n, frames)
                            self._batch_infer_fn = lambda batch, _s=sess, _n=input_name: self._run_onnx_batch(_s, _n, batch)
                            self._backend_name = "onnx_directml"
                            self._load_error = None
                            logger.info("TrackNet loaded via ONNX DirectML (warmup OK)")
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
                            _ov_done.wait(timeout=30)

                            if not _ov_done.is_set():
                                tried.append(f"openvino:{dev}: compile_model タイムアウト（30s）")
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

    # ONNX の ReduceMax/Softmax 中間バッファが batch 数に超線形で増大するため上限を設ける。
    # batch=4 でも OCLink 往復は 28→7 回に削減できる（N=30フレーム時）。
    _MAX_BATCH = 4

    def _predict_frames_batch(self, frames: list[np.ndarray], n_triplets: int) -> list[dict]:
        """トリプレットを _MAX_BATCH 件ずつバッチ推論（OCLink 往復削減 + OOM 防止）。"""
        from backend.tracknet.zone_mapper import heatmap_to_zone

        results = []
        for chunk_start in range(0, n_triplets, self._MAX_BATCH):
            chunk_end = min(chunk_start + self._MAX_BATCH, n_triplets)
            batch_inp = np.concatenate(
                [self._preprocess(frames[i: i + FRAME_STACK]) for i in range(chunk_start, chunk_end)],
                axis=0,
            )  # (chunk, 3, H, W)
            heatmaps = self._batch_infer_fn(batch_inp)  # (chunk, H, W)
            for j, heatmap in enumerate(heatmaps):
                zone, conf, coords = heatmap_to_zone(heatmap)
                results.append({
                    "frame_idx": chunk_start + j + 1,
                    "zone": zone,
                    "confidence": round(conf, 3),
                    "x_norm": round(coords[0], 4) if coords else None,
                    "y_norm": round(coords[1], 4) if coords else None,
                })
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

    def _preprocess(self, frames: list[np.ndarray]) -> np.ndarray:
        import cv2

        channels = []
        for frame in frames:
            resized = cv2.resize(frame, (INPUT_W, INPUT_H))
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
            channels.append(gray)
        stacked = np.stack(channels, axis=0)  # (3, H, W)
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
