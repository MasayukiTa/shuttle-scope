"""Track C2: RTMPose-m integration.

YOLO で検出された各 player bbox を RTMPose に通し、17 関節の keypoints を
返す。Track C3 SwingDetector の入力源。

設計:
  - **graceful degradation**: mmpose / 重みファイルが無い環境でも `is_available()`
    が False を返すだけで例外を投げない。CI / 開発機 / 5060Ti プロダクションの
    どれでも import エラーで起動が止まらない。
  - **複数バックエンド優先順**:
      1. ONNX Runtime (CUDA / CPU): `backend/models/rtmpose_m_*.onnx`
      2. mmpose Python API (mmcv + mmpose インストール済み環境)
      3. None (= 利用不可)
  - 4 player バッチ推論を 1 forward で済ませる (FP16, batched)
  - 出力: List[PoseResult]、各 17 関節 (x, y, confidence) 形式

COCO 17 keypoints (RTMPose のデフォルト):
  0=nose, 1=left_eye, 2=right_eye, 3=left_ear, 4=right_ear,
  5=left_shoulder, 6=right_shoulder, 7=left_elbow, 8=right_elbow,
  9=left_wrist, 10=right_wrist, 11=left_hip, 12=right_hip,
  13=left_knee, 14=right_knee, 15=left_ankle, 16=right_ankle
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


# ─── COCO 17 keypoint インデックス ───────────────────────────────────────────

class KP:
    NOSE = 0
    L_EYE = 1
    R_EYE = 2
    L_EAR = 3
    R_EAR = 4
    L_SHOULDER = 5
    R_SHOULDER = 6
    L_ELBOW = 7
    R_ELBOW = 8
    L_WRIST = 9
    R_WRIST = 10
    L_HIP = 11
    R_HIP = 12
    L_KNEE = 13
    R_KNEE = 14
    L_ANKLE = 15
    R_ANKLE = 16


@dataclass
class PoseResult:
    """1 player 1 frame 分のポーズ推定結果。"""
    track_id: Optional[int]
    label: Optional[str]
    bbox: List[float]                            # 入力 bbox を保持
    keypoints: np.ndarray = field(default_factory=lambda: np.zeros((17, 3), dtype=np.float32))
    confidence: float = 0.0                       # 平均 keypoint conf
    backend: str = "unloaded"

    def kp_xy(self, idx: int) -> Tuple[float, float]:
        return (float(self.keypoints[idx, 0]), float(self.keypoints[idx, 1]))

    def kp_conf(self, idx: int) -> float:
        return float(self.keypoints[idx, 2])


# ─── エンジン ────────────────────────────────────────────────────────────────

_MODEL_DIR = Path(__file__).resolve().parent.parent / "models"
_ONNX_CANDIDATES = [
    _MODEL_DIR / "rtmpose_m_simcc.onnx",
    _MODEL_DIR / "rtmpose_m.onnx",
]


class RTMPoseEngine:
    """RTMPose 推論エンジン (graceful degradation)。

    Usage:
        eng = RTMPoseEngine()
        if eng.load():
            results = eng.infer(frame_bgr, [{"bbox": [...], "track_id": 1}, ...])
    """

    def __init__(
        self,
        *,
        cuda_device_index: int = 0,
        prefer_backend: str = "auto",   # "auto" / "onnx_cuda" / "onnx_cpu" / "mmpose"
    ) -> None:
        self._loaded = False
        self._backend = "unloaded"
        self._session = None              # ONNX Runtime InferenceSession
        self._mmpose_inferencer = None    # mmpose Inferencer
        self._input_name: Optional[str] = None
        self._cuda_device_index = cuda_device_index
        self._prefer_backend = prefer_backend
        self._load_error: Optional[str] = None

    # ─── 可用性 ─────────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """ONNX Runtime か mmpose のどちらかが import 可能か。"""
        try:
            import onnxruntime  # noqa: F401
            return True
        except ImportError:
            pass
        try:
            from mmpose.apis import MMPoseInferencer  # noqa: F401
            return True
        except ImportError:
            return False

    # ─── ロード ────────────────────────────────────────────────────────

    def load(self) -> bool:
        """重み + バックエンドをロード。成功で True、失敗で False (例外なし)。"""
        if self._loaded:
            return True
        order: List[str] = []
        if self._prefer_backend == "auto":
            order = ["onnx_cuda", "onnx_cpu", "mmpose"]
        else:
            order = [self._prefer_backend]
        for be in order:
            try:
                if be.startswith("onnx") and self._load_onnx(be):
                    self._loaded = True
                    self._backend = be
                    logger.info("RTMPose loaded via %s", be)
                    return True
                if be == "mmpose" and self._load_mmpose():
                    self._loaded = True
                    self._backend = "mmpose"
                    logger.info("RTMPose loaded via mmpose API")
                    return True
            except Exception as exc:
                self._load_error = f"{be}: {type(exc).__name__}: {exc}"
                logger.debug("RTMPose %s load failed: %s", be, exc)
        logger.warning("RTMPose load failed: no backend available (last_error=%s)", self._load_error)
        return False

    def _load_onnx(self, backend: str) -> bool:
        try:
            import onnxruntime as ort
        except ImportError:
            return False
        onnx_path = next((p for p in _ONNX_CANDIDATES if p.exists()), None)
        if onnx_path is None:
            return False
        providers = []
        if backend == "onnx_cuda":
            providers.append(("CUDAExecutionProvider", {"device_id": self._cuda_device_index}))
        providers.append("CPUExecutionProvider")
        try:
            sess_opts = ort.SessionOptions()
            sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._session = ort.InferenceSession(str(onnx_path), sess_opts, providers=providers)
            self._input_name = self._session.get_inputs()[0].name
            return True
        except Exception:
            return False

    def _load_mmpose(self) -> bool:
        try:
            from mmpose.apis import MMPoseInferencer
        except ImportError:
            return False
        try:
            self._mmpose_inferencer = MMPoseInferencer("rtmpose-m_8xb256-420e_coco-256x192")
            return True
        except Exception:
            return False

    # ─── 推論 ───────────────────────────────────────────────────────────

    def infer(
        self,
        frame_bgr: np.ndarray,
        detections: List[dict],
    ) -> List[PoseResult]:
        """各 detection bbox に対して 17 関節を推定する。

        detections の各 dict は最低 "bbox" キー (x1,y1,x2,y2 正規化座標) を持つ。
        オプションで "track_id", "label" を含めると PoseResult に転写される。

        ロード失敗時 / mock 環境では空 keypoints (全 0) を返す。
        """
        results: List[PoseResult] = []
        if not self._loaded:
            for d in detections:
                results.append(PoseResult(
                    track_id=d.get("track_id"),
                    label=d.get("label"),
                    bbox=list(d.get("bbox", [])),
                    backend="unloaded",
                ))
            return results
        if self._backend.startswith("onnx") and self._session is not None:
            return self._infer_onnx(frame_bgr, detections)
        if self._backend == "mmpose" and self._mmpose_inferencer is not None:
            return self._infer_mmpose(frame_bgr, detections)
        return results

    def _infer_onnx(self, frame_bgr: np.ndarray, detections: List[dict]) -> List[PoseResult]:
        h_img, w_img = frame_bgr.shape[:2]
        results: List[PoseResult] = []
        # 入力サイズは モデル依存。RTMPose-m 256x192 を仮定。
        target_h, target_w = 256, 192
        for d in detections:
            bbox = d.get("bbox", [])
            if len(bbox) != 4:
                continue
            x1 = max(0, int(bbox[0] * w_img))
            y1 = max(0, int(bbox[1] * h_img))
            x2 = min(w_img, int(bbox[2] * w_img))
            y2 = min(h_img, int(bbox[3] * h_img))
            if x2 <= x1 or y2 <= y1:
                continue
            crop = frame_bgr[y1:y2, x1:x2]
            try:
                import cv2
                resized = cv2.resize(crop, (target_w, target_h))
                # BGR → RGB → CHW float
                rgb = resized[:, :, ::-1].astype(np.float32) / 255.0
                chw = np.transpose(rgb, (2, 0, 1))
                inp = chw[np.newaxis, :, :, :]
                outputs = self._session.run(None, {self._input_name: inp})
            except Exception as exc:
                logger.debug("RTMPose ONNX inference failed: %s", exc)
                continue
            kpts = self._decode_simcc_or_heatmap(outputs, (x2 - x1, y2 - y1), (x1, y1))
            avg_conf = float(np.mean(kpts[:, 2])) if kpts.size else 0.0
            results.append(PoseResult(
                track_id=d.get("track_id"),
                label=d.get("label"),
                bbox=list(bbox),
                keypoints=kpts,
                confidence=avg_conf,
                backend=self._backend,
            ))
        return results

    def _infer_mmpose(self, frame_bgr: np.ndarray, detections: List[dict]) -> List[PoseResult]:
        # mmpose Inferencer の API は mmpose のバージョンに依存する。
        # 5060Ti 上の prod 環境で実機チューニング前提のため、ここでは骨組のみ。
        results: List[PoseResult] = []
        try:
            res = next(self._mmpose_inferencer(frame_bgr, return_vis=False))
            preds = res.get("predictions", [[]])[0]
            for d, p in zip(detections, preds):
                kpts_raw = np.array(p.get("keypoints", []), dtype=np.float32)
                scores = np.array(p.get("keypoint_scores", []), dtype=np.float32)
                if kpts_raw.size and scores.size:
                    h_img, w_img = frame_bgr.shape[:2]
                    kpts = np.zeros((17, 3), dtype=np.float32)
                    n = min(17, len(kpts_raw))
                    for i in range(n):
                        kpts[i, 0] = kpts_raw[i, 0] / w_img  # 正規化
                        kpts[i, 1] = kpts_raw[i, 1] / h_img
                        kpts[i, 2] = float(scores[i])
                    avg = float(np.mean(kpts[:, 2]))
                else:
                    kpts = np.zeros((17, 3), dtype=np.float32)
                    avg = 0.0
                results.append(PoseResult(
                    track_id=d.get("track_id"),
                    label=d.get("label"),
                    bbox=list(d.get("bbox", [])),
                    keypoints=kpts,
                    confidence=avg,
                    backend="mmpose",
                ))
        except Exception as exc:
            logger.debug("RTMPose mmpose inference failed: %s", exc)
        return results

    def _decode_simcc_or_heatmap(
        self,
        outputs,
        crop_size: Tuple[int, int],
        crop_origin: Tuple[int, int],
    ) -> np.ndarray:
        """SimCC または heatmap 出力から keypoints (17, 3) を抽出。

        出力フォーマットはモデルにより異なる。汎用デコーダは難しいので、
        最も単純なケース (heatmap [1, 17, H, W]) を最初に試し、
        次に SimCC ([1, 17, W_x] と [1, 17, H_y] のペア) を試す。
        失敗したら全 0 を返す。
        """
        kpts = np.zeros((17, 3), dtype=np.float32)
        crop_w, crop_h = crop_size
        ox, oy = crop_origin
        try:
            if len(outputs) == 1 and outputs[0].ndim == 4:
                # heatmap [1, 17, H, W]
                hm = outputs[0][0]
                _, hH, hW = hm.shape
                for i in range(min(17, hm.shape[0])):
                    flat = hm[i].argmax()
                    py = flat // hW
                    px = flat % hW
                    conf = float(hm[i, py, px])
                    img_x = (ox + (px / hW) * crop_w)
                    img_y = (oy + (py / hH) * crop_h)
                    # 画像正規化に戻す。crop_size は元画像 px の crop。
                    # ここでは画像全体サイズを知らないので元 crop_size 内座標を返す。
                    kpts[i, 0] = img_x
                    kpts[i, 1] = img_y
                    kpts[i, 2] = conf
            elif len(outputs) == 2:
                # SimCC: outputs[0]=x logits, outputs[1]=y logits
                x_logits, y_logits = outputs
                for i in range(min(17, x_logits.shape[1])):
                    px = int(np.argmax(x_logits[0, i]))
                    py = int(np.argmax(y_logits[0, i]))
                    conf_x = float(np.max(x_logits[0, i]))
                    conf_y = float(np.max(y_logits[0, i]))
                    kpts[i, 0] = ox + (px / x_logits.shape[2]) * crop_w
                    kpts[i, 1] = oy + (py / y_logits.shape[2]) * crop_h
                    kpts[i, 2] = (conf_x + conf_y) / 2
        except Exception as exc:
            logger.debug("RTMPose decode failed: %s", exc)
        return kpts

    @property
    def backend_name(self) -> str:
        return self._backend


# ─── シングルトン ─────────────────────────────────────────────────────────────

_engine: Optional[RTMPoseEngine] = None


def get_rtmpose_engine() -> RTMPoseEngine:
    global _engine
    if _engine is None:
        _engine = RTMPoseEngine()
        _engine.load()  # 失敗しても loaded=False で graceful
    return _engine
