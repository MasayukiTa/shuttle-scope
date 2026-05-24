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
                # Build TRT engine for the actual max-batch at load time so
                # later predict_frames does not pay engine-rebuild latency.
                if name.startswith("trt") or name.startswith("cuda"):
                    self._warmup_gpu()
                return True
            except Exception as exc:  # pragma: no cover - depends on local EP
                last_exc = f"{name}: {type(exc).__name__}: {exc}"
                logger.debug("[wasb] EP %s failed: %s", name, exc)
                if name != "cpu":
                    self._gpu_load_error = last_exc

        self._load_error = last_exc or "no EP available"
        logger.warning("[wasb] load failed: %s", self._load_error)
        return False

    def run(self, video_path: str, fps: float = 30.0) -> list:
        """TrackNetInferencer 互換アダプタ。動画を読み込み ``List[ShuttleSample]`` を返す。

        ``backend.cv.factory.get_shuttle_detector()`` 経由で production の
        ``video_pipeline`` / ``tracknet_runner`` / ``benchmark.runner`` から
        TrackNet と同じ呼び出し方で差し替え可能にするためのアダプタ。

        - ``predict_frames`` の dict 出力を ``ShuttleSample`` に変換する。
        - ``visible=False`` の窓は ``confidence=0.0`` で素通しする
          (TrackNet 側もスキップせず 0 conf を返す挙動に合わせる)。
        - ``ts_sec`` は ``frame_idx / fps`` で算出 (動画 fps 未取得時は 30 fallback)。
        """
        import cv2  # 遅延 import: cv2 は重いので必要時のみ

        from backend.cv.base import ShuttleSample

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            logger.warning("[wasb.run] cannot open video: %s", video_path)
            return []
        try:
            cap_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            if cap_fps > 0:
                fps = cap_fps
            frames: list[np.ndarray] = []
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                frames.append(frame)
        finally:
            cap.release()

        if not frames:
            return []

        preds = self.predict_frames(frames)
        samples = []
        # predict_frames の frame_idx は 1-origin (窓の最終フレーム)
        # 元フレーム index は frame_idx + FRAME_STACK - 2
        for p in preds:
            f_idx_orig = int(p["frame_idx"]) + FRAME_STACK - 2
            x_norm = p.get("x_norm")
            y_norm = p.get("y_norm")
            # ShuttleSample は px 座標を想定 (TrackNet と同様)。
            # WASB は normalized で返すので元動画解像度を掛ける。
            if x_norm is None or y_norm is None:
                x_px = 0.0
                y_px = 0.0
            else:
                H0, W0 = frames[0].shape[:2]
                x_px = float(x_norm) * float(W0)
                y_px = float(y_norm) * float(H0)
            samples.append(ShuttleSample(
                frame=f_idx_orig,
                ts_sec=float(f_idx_orig) / fps if fps > 0 else 0.0,
                x=x_px,
                y=y_px,
                confidence=float(p.get("confidence", 0.0)),
            ))
        return samples

    def predict_frames(self, frames: list[np.ndarray]) -> list[dict]:
        """3 フレームのスライディングウィンドウで推論し、各窓 1 件の dict を返す。

        スキーマ: ``{frame_idx, zone, confidence, x_norm, y_norm, visible}``
        ``frame_idx`` は窓の最終フレーム (1-origin)。

        最適化:
          - 全フレームを一度だけ前処理 (重複 resize 排除)
          - torch + IOBinding で GPU 上 zero-copy 推論 (CUDA EP 時のみ)
          - chunk_size=128 frame で VRAM 制御
          - CUDA EP 不可時は従来の numpy session.run にフォールバック
        """
        if not frames:
            return []
        n_triplets = len(frames) - FRAME_STACK + 1
        if n_triplets <= 0:
            return []
        if not self._loaded and not self.load():
            return [
                {
                    "frame_idx": i + 1, "zone": None, "confidence": 0.0,
                    "x_norm": None, "y_norm": None, "visible": False,
                }
                for i in range(n_triplets)
            ]

        # GPU 最適化パス
        if self._can_use_gpu_fastpath():
            try:
                return self._predict_frames_gpu(frames)
            except Exception as exc:
                logger.warning("[wasb] GPU fastpath failed, falling back to CPU: %s", exc)

        # CPU フォールバック (旧実装と同等)
        return self._predict_frames_cpu(frames)

    def _warmup_gpu(self, iters: int = 3) -> None:
        """Trigger TRT engine build for _max_batch and a smaller fallback batch
        so the first real predict_frames call doesn't pay engine compile cost.
        Silent on failure (warmup is opportunistic)."""
        try:
            import torch
            if not torch.cuda.is_available():
                return
            device = f"cuda:{self._cuda_device_index}"
            sizes = sorted(set([max(1, self._max_batch), 1]))
            for bsz in sizes:
                x = torch.randn(bsz, FRAME_STACK * 3, INPUT_H, INPUT_W,
                                dtype=torch.float32, device=device).contiguous()
                out = torch.empty(bsz, FRAME_STACK, INPUT_H, INPUT_W,
                                   dtype=torch.float32, device=device)
                io = self._session.io_binding()
                io.bind_input(name=self._input_name, device_type="cuda",
                              device_id=self._cuda_device_index,
                              element_type=np.float32, shape=tuple(x.shape),
                              buffer_ptr=x.data_ptr())
                io.bind_output(name=self._session.get_outputs()[0].name,
                               device_type="cuda",
                               device_id=self._cuda_device_index,
                               element_type=np.float32, shape=tuple(out.shape),
                               buffer_ptr=out.data_ptr())
                for _ in range(iters):
                    self._session.run_with_iobinding(io)
                del x, out
            torch.cuda.synchronize()
            logger.info("[wasb] GPU warmup ok (batches=%s)", sizes)
        except Exception as exc:
            logger.debug("[wasb] warmup skipped: %s", exc)

    def _can_use_gpu_fastpath(self) -> bool:
        if self._session is None:
            return False
        get_providers = getattr(self._session, "get_providers", None)
        if not callable(get_providers):
            return False
        try:
            provs = get_providers()
        except Exception:
            return False
        if not any("CUDA" in p or "Tensorrt" in p for p in provs):
            return False
        if not hasattr(self._session, "io_binding") or not hasattr(self._session, "run_with_iobinding"):
            return False
        try:
            import torch
            if not torch.cuda.is_available():
                return False
        except ImportError:
            return False
        return True

    def _predict_frames_gpu(self, frames: list[np.ndarray]) -> list[dict]:
        """GPU 最適化パス: torch + IOBinding。"""
        import torch
        from backend.tracknet.zone_mapper import coords_to_zone

        device = f"cuda:{self._cuda_device_index}"
        mean_gpu = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 3, 1, 1)
        std_gpu = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 3, 1, 1)
        batch = max(1, self._max_batch)
        chunk_size = max(batch + FRAME_STACK - 1, 128)
        overlap = FRAME_STACK - 1

        n_triplets = len(frames) - FRAME_STACK + 1
        results: list[dict] = []
        produced = 0
        start = 0
        while produced < n_triplets and start < len(frames):
            chunk = frames[start:start + chunk_size]
            if len(chunk) < FRAME_STACK:
                break

            # 全 frame 1 度だけ前処理 (numpy → uint8 GPU → resize+normalize)
            arr = np.stack(chunk, axis=0)  # (N, H0, W0, 3) uint8
            t = torch.from_numpy(arr).to(device, non_blocking=True)
            t = t.permute(0, 3, 1, 2).contiguous().float() / 255.0
            t = t[:, [2, 1, 0], :, :]  # BGR → RGB
            t = torch.nn.functional.interpolate(t, size=(INPUT_H, INPUT_W),
                                                 mode="bilinear", align_corners=False)
            t = (t - mean_gpu) / std_gpu  # (N, 3, H, W)

            # triplet build via concat along channel
            n_trip_chunk = t.shape[0] - FRAME_STACK + 1
            triplets = torch.cat(
                [t[0:n_trip_chunk], t[1:n_trip_chunk + 1], t[2:n_trip_chunk + 2]],
                dim=1,
            )  # (n_trip, 9, H, W)

            # batched IOBinding inference
            for b0 in range(0, n_trip_chunk, batch):
                chunk_inp = triplets[b0:b0 + batch].contiguous()
                bsz = chunk_inp.shape[0]
                out_gpu = torch.empty((bsz, FRAME_STACK, INPUT_H, INPUT_W),
                                      dtype=torch.float32, device=device)
                io = self._session.io_binding()
                io.bind_input(
                    name=self._input_name, device_type="cuda",
                    device_id=self._cuda_device_index, element_type=np.float32,
                    shape=tuple(chunk_inp.shape), buffer_ptr=chunk_inp.data_ptr(),
                )
                io.bind_output(
                    name=self._session.get_outputs()[0].name, device_type="cuda",
                    device_id=self._cuda_device_index, element_type=np.float32,
                    shape=tuple(out_gpu.shape), buffer_ptr=out_gpu.data_ptr(),
                )
                self._session.run_with_iobinding(io)

                # GPU postprocess: take last-frame heatmap, sigmoid → argmax
                # WASB outputs raw logits; sigmoid maps to [0,1] probability so
                # the visible_threshold reads as "P(shuttle) >= 0.5" intuitively.
                last = torch.sigmoid(out_gpu[:, -1, :, :])  # (bsz, H, W) in [0,1]
                flat = last.view(bsz, -1)
                max_vals, max_idx = flat.max(dim=1)
                ys = (max_idx // INPUT_W).cpu().numpy()
                xs = (max_idx % INPUT_W).cpu().numpy()
                confs = max_vals.cpu().numpy()
                for i in range(bsz):
                    conf = float(confs[i])
                    visible = conf >= self._visible_threshold
                    x_norm = float(xs[i]) / INPUT_W
                    y_norm = float(ys[i]) / INPUT_H
                    zone = coords_to_zone(x_norm, y_norm) if visible else None
                    results.append({
                        "frame_idx": produced + 1,
                        "zone": zone,
                        "confidence": round(conf, 3),
                        "x_norm": round(x_norm, 4) if visible else None,
                        "y_norm": round(y_norm, 4) if visible else None,
                        "visible": visible,
                    })
                    produced += 1
            del t, triplets

            if start + chunk_size >= len(frames):
                break
            start += chunk_size - overlap

        # Temporal hysteresis smoothing: if a frame is just below threshold
        # but is flanked by confident detections, mark it visible too. Helps
        # bridge brief shuttle occlusions / sub-pixel motion blur frames.
        self._smooth_temporal(results)

        # Optional 2nd pass: track-then-detect ROI re-inference.
        # Default OFF — the gain measured on muroya doubles was only +0.9pt
        # detection rate at 17x speed cost (most uncertain frames don't
        # actually contain the shuttle, so ROI re-inference burns compute
        # without finding new detections). Kept as opt-in for offline /
        # accuracy-critical use cases via SS_WASB_ROI_REFINE=1.
        if os.environ.get("SS_WASB_ROI_REFINE", "0") not in ("0", "false", ""):
            try:
                self._refine_uncertain_via_roi(frames, results)
            except Exception as exc:
                logger.debug("[wasb] ROI refinement failed (continuing): %s", exc)

        return results

    def _refine_uncertain_via_roi(
        self,
        frames: list[np.ndarray],
        results: list[dict],
        roi_w_norm: float = 0.20,   # 20% of frame width = ~384px on 1920p
        roi_h_norm: float = 0.20,
        soft_floor: float = 0.4,    # tightened: only refine borderline (was 0.2)
        confident: float = 0.6,     # seed positions must come from frames with conf >= this
        roi_threshold: float = 0.4, # threshold for ROI re-inference (relaxed)
        max_seed_age: int = 5,      # tightened (was 15): only seed from recent
        max_batch: int = 32,        # larger batch (was 16)
    ) -> int:
        """Track-then-detect 2nd pass.

        For each frame in results that is uncertain (soft_floor <= conf <
        visible_threshold), find the nearest confident detection within
        max_seed_age frames, crop a ROI of size (roi_w, roi_h) of the
        frame around that seed position, build a 3-frame triplet from the
        same ROI on i-1/i/i+1, push through WASB at model-native 512x288.
        If the re-inferred peak passes roi_threshold, mark visible and
        update coordinates.

        Returns number of frames promoted.
        """
        try:
            import torch  # noqa
        except ImportError:
            return 0
        from backend.tracknet.zone_mapper import coords_to_zone
        import torch

        n = len(results)
        if n < 3:
            return 0
        H_full, W_full = frames[0].shape[:2] if frames else (0, 0)
        if H_full == 0:
            return 0

        # Build seed map: index → (x_norm, y_norm) from the nearest confident
        # frame to the left and to the right (within max_seed_age).
        confident_idx_x_y: list[tuple[int, float, float]] = []
        for i, r in enumerate(results):
            if r["visible"] and r.get("x_norm") is not None and r["confidence"] >= confident:
                confident_idx_x_y.append((i, r["x_norm"], r["y_norm"]))
        if not confident_idx_x_y:
            return 0
        conf_idxs = [c[0] for c in confident_idx_x_y]

        # Helper: nearest confident index, linear scan (n small enough)
        def nearest_conf(i: int) -> tuple[int, float, float] | None:
            best = None
            best_d = max_seed_age + 1
            for ci, cx, cy in confident_idx_x_y:
                d = abs(ci - i)
                if d < best_d:
                    best_d = d
                    best = (ci, cx, cy)
            if best is None or best_d > max_seed_age:
                return None
            return best

        # Collect candidates and their seed positions
        candidates = []  # list of (i, x_norm, y_norm)
        for i, r in enumerate(results):
            if r["visible"]:
                continue
            if r["confidence"] < soft_floor:
                continue
            # need triplet: i-1, i, i+1 must all map to a valid frame.
            # results[i] corresponds to frame index i+FRAME_STACK-1 in the
            # original frame list (since we prepend FRAME_STACK-1 frames per
            # sliding window). Equivalent: frames_idx = i + FRAME_STACK - 1.
            # We need frames at fi-1, fi, fi+1 with fi = i + FRAME_STACK - 1.
            fi = i + FRAME_STACK - 1
            if fi - 1 < 0 or fi + 1 >= len(frames):
                continue
            seed = nearest_conf(i)
            if seed is None:
                continue
            _, cx, cy = seed
            candidates.append((i, cx, cy, fi))

        if not candidates:
            return 0

        device = f"cuda:{self._cuda_device_index}"
        mean_gpu = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 3, 1, 1)
        std_gpu = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 3, 1, 1)

        promoted = 0
        roi_pw = int(roi_w_norm * W_full)
        roi_ph = int(roi_h_norm * H_full)

        # Process in batches
        for b0 in range(0, len(candidates), max_batch):
            batch = candidates[b0:b0 + max_batch]
            bsz = len(batch)
            # Build (bsz, 9, INPUT_H, INPUT_W) input from ROI crops
            crops_np = np.empty((bsz * 3, roi_ph, roi_pw, 3), dtype=np.uint8)
            roi_boxes = []  # (x0, y0, x1, y1) per candidate in full-frame coords
            for k, (i, cx, cy, fi) in enumerate(batch):
                # ROI box in full coords, clipped to frame
                cx_pix = int(cx * W_full); cy_pix = int(cy * H_full)
                x0 = max(0, min(W_full - roi_pw, cx_pix - roi_pw // 2))
                y0 = max(0, min(H_full - roi_ph, cy_pix - roi_ph // 2))
                x1 = x0 + roi_pw; y1 = y0 + roi_ph
                roi_boxes.append((x0, y0, x1, y1))
                for j, fr_idx in enumerate((fi - 1, fi, fi + 1)):
                    crops_np[k * 3 + j] = frames[fr_idx][y0:y1, x0:x1]
            # Upload to GPU and preprocess
            t = torch.from_numpy(crops_np).to(device, non_blocking=True)
            t = t.permute(0, 3, 1, 2).contiguous().float() / 255.0
            t = t[:, [2, 1, 0], :, :]
            t = torch.nn.functional.interpolate(t, size=(INPUT_H, INPUT_W),
                                                  mode="bilinear", align_corners=False)
            t = (t - mean_gpu) / std_gpu
            # Reshape (bsz*3, 3, H, W) → (bsz, 9, H, W) (stack 3 frames as channels)
            t = t.view(bsz, 3, 3, INPUT_H, INPUT_W).reshape(bsz, 9, INPUT_H, INPUT_W).contiguous()
            # Run inference via IOBinding
            y = torch.empty(bsz, FRAME_STACK, INPUT_H, INPUT_W,
                             dtype=torch.float32, device=device)
            io = self._session.io_binding()
            io.bind_input(name=self._input_name, device_type="cuda",
                          device_id=self._cuda_device_index,
                          element_type=np.float32, shape=tuple(t.shape),
                          buffer_ptr=t.data_ptr())
            io.bind_output(name=self._session.get_outputs()[0].name,
                           device_type="cuda", device_id=self._cuda_device_index,
                           element_type=np.float32, shape=tuple(y.shape),
                           buffer_ptr=y.data_ptr())
            self._session.run_with_iobinding(io)
            # Postprocess: sigmoid last-frame heatmap
            last = torch.sigmoid(y[:, -1, :, :])
            flat = last.view(bsz, -1)
            max_vals, max_idx = flat.max(dim=1)
            ys = (max_idx // INPUT_W).cpu().numpy()
            xs = (max_idx % INPUT_W).cpu().numpy()
            confs = max_vals.cpu().numpy()
            for k, (i, _cx, _cy, _fi) in enumerate(batch):
                conf_new = float(confs[k])
                if conf_new < roi_threshold:
                    continue
                x0, y0, x1, y1 = roi_boxes[k]
                # Map ROI-internal pixel back to full-frame normalized coords
                px = x0 + (xs[k] + 0.5) * (x1 - x0) / INPUT_W
                py = y0 + (ys[k] + 0.5) * (y1 - y0) / INPUT_H
                x_norm = float(px) / W_full
                y_norm = float(py) / H_full
                # Only update if new conf > original
                if conf_new > results[i]["confidence"]:
                    results[i]["confidence"] = round(conf_new, 3)
                    results[i]["x_norm"] = round(x_norm, 4)
                    results[i]["y_norm"] = round(y_norm, 4)
                    results[i]["visible"] = True
                    results[i]["zone"] = coords_to_zone(x_norm, y_norm)
                    promoted += 1
            del t, y

        if promoted:
            logger.info("[wasb] ROI refinement promoted %d/%d uncertain frames",
                         promoted, len(candidates))
        return promoted

    def _smooth_temporal(self, results: list[dict], soft_floor: float = 0.3,
                          window: int = 1) -> None:
        """In-place hysteresis: a frame within `window` of two confident
        neighbours and with conf >= soft_floor is promoted to visible.
        Does nothing if results is shorter than 2*window+1."""
        if len(results) < 2 * window + 1:
            return
        from backend.tracknet.zone_mapper import coords_to_zone
        thresh = self._visible_threshold
        n = len(results)
        for i in range(window, n - window):
            r = results[i]
            if r["visible"]:
                continue
            if r["confidence"] < soft_floor:
                continue
            # require both sides confident within window
            left_ok = any(results[i - k]["visible"] for k in range(1, window + 1))
            right_ok = any(results[i + k]["visible"] for k in range(1, window + 1))
            if not (left_ok and right_ok):
                continue
            # interpolate position from nearest visible neighbours
            left = next((results[i - k] for k in range(1, window + 1) if results[i - k]["visible"]), None)
            right = next((results[i + k] for k in range(1, window + 1) if results[i + k]["visible"]), None)
            if left is None or right is None:
                continue
            x_norm = (left["x_norm"] + right["x_norm"]) / 2
            y_norm = (left["y_norm"] + right["y_norm"]) / 2
            r["visible"] = True
            r["x_norm"] = round(x_norm, 4)
            r["y_norm"] = round(y_norm, 4)
            r["zone"] = coords_to_zone(x_norm, y_norm)

    def _predict_frames_cpu(self, frames: list[np.ndarray]) -> list[dict]:
        """非 GPU バックエンド用フォールバック (元の実装)。"""
        from backend.tracknet.zone_mapper import coords_to_zone

        n_triplets = len(frames) - FRAME_STACK + 1
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
                        "frame_idx": idx + 1, "zone": None, "confidence": 0.0,
                        "x_norm": None, "y_norm": None, "visible": False,
                    })
                continue

            heatmaps = self._extract_last_frame_heatmaps(outputs)
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
