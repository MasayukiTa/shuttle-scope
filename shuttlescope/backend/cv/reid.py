"""選手再同定 (Re-ID) 特徴量抽出

優先順:
  1. OSNet ONNX — `backend/models/osnet_x0_25.onnx` があれば 512-d embedding を返す
  2. フォールバック: HSV 3D hist (8×8×4=256) + LBP uniform (59) = 315-d
     → Hue のみの 12-bin と比べて色チャネル・テクスチャを保持、観客識別力が高い

いずれも L2 正規化済み float list を返す。cos 類似度でマッチング可。

使い方:
    emb = extract_embedding(frame_bgr, bbox_norm, fw, fh)  # list[float] 長さ 512 or 315
    sim = cos_sim(emb_a, emb_b)  # 0.0-1.0
"""

from __future__ import annotations

import logging
import math
import threading
from pathlib import Path
from typing import Optional

import numpy as np
import cv2

logger = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
OSNET_ONNX = MODELS_DIR / "osnet_x0_25.onnx"

# 観客/審判棄却用の類似度しきい値（cos sim）
# 本値未満は「別人」と見なす。0.65 は経験値（ユニ色は似ても観客は必ず下回る設定）
MIN_APP_SIM = 0.60

_lock = threading.Lock()
_onnx_sess = None
_onnx_input_name: Optional[str] = None
_onnx_load_tried = False


def _try_load_onnx() -> None:
    """OSNet ONNX を遅延ロード。存在しなければ静かに諦める。"""
    global _onnx_sess, _onnx_input_name, _onnx_load_tried
    if _onnx_load_tried:
        return
    _onnx_load_tried = True
    if not OSNET_ONNX.exists():
        logger.info("ReID: OSNet ONNX not found at %s, using HSV+LBP fallback", OSNET_ONNX)
        return
    try:
        import onnxruntime as ort  # type: ignore
        providers = ["CPUExecutionProvider"]
        sess = ort.InferenceSession(str(OSNET_ONNX), providers=providers)
        _onnx_sess = sess
        _onnx_input_name = sess.get_inputs()[0].name
        logger.info("ReID: OSNet ONNX loaded from %s", OSNET_ONNX)
    except Exception as e:
        logger.warning("ReID: OSNet ONNX load failed (%s), using HSV+LBP fallback", e)


def _torso_crop(frame_bgr: np.ndarray, bbox_norm, fw: int, fh: int) -> Optional[np.ndarray]:
    """bbox の胴体領域（高さ 15%-75%、幅中央 80%）を切り出し。足元背景・頭部肌色を除外。"""
    try:
        x1 = max(0, int(bbox_norm[0] * fw))
        y1 = max(0, int(bbox_norm[1] * fh))
        x2 = min(fw, int(bbox_norm[2] * fw))
        y2 = min(fh, int(bbox_norm[3] * fh))
        if x2 - x1 < 6 or y2 - y1 < 12:
            return None
        bw = x2 - x1
        bh = y2 - y1
        tx1 = x1 + int(bw * 0.10)
        tx2 = x2 - int(bw * 0.10)
        ty1 = y1 + int(bh * 0.15)
        ty2 = y1 + int(bh * 0.75)
        crop = frame_bgr[ty1:ty2, tx1:tx2]
        if crop.size == 0:
            return None
        return crop
    except Exception:
        return None


def _lbp_hist(gray: np.ndarray) -> np.ndarray:
    """8近傍 uniform LBP ヒスト（59 ビン）。回転不変ではないが軽量で服のテクスチャに効く。"""
    # uniform LBP 実装（scikit-image 依存を避けるため numpy で手書き）
    # 8近傍コードは 256 通り、そのうち uniform(2回以下のビット遷移) は 58 + 1(non-uniform bucket) = 59
    # しきい値: 中央画素との比較
    g = gray.astype(np.int16)
    h, w = g.shape
    if h < 3 or w < 3:
        return np.zeros(59, dtype=np.float32)
    c = g[1:-1, 1:-1]
    # 8近傍（時計回り）
    p = [
        g[0:-2, 0:-2], g[0:-2, 1:-1], g[0:-2, 2:],
        g[1:-1, 2:], g[2:, 2:], g[2:, 1:-1],
        g[2:, 0:-2], g[1:-1, 0:-2],
    ]
    code = np.zeros_like(c, dtype=np.uint8)
    for i, pi in enumerate(p):
        code |= ((pi >= c).astype(np.uint8) << i)
    # uniform 判定: ビット遷移回数 ≤ 2
    # 事前計算テーブル
    if not hasattr(_lbp_hist, "_lut"):
        lut = np.zeros(256, dtype=np.uint8)
        next_u = 0
        mapping = {}
        for v in range(256):
            # ビット遷移数を数える（円環）
            bits = [(v >> i) & 1 for i in range(8)]
            trans = sum(1 for i in range(8) if bits[i] != bits[(i + 1) % 8])
            if trans <= 2:
                if v not in mapping:
                    mapping[v] = next_u
                    next_u += 1
                lut[v] = mapping[v]
            else:
                lut[v] = 58  # non-uniform bucket
        _lbp_hist._lut = lut  # type: ignore
    mapped = _lbp_hist._lut[code]  # type: ignore
    hist, _ = np.histogram(mapped, bins=59, range=(0, 59))
    s = hist.sum()
    if s <= 0:
        return np.zeros(59, dtype=np.float32)
    return (hist.astype(np.float32) / s)


