"""Phase 4 ReIDEmbedder unit test (model 不要)。

OSNet ONNX が無くても embedder 自身は import + ダミー実行可能であること、
cosine similarity ヘルパが期待通りであることを検証する。
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.cv.reid_embedder import (
    ReIDEmbedder,
    cosine_similarity,
    cosine_similarity_matrix,
)


class TestEmbedderUnavailable:
    """ONNX model 未配置時の挙動: available=False、zeros 返却。"""

    def test_unavailable_when_model_missing(self, tmp_path):
        emb = ReIDEmbedder(tmp_path / "does_not_exist.onnx")
        assert emb.available is False
        assert emb.feature_dim == 512

    def test_embed_batch_returns_zeros_when_unavailable(self, tmp_path):
        emb = ReIDEmbedder(tmp_path / "missing.onnx")
        crops = [np.zeros((64, 32, 3), dtype=np.uint8) for _ in range(3)]
        feats = emb.embed_batch(crops)
        assert feats.shape == (3, 512)
        assert np.allclose(feats, 0.0)

    def test_embed_batch_empty(self, tmp_path):
        emb = ReIDEmbedder(tmp_path / "missing.onnx")
        feats = emb.embed_batch([])
        assert feats.shape == (0, 512)


class TestPreprocess:
    """前処理 shape の検証 (model 無しでもクラスメソッドは呼べる)。"""

    def test_preprocess_shape(self):
        crops = [
            np.full((100, 50, 3), 128, dtype=np.uint8),
            np.full((200, 80, 3), 64, dtype=np.uint8),
        ]
        batch = ReIDEmbedder._preprocess(crops)
        assert batch.shape == (2, 3, 256, 128)
        assert batch.dtype == np.float32

    def test_preprocess_handles_empty_crop(self):
        crops = [np.zeros((0, 0, 3), dtype=np.uint8)]
        batch = ReIDEmbedder._preprocess(crops)
        # zero-size crop は 0 埋め (mean/std 引き算で非ゼロにはなる)
        assert batch.shape == (1, 3, 256, 128)


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        assert cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0], dtype=np.float32)
        assert cosine_similarity(a, b) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([-1.0, 0.0], dtype=np.float32)
        assert cosine_similarity(a, b) == pytest.approx(-1.0)

    def test_mismatched_shape_returns_zero(self):
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([1.0, 0.0, 0.0], dtype=np.float32)
        assert cosine_similarity(a, b) == 0.0

    def test_empty_returns_zero(self):
        a = np.zeros(0, dtype=np.float32)
        b = np.zeros(0, dtype=np.float32)
        assert cosine_similarity(a, b) == 0.0

    def test_none_returns_zero(self):
        assert cosine_similarity(None, np.array([1.0])) == 0.0


class TestCosineSimilarityMatrix:
    def test_identity_basis(self):
        a = np.eye(3, dtype=np.float32)
        b = np.eye(3, dtype=np.float32)
        m = cosine_similarity_matrix(a, b)
        # 対角線 = 1.0、それ以外 = 0
        assert m.shape == (3, 3)
        assert np.allclose(np.diag(m), 1.0)
        assert np.allclose(m - np.diag(np.diag(m)), 0.0)

    def test_empty(self):
        a = np.zeros((0, 5), dtype=np.float32)
        b = np.zeros((3, 5), dtype=np.float32)
        m = cosine_similarity_matrix(a, b)
        assert m.shape == (0, 3)
