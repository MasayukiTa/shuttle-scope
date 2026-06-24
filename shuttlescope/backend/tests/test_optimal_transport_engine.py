"""
test_optimal_transport_engine.py — optimal_transport_engine の合成ユニットテスト

DB 不使用。numpy のみ。
"""
import numpy as np
import pytest

from backend.analysis.optimal_transport_engine import (
    sinkhorn_distance,
    pairwise_distance_matrix,
    classical_mds,
)


# ---------------------------------------------------------------------------
# 共通フィクスチャ
# ---------------------------------------------------------------------------

def _uniform_cost(K: int) -> np.ndarray:
    """K×K コスト行列: 非対角 = 1、対角 = 0 の単純コスト"""
    C = np.ones((K, K))
    np.fill_diagonal(C, 0.0)
    return C


def _grid_cost(K: int) -> np.ndarray:
    """1D グリッドのユークリッド距離行列 (0, 1, ..., K-1) を [0,1] 正規化"""
    idx = np.arange(K, dtype=float)
    C = np.abs(idx[:, None] - idx[None, :])
    if C.max() > 0:
        C /= C.max()
    return C


# ---------------------------------------------------------------------------
# sinkhorn_distance テスト
# ---------------------------------------------------------------------------

class TestSinkhornDistance:

    def test_identical_histograms_near_zero(self):
        """同一分布同士の OT 距離はほぼ 0"""
        K = 9
        p = np.ones(K) / K
        C = _grid_cost(K)
        d = sinkhorn_distance(p, p, C, reg=0.05, iters=300)
        assert d >= 0.0, "距離は非負でなければならない"
        assert d < 1e-3, f"同一分布の距離が {d:.6f} > 1e-3 と大きすぎる"

    def test_far_apart_larger_than_near(self):
        """遠いゾーンに集中した分布ペアの距離 > 近いゾーンの分布ペア"""
        K = 9
        C = _grid_cost(K)

        eps = 1e-8
        # 近いペア: ゾーン 0 と ゾーン 1
        p_near = np.full(K, eps); p_near[0] = 1.0
        q_near = np.full(K, eps); q_near[1] = 1.0
        p_near /= p_near.sum(); q_near /= q_near.sum()

        # 遠いペア: ゾーン 0 と ゾーン 8
        p_far = np.full(K, eps); p_far[0] = 1.0
        q_far = np.full(K, eps); q_far[8] = 1.0
        p_far /= p_far.sum(); q_far /= q_far.sum()

        d_near = sinkhorn_distance(p_near, q_near, C)
        d_far  = sinkhorn_distance(p_far,  q_far,  C)

        assert d_far > d_near, (
            f"遠いペア距離 ({d_far:.6f}) が近いペア ({d_near:.6f}) 以下になっている"
        )

    def test_symmetry(self):
        """Sinkhorn 距離は対称: d(p,q) ≈ d(q,p)"""
        K = 9
        rng = np.random.default_rng(seed=42)
        p = rng.dirichlet(np.ones(K))
        q = rng.dirichlet(np.ones(K))
        C = _grid_cost(K)

        d_pq = sinkhorn_distance(p, q, C)
        d_qp = sinkhorn_distance(q, p, C)

        assert abs(d_pq - d_qp) < 1e-6, (
            f"非対称: d(p,q)={d_pq:.8f}, d(q,p)={d_qp:.8f}"
        )

    def test_nonnegative(self):
        """距離は常に非負"""
        K = 5
        rng = np.random.default_rng(seed=7)
        p = rng.dirichlet(np.ones(K))
        q = rng.dirichlet(np.ones(K))
        C = _grid_cost(K)
        assert sinkhorn_distance(p, q, C) >= 0.0

    def test_single_zone_uniform_cost(self):
        """単一ゾーン集中分布 × 一様コスト行列: 概念的妥当性確認"""
        K = 3
        C = _uniform_cost(K)
        p = np.array([1.0, 0.0, 0.0])
        q = np.array([0.0, 1.0, 0.0])
        d = sinkhorn_distance(p, q, C)
        assert d > 0.0, "異なるゾーン間の距離は正でなければならない"

    def test_shape_mismatch_raises(self):
        """サイズ不一致は ValueError を上げる"""
        p = np.ones(3) / 3
        q = np.ones(4) / 4
        C = np.zeros((3, 3))
        with pytest.raises(ValueError):
            sinkhorn_distance(p, q, C)


