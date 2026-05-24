"""WASB-SBDT shuttle detection runner.

ONNX Runtime ベースの HRNet バックボーン推論ラッパー。TrackNetV3 と同じ
``predict_frames(frames) -> list[dict]`` インターフェースを実装し、
``cv.factory.get_shuttle_detector()`` から env switch で差し替え可能にする。

EP 優先度:
1. TensorRT (fp16 + engine cache)
2. CUDA
3. CPU
失敗時は ``_gpu_load_error`` に理由を残し、CPU フォールバックで動き続ける。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── 形状定数 ──────────────────────────────────────────────────────────────
FRAME_STACK = 3
INPUT_H = 288
INPUT_W = 512

# ImageNet 正規化 (HRNet pretrain と同じ)
_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(1, 3, 1, 1)
_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(1, 3, 1, 1)

_WEIGHTS_DIR = Path(__file__).resolve().parent / "weights"
_DEFAULT_ONNX = _WEIGHTS_DIR / "wasb_badminton.onnx"
_TRT_CACHE_DIR = _WEIGHTS_DIR / "trt_cache"

_DEFAULT_VISIBLE_THRESHOLD = 0.5


def _resolve_model_path(explicit: Optional[str]) -> Path:
    """SS_WASB_ONNX > 引数 > デフォルト の優先で ONNX パスを解決する。"""
    env_path = os.environ.get("SS_WASB_ONNX", "").strip()
    if env_path:
        return Path(env_path)
    if explicit:
        return Path(explicit)
    return _DEFAULT_ONNX


class WasbInference:
    """WASB-SBDT 推論ラッパー (TrackNetInference 互換 API)。

    Usage:
        eng = WasbInference()
        if eng.load():
            preds = eng.predict_frames(frames_bgr)
    """

    # クラス属性として外部から参照される定数
    FRAME_STACK = FRAME_STACK
    INPUT_H = INPUT_H
    INPUT_W = INPUT_W

    def __init__(
        self,
        backend: str = "auto",
        device: str = "GPU",
        model_path: Optional[str] = None,
        cuda_device_index: int = 0,
        visible_threshold: float = _DEFAULT_VISIBLE_THRESHOLD,
    ) -> None:
        self._backend = backend
        self._device = device
        self._cuda_device_index = cuda_device_index
        self._model_path: Path = _resolve_model_path(model_path)
        self._visible_threshold = visible_threshold

        self._session = None
        self._input_name: Optional[str] = None
        self._backend_name: str = "unloaded"
        self._loaded: bool = False
        self._load_error: Optional[str] = None
        self._gpu_load_error: Optional[str] = None
        self._max_batch_cache: Optional[int] = None

    # ─── 公開 API ────────────────────────────────────────────────────

    def backend_name(self) -> str:
        return self._backend_name

    def get_load_error(self) -> Optional[str]:
        return self._load_error

    @property
    def _max_batch(self) -> int:
        """空き VRAM から推定される最大バッチサイズ。

        TrackNet の ``_vram_based_max_batch`` を再利用 (per_sample_mb=120 で
        WASB の HRNet スタックを概算)。GPU 取得失敗時は 4。CPU 実行時も 4。
        """
        if self._max_batch_cache is not None:
            return self._max_batch_cache
        if self._backend_name.startswith(("trt", "cuda")):
            try:
                from backend.tracknet.inference import _vram_based_max_batch

                self._max_batch_cache = max(
                    1, _vram_based_max_batch(self._cuda_device_index, per_sample_mb=120)
                )
            except Exception:
                self._max_batch_cache = 4
        else:
            self._max_batch_cache = 4
        return self._max_batch_cache

    def load(self) -> bool:
        """ONNX Runtime セッションを初期化する。成功で True / 失敗で False。

        例外は投げない。失敗時は ``_load_error`` / ``_gpu_load_error`` に
        理由を残す。
        """
        if self._loaded:
            return True

        if not self._model_path.exists():
            msg = f"ONNX model not found: {self._model_path}"
            self._load_error = msg
            self._gpu_load_error = msg
            logger.warning("[wasb] %s", msg)
            return False

        try:
            import onnxruntime as ort
        except ImportError as exc:
            self._load_error = f"onnxruntime not installed: {exc}"
            logger.warning("[wasb] %s", self._load_error)
            return False

        # TrackNet 経由で CUDA / TRT の DLL ディレクトリを登録
        try:
            from backend.tracknet.inference import _register_cuda_dll_dirs

            _register_cuda_dll_dirs()
        except Exception:
            pass

        _TRT_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        sess_opts = ort.SessionOptions()
        sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL

        available = set(ort.get_available_providers())
        prefer_gpu = self._backend != "cpu" and str(self._device).upper() != "CPU"

        attempts: list[tuple[str, list]] = []
        if prefer_gpu:
            if "TensorrtExecutionProvider" in available:
                attempts.append((
                    f"trt:{self._cuda_device_index}",
                    [
                        (
                            "TensorrtExecutionProvider",
                            {
                                "device_id": self._cuda_device_index,
                                "trt_fp16_enable": True,
                                "trt_engine_cache_enable": True,
                                "trt_engine_cache_path": str(_TRT_CACHE_DIR),
                            },
                        ),
                        ("CUDAExecutionProvider", {"device_id": self._cuda_device_index}),
                        "CPUExecutionProvider",
                    ],
                ))
            if "CUDAExecutionProvider" in available:
                attempts.append((
                    f"cuda:{self._cuda_device_index}",
                    [
                        ("CUDAExecutionProvider", {"device_id": self._cuda_device_index}),
                        "CPUExecutionProvider",
                    ],
                ))
        attempts.append(("cpu", ["CPUExecutionProvider"]))

        last_exc: Optional[str] = None
        for name, providers in attempts:
            try:
                self._session = ort.InferenceSession(
                    str(self._model_path), sess_opts, providers=providers
                )
                self._input_name = self._session.get_inputs()[0].name
                self._backend_name = name
                self._loaded = True
                if name == "cpu" and prefer_gpu and self._gpu_load_error is None:
                    self._gpu_load_error = last_exc or "GPU EP not selected"
                logger.info(
                    "[wasb] loaded via %s (model=%s)", name, self._model_path.name
                )
                return True
            except Exception as exc:  # pragma: no cover - depends on local EP
                last_exc = f"{name}: {type(exc).__name__}: {exc}"
                logger.debug("[wasb] EP %s failed: %s", name, exc)
                if name != "cpu":
                    self._gpu_load_error = last_exc

        self._load_error = last_exc or "no EP available"
        logger.warning("[wasb] load failed: %s", self._load_error)
        return False

    def predict_frames(self, frames: list[np.ndarray]) -> list[dict]:
        """3 フレームのスライディングウィンドウで推論し、各窓 1 件の dict を返す。

        スキーマ: ``{frame_idx, zone, confidence, x_norm, y_norm, visible}``
        ``frame_idx`` は窓の最終フレーム (1-origin)。
        """
        if not frames:
            return []
        n_triplets = len(frames) - FRAME_STACK + 1
        if n_triplets <= 0:
            return []
        if not self._loaded and not self.load():
            # ロード失敗時は空 / placeholder を返す
            return [
                {
                    "frame_idx": i + 1,
                    "zone": None,
                    "confidence": 0.0,
                    "x_norm": None,
                    "y_norm": None,
                    "visible": False,
                }
                for i in range(n_triplets)
            ]

        from backend.tracknet.zone_mapper import coords_to_zone

        results: list[dict] = []
        batch = max(1, self._max_batch)
        for start in range(0, n_triplets, batch):
            end = min(start + batch, n_triplets)
            batch_inp = self._preprocess_batch(frames, start, end)
            try:
                outputs = self._session.run(None, {self._input_name: batch_inp})
            except Exception as exc:
                logger.warning("[wasb] inference failed (batch %d-%d): %s", start, end, exc)
                for idx in range(start, end):
                    results.append({
                        "frame_idx": idx + 1,
                        "zone": None,
                        "confidence": 0.0,
                        "x_norm": None,
                        "y_norm": None,
                        "visible": False,
                    })
                continue

            heatmaps = self._extract_last_frame_heatmaps(outputs)
            # heatmaps: (B, H, W)
            for i, hm in enumerate(heatmaps):
                conf, x_norm, y_norm = self._peak(hm)
                visible = bool(conf >= self._visible_threshold)
                zone = coords_to_zone(x_norm, y_norm) if visible else None
                results.append({
                    "frame_idx": start + i + 1,
                    "zone": zone,
                    "confidence": round(float(conf), 3),
                    "x_norm": round(float(x_norm), 4) if visible else None,
                    "y_norm": round(float(y_norm), 4) if visible else None,
                    "visible": visible,
                })
        return results

    # ─── 内部 ─────────────────────────────────────────────────────────

    def _preprocess_batch(
        self, frames: list[np.ndarray], start: int, end: int
    ) -> np.ndarray:
        """(B, 9, H, W) float32 を生成する。各 triplet を 3 枚スタック。"""
        import cv2

        batch = []
        for i in range(start, end):
            triplet = []
            for j in range(FRAME_STACK):
                f = frames[i + j]
                resized = cv2.resize(f, (INPUT_W, INPUT_H))
                rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
                chw = np.transpose(rgb, (2, 0, 1))  # (3, H, W)
                triplet.append(chw)
            stacked = np.concatenate(triplet, axis=0)  # (9, H, W)
            batch.append(stacked)
        arr = np.stack(batch, axis=0).astype(np.float32)  # (B, 9, H, W)
        # ImageNet 正規化を 3 ch ずつブロードキャストするため reshape して適用
        b = arr.shape[0]
        arr = arr.reshape(b, FRAME_STACK, 3, INPUT_H, INPUT_W)
        arr = (arr - _MEAN) / _STD
        arr = arr.reshape(b, FRAME_STACK * 3, INPUT_H, INPUT_W)
        return arr

    def _extract_last_frame_heatmaps(self, outputs) -> np.ndarray:
        """モデル出力からスケール 0・最終フレームのヒートマップ (B, H, W) を取り出す。

        WASB はマルチスケール出力で典型的に dict 風ではなく list[np.ndarray] を
        返す。最初の出力 (最大解像度) を採用し、(B, 3, H, W) なら最終 ch を取る。
        """
        # outputs: ONNX Runtime は list[ndarray] を返す
        primary = outputs[0]
        arr = np.asarray(primary)
        if arr.ndim == 4 and arr.shape[1] == FRAME_STACK:
            # (B, 3, H, W) — 最後のフレームを採用
            return arr[:, -1, :, :]
        if arr.ndim == 4 and arr.shape[1] == 1:
            return arr[:, 0, :, :]
        if arr.ndim == 3:
            return arr
        # フォールバック: 任意次元を (B, H, W) に丸める
        return arr.reshape(arr.shape[0], INPUT_H, INPUT_W)

    def _peak(self, heatmap: np.ndarray) -> tuple[float, float, float]:
        """(H, W) ヒートマップから (conf, x_norm, y_norm) を返す。"""
        if heatmap.size == 0:
            return 0.0, 0.0, 0.0
        flat = int(np.argmax(heatmap))
        h, w = heatmap.shape[-2], heatmap.shape[-1]
        py, px = divmod(flat, w)
        conf = float(heatmap[py, px])
        x_norm = (px + 0.5) / w
        y_norm = (py + 0.5) / h
        return conf, x_norm, y_norm
