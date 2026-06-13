"""Phase 4 ReID Embedder.

OSNet x0_25 ONNX を使った person crop → 512-d embedding。
batch 推論 + GPU/CPU 自動選択。crop 前処理は cv2 で内部実行。

設計書: private_docs/2026-05-27_person_tracking_design.md (Tier 3 ReID Recovery)

既存の `backend/cv/reid.py` (HSV+LBP fallback / 単一 embedding 抽出) とは別レイヤ。
PersonTracker (Phase 4) から呼ばれ、batch 推論の throughput を活かす。

使い方:
    embedder = ReIDEmbedder("backend/models/osnet_x0_25_reid.onnx")
    crops = [frame[y1:y2, x1:x2] for ...]
    feats = embedder.embed_batch(crops)  # (N, 512) L2 正規化済み
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)

# ImageNet normalization
_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(1, 3, 1, 1)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(1, 3, 1, 1)

# モデル入力解像度 (OSNet 標準)
_INPUT_H = 256
_INPUT_W = 128
_FEATURE_DIM = 512

# 固定推論バッチサイズ。embed_batch は入力を常にこの N へ pad/chunk して shape を
# 一定化し、CUDA EP が batch 次元の変動ごとに数秒〜十数秒かけて cuDNN/カーネル探索を
# 再実行する (track 数が増減する frame で毎回 ~12s 停止する) 問題を回避する。env で上書き可。
try:
    _REID_BATCH = max(1, int(os.environ.get("SS_REID_BATCH", "32")))
except (TypeError, ValueError):
    _REID_BATCH = 32


class ReIDEmbedder:
    """OSNet ONNX を使った batch ReID embedder。

    `__init__` で ONNX session を確立 (失敗時は `available=False`)。
    `embed_batch` は (N, 512) を返す。L2 正規化済み。
    モデル未配置でも import エラーにはならず、`embed_batch` は zeros を返す。
    """

    def __init__(
        self,
        model_path: str | Path,
        cuda_device: int = 0,
        prefer_cuda: bool = True,
    ):
        self._model_path = Path(model_path)
        self._cuda_device = cuda_device
        self._prefer_cuda = prefer_cuda
        self._sess = None
        self._input_name: Optional[str] = None
        self._lock = threading.Lock()
        self._provider_used: str = "none"

        if not self._model_path.exists():
            logger.warning("ReIDEmbedder: model not found at %s — embedder disabled", self._model_path)
            return
        try:
            import onnxruntime as ort  # type: ignore
        except ImportError:
            logger.warning("ReIDEmbedder: onnxruntime not installed — embedder disabled")
            return

        providers: list = []
        avail = set(ort.get_available_providers())
        if prefer_cuda and "CUDAExecutionProvider" in avail:
            # embed_batch の入力は (N, 3, 256, 128) で N=crop数が毎フレーム変動する。
            # CUDA EP の cudnn_conv_algo_search は既定 EXHAUSTIVE のため、新しい N を
            # 見るたびに cuDNN アルゴリズム探索を数秒かけて再実行し、track 数が増減する
            # フレームで数秒〜十数秒の停止を起こす。HEURISTIC にすると探索が即時になり、
            # 動的バッチでも停止しない (OSNet のような conv 主体モデルでは推論速度の差は軽微)。
            providers.append((
                "CUDAExecutionProvider",
                {
                    "device_id": cuda_device,
                    "cudnn_conv_algo_search": "HEURISTIC",
                },
            ))
        providers.append("CPUExecutionProvider")

        try:
            sess_opts = ort.SessionOptions()
            sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            self._sess = ort.InferenceSession(str(self._model_path), sess_opts, providers=providers)
            self._input_name = self._sess.get_inputs()[0].name
            self._provider_used = self._sess.get_providers()[0]
            logger.info(
                "ReIDEmbedder loaded: %s provider=%s",
                self._model_path.name, self._provider_used,
            )
        except Exception as exc:
            logger.error("ReIDEmbedder session create failed: %s", exc)
            self._sess = None

    @property
    def available(self) -> bool:
        return self._sess is not None

    @property
    def feature_dim(self) -> int:
        return _FEATURE_DIM

    @property
    def provider(self) -> str:
        return self._provider_used

    @staticmethod
    def _preprocess(crops: list[np.ndarray]) -> np.ndarray:
        """list of BGR uint8 → (N, 3, 256, 128) float32 ImageNet normalized."""
        import cv2  # 遅延 import

        n = len(crops)
        batch = np.empty((n, 3, _INPUT_H, _INPUT_W), dtype=np.float32)
        for i, c in enumerate(crops):
            if c is None or c.size == 0:
                # 退化入力 — 0 埋め (後段で zero-feature が返る)
                batch[i] = 0.0
                continue
            # BGR → RGB resize 256x128
            rgb = cv2.cvtColor(c, cv2.COLOR_BGR2RGB)
            resized = cv2.resize(rgb, (_INPUT_W, _INPUT_H))
            arr = resized.astype(np.float32) / 255.0  # HWC
            arr = arr.transpose(2, 0, 1)  # CHW
            batch[i] = arr
        batch = (batch - _IMAGENET_MEAN) / _IMAGENET_STD
        return batch

    def embed_batch(self, crops: list[np.ndarray]) -> np.ndarray:
        """N 個の person crop (variable size BGR uint8) → (N, 512) L2 正規化 embedding。

        model 未読み込みなら zeros を返す。
        """
        n = len(crops)
        if n == 0:
            return np.zeros((0, _FEATURE_DIM), dtype=np.float32)
        if self._sess is None or self._input_name is None:
            return np.zeros((n, _FEATURE_DIM), dtype=np.float32)

        batch = self._preprocess(crops)  # (n, 3, H, W)
        # 固定バッチサイズで chunk 推論する (動的 N を session に渡さない)。
        # 入力を常に (_REID_BATCH, 3, H, W) に pad/分割すると ONNX Runtime/CUDA EP が
        # 見る shape が一定になり、初回 1 回だけコンパイルして以降は常時高速 (~20ms) になる。
        # OSNet は batch 独立 (推論時 BatchNorm は running 統計) なので pad 行 (zeros) を
        # 足して valid 分のみ slice しても valid 出力は不変。2026-06-13 prod 実測で
        # 動的 N の ~12s/frame 停止が解消することを確認済み。
        bs = _REID_BATCH
        outs: list[np.ndarray] = []
        with self._lock:
            for start in range(0, n, bs):
                chunk = batch[start:start + bs]
                m = chunk.shape[0]
                if m < bs:
                    pad = np.zeros((bs - m, 3, _INPUT_H, _INPUT_W), dtype=chunk.dtype)
                    chunk = np.concatenate([chunk, pad], axis=0)
                try:
                    out = self._sess.run(None, {self._input_name: chunk})[0]
                except Exception as exc:
                    logger.error("ReIDEmbedder inference failed: %s", exc)
                    return np.zeros((n, _FEATURE_DIM), dtype=np.float32)
                outs.append(np.asarray(out, dtype=np.float32).reshape(bs, -1)[:m])
        feats = np.concatenate(outs, axis=0)
        # L2 正規化
        norms = np.linalg.norm(feats, axis=1, keepdims=True)
        norms = np.where(norms > 1e-9, norms, 1.0)
        feats = feats / norms
        return feats


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """L2 正規化済み 1D ベクトル同士の cosine 類似度 (range -1..1)。

    L2 正規化済みを想定するため内積をそのまま返す。
    """
    if a is None or b is None:
        return 0.0
    a = np.asarray(a, dtype=np.float32).ravel()
    b = np.asarray(b, dtype=np.float32).ravel()
    if a.shape != b.shape or a.size == 0:
        return 0.0
    return float(np.dot(a, b))


def cosine_similarity_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """L2 正規化済み (M, D) と (N, D) → (M, N) cosine 類似度 matrix。"""
    if a.size == 0 or b.size == 0:
        return np.zeros((a.shape[0], b.shape[0]), dtype=np.float32)
    return (a @ b.T).astype(np.float32)


# 既定モデル path (PersonTracker から参照)
DEFAULT_REID_MODEL_PATH = os.environ.get(
    "SS_PERSON_REID_MODEL",
    str(Path(__file__).resolve().parent.parent / "models" / "osnet_x0_25_reid.onnx"),
)


def get_default_embedder() -> Optional[ReIDEmbedder]:
    """env path で embedder を 1 度だけ作って返す。失敗/未配置時は None。"""
    global _SINGLETON
    try:
        return _SINGLETON  # type: ignore[name-defined]
    except NameError:
        pass
    try:
        emb = ReIDEmbedder(DEFAULT_REID_MODEL_PATH)
        _SINGLETON = emb if emb.available else None  # type: ignore[name-defined]
    except Exception as exc:
        logger.warning("get_default_embedder failed: %s", exc)
        _SINGLETON = None  # type: ignore[name-defined]
    return _SINGLETON  # type: ignore[name-defined]