def _hsv3d_hist(crop_bgr: np.ndarray, h_bins: int = 16, s_bins: int = 8, v_bins: int = 4) -> np.ndarray:
    """HSV 3D ヒスト（既定 16×8×4 = 512 bins）。L1 正規化済み。低彩度 + 極端な明度は除外。"""
    hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
    # マスク: S > 30（肌色低彩度除外は難しいので控えめ）, V 15-240（黒/白飛び除外）
    mask = ((hsv[..., 1] > 30) & (hsv[..., 2] > 15) & (hsv[..., 2] < 240)).astype(np.uint8)
    if mask.sum() < 30:
        return np.zeros(h_bins * s_bins * v_bins, dtype=np.float32)
    hist = cv2.calcHist([hsv], [0, 1, 2], mask, [h_bins, s_bins, v_bins], [0, 180, 0, 256, 0, 256])
    hist = hist.flatten().astype(np.float32)
    s = hist.sum()
    if s <= 0:
        return np.zeros_like(hist)
    return hist / s


def _fallback_embedding(frame_bgr: np.ndarray, bbox_norm, fw: int, fh: int) -> list[float]:
    """HSV 3D hist + LBP 連結 → L2 正規化。ONNX 未導入時のフォールバック。"""
    crop = _torso_crop(frame_bgr, bbox_norm, fw, fh)
    if crop is None:
        return []
    try:
        hsv_vec = _hsv3d_hist(crop)
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        lbp_vec = _lbp_hist(gray)
        # HSV:LBP = 1:0.3（色が主、テクスチャ補助）
        feat = np.concatenate([hsv_vec, 0.3 * lbp_vec]).astype(np.float32)
        n = np.linalg.norm(feat)
        if n > 0:
            feat = feat / n
        return feat.tolist()
    except Exception as e:
        logger.debug("reid fallback failed: %s", e)
        return []


def _onnx_embedding(frame_bgr: np.ndarray, bbox_norm, fw: int, fh: int) -> list[float]:
    """OSNet ONNX 推論。入力 256x128 BGR→RGB Normalize。出力 512-d L2 正規化。"""
    if _onnx_sess is None or _onnx_input_name is None:
        return []
    crop = _torso_crop(frame_bgr, bbox_norm, fw, fh)
    if crop is None:
        return []
    try:
        # BGR → RGB, resize 256x128, normalize ImageNet mean/std
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        resized = cv2.resize(rgb, (128, 256))
        arr = resized.astype(np.float32) / 255.0
        mean = np.array([0.485, 0.456, 0.406], dtype=np.float32)
        std = np.array([0.229, 0.224, 0.225], dtype=np.float32)
        arr = (arr - mean) / std
        arr = arr.transpose(2, 0, 1)[None, ...]  # NCHW
        with _lock:
            out = _onnx_sess.run(None, {_onnx_input_name: arr})[0]
        feat = out.flatten().astype(np.float32)
        n = np.linalg.norm(feat)
        if n > 0:
            feat = feat / n
        return feat.tolist()
    except Exception as e:
        logger.debug("reid onnx failed: %s", e)
        return []


def extract_embedding(frame_bgr: np.ndarray, bbox_norm, fw: int, fh: int) -> list[float]:
    """Re-ID 埋め込み抽出。ONNX があれば使い、無ければフォールバック。"""
    _try_load_onnx()
    if _onnx_sess is not None:
        emb = _onnx_embedding(frame_bgr, bbox_norm, fw, fh)
        if emb:
            return emb
    return _fallback_embedding(frame_bgr, bbox_norm, fw, fh)


def cos_sim(a, b) -> float:
    """L2 正規化済みベクトル同士の cos sim。空なら 0.5（中立）。"""
    if not a or not b:
        return 0.5
    la = len(a)
    lb = len(b)
    if la != lb:
        return 0.5
    dot = 0.0
    for i in range(la):
        dot += a[i] * b[i]
    return max(0.0, min(1.0, (dot + 1.0) / 2.0 if dot < 0 else dot))


def cos_sim_gallery(gallery, q) -> float:
    """ギャラリー（list of embedding）と q の cos sim の最大値。空なら 0.5。"""
    if not gallery or not q:
        return 0.5
    # 単一 embedding（後方互換: 数値リスト）
    if isinstance(gallery[0], (int, float)):
        return cos_sim(gallery, q)  # type: ignore[arg-type]
    best = 0.0
    for g in gallery:
        s = cos_sim(g, q)
        if s > best:
            best = s
    return best