# ---------------------------------------------------------------------------
# pairwise_distance_matrix テスト
# ---------------------------------------------------------------------------

class TestPairwiseDistanceMatrix:

    def test_empty_returns_empty(self):
        """空辞書は空リストと空行列を返す"""
        player_ids, D = pairwise_distance_matrix({}, np.zeros((0, 0)))
        assert player_ids == []
        assert D.shape == (0, 0)

    def test_single_player(self):
        """選手 1 人は 1×1 の零行列"""
        K = 9
        hist = {1: np.ones(K) / K}
        cost = _grid_cost(K)
        player_ids, D = pairwise_distance_matrix(hist, cost)
        assert player_ids == [1]
        assert D.shape == (1, 1)
        assert D[0, 0] == pytest.approx(0.0)

    def test_symmetric_matrix(self):
        """距離行列は対称"""
        K = 9
        rng = np.random.default_rng(seed=100)
        hists = {i: rng.dirichlet(np.ones(K)) for i in [1, 2, 3]}
        cost = _grid_cost(K)
        _, D = pairwise_distance_matrix(hists, cost)
        assert np.allclose(D, D.T, atol=1e-8)

    def test_diagonal_zero(self):
        """対角要素 = 0"""
        K = 9
        rng = np.random.default_rng(seed=200)
        hists = {i: rng.dirichlet(np.ones(K)) for i in [10, 20, 30]}
        cost = _grid_cost(K)
        _, D = pairwise_distance_matrix(hists, cost)
        assert np.allclose(np.diag(D), 0.0, atol=1e-10)

    def test_order_is_sorted(self):
        """返り値の player_ids は昇順ソート"""
        K = 3
        hists = {5: np.ones(K)/K, 2: np.ones(K)/K, 9: np.ones(K)/K}
        cost = _grid_cost(K)
        player_ids, _ = pairwise_distance_matrix(hists, cost)
        assert player_ids == sorted(player_ids)


# ---------------------------------------------------------------------------
# classical_mds テスト
# ---------------------------------------------------------------------------

class TestClassicalMDS:

    def test_empty_input(self):
        """空行列は形状 (0, 2) を返す"""
        coords = classical_mds(np.empty((0, 0)))
        assert coords.shape == (0, 2)

    def test_single_point(self):
        """1 点は原点を返す"""
        coords = classical_mds(np.zeros((1, 1)))
        assert coords.shape == (1, 2)
        assert np.allclose(coords, 0.0)

    def test_finite_coords(self):
        """有限な距離行列からは有限な座標が返る"""
        K = 9
        rng = np.random.default_rng(seed=42)
        hists = {i: rng.dirichlet(np.ones(K)) for i in range(5)}
        cost = _grid_cost(K)
        _, D = pairwise_distance_matrix(hists, cost)
        coords = classical_mds(D, dims=2)
        assert coords.shape == (5, 2)
        assert np.all(np.isfinite(coords)), "座標に NaN/inf が含まれている"

    def test_known_1d_structure(self):
        """3 点の 1D 距離行列: MDS は元の 1D 構造を保存するはず"""
        # 点 A=0, B=1, C=2 の 1D 距離 → [0,1,2], [1,0,1], [2,1,0]
        D = np.array([[0, 1, 2], [1, 0, 1], [2, 1, 0]], dtype=float)
        coords = classical_mds(D, dims=2)
        assert coords.shape == (3, 2)
        assert np.all(np.isfinite(coords))
        # 主成分での 3 点間相対距離が元の 1D 距離と一致するか確認
        # (MDS は回転不変なので絶対位置ではなく相対距離で検証)
        pc1 = coords[:, 0]  # 第 1 主成分
        d_AB = abs(pc1[0] - pc1[1])
        d_BC = abs(pc1[1] - pc1[2])
        d_AC = abs(pc1[0] - pc1[2])
        # d_AC ≈ 2 * d_AB ≈ 2 * d_BC (1D 等間隔)
        assert abs(d_AC - 2 * d_AB) < 0.1, f"距離比が崩れている: d_AC={d_AC:.4f}, 2*d_AB={2*d_AB:.4f}"

    def test_dims_clipped_to_n_minus_1(self):
        """dims > N-1 のとき N-1 までクリップされる (エラーにならない)"""
        D = np.array([[0, 1], [1, 0]], dtype=float)
        coords = classical_mds(D, dims=5)  # N=2 なので実質 dims=1
        assert coords.shape[0] == 2
        assert np.all(np.isfinite(coords))
