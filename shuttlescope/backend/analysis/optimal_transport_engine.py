"""
optimal_transport_engine.py — エントロピー正則化最適輸送 (Sinkhorn) エンジン (Research)

選手のショット着地点分布をゾーンヒストグラムで表現し、
プレースメントスタイルの「距離」を Wasserstein (OT) 距離で定量化する。

設計原則:
  - 純粋関数のみ (DB アクセス無し)。numpy 以外の依存無し。
  - entropic-regularized OT (Sinkhorn 法) を使用。scipy は使わない。
  - サンプル不足・ゼロ割り防止のため epsilon ガードを随所に挿入する。
  - 決定論的: 乱数/datetime 不使用。
"""
from __future__ import annotations

import numpy as np


# ---------------------------------------------------------------------------
# Sinkhorn エントロピー正則化 OT
# ---------------------------------------------------------------------------

def _sinkhorn_raw(
    p: np.ndarray,
    q: np.ndarray,
    cost: np.ndarray,
    reg: float = 0.05,
    iters: int = 300,
) -> float:
    """エントロピー正則化 OT の生コスト <T*, C> (自己バイアスを含む)。

    p, q : 正規化済みヒストグラム (長さ K の 1D array、和 ≈ 1)
    cost : K×K コスト行列 (非負、対角 = 0)
    reg  : エントロピー正則化パラメータ λ (大きいほど滑らか、小さいほど真の OT に近い)
    iters: Sinkhorn 反復回数

    返り値: スカラー輸送コスト <T*, cost>

    注意:
      - p/q は正規化されている必要がある (合計が 1 でない場合は内部で正規化)
      - ゼロ要素への log(0) を防ぐため epsilon=1e-10 を加算する
    """
    eps = 1e-10  # ゼロ除算・log(0) ガード

    p = np.asarray(p, dtype=float)
    q = np.asarray(q, dtype=float)
    C = np.asarray(cost, dtype=float)

    K = len(p)
    if len(q) != K or C.shape != (K, K):
        raise ValueError(
            f"sinkhorn_distance: shape mismatch p={p.shape}, q={q.shape}, cost={C.shape}"
        )

    # 正規化 (呼び出し側が既に正規化していても再正規化で安全にする)
    p = (p + eps) / (p + eps).sum()
    q = (q + eps) / (q + eps).sum()

    # Gibbs カーネル K = exp(-C / λ)
    # 数値安定化のため C を最大値でシフトしてから exp を取る
    log_K = -C / reg
    log_K -= log_K.max()          # 最大を 0 にシフト (exp が inf にならないよう)
    Kmat = np.exp(log_K)          # (K, K)

    # Sinkhorn 反復: u, v を交互に更新
    u = np.ones(K)                # スケーリング変数
    v = np.ones(K)

    for _ in range(int(iters)):
        u = p / (Kmat @ v + eps)
        v = q / (Kmat.T @ u + eps)

    # 輸送行列 T = diag(u) K diag(v)
    T = u[:, None] * Kmat * v[None, :]

    # スカラーコスト: <T, C> = Σ T_ij * C_ij
    return float(np.sum(T * C))


def sinkhorn_distance(
    p: np.ndarray,
    q: np.ndarray,
    cost: np.ndarray,
    reg: float = 0.05,
    iters: int = 300,
) -> float:
    """脱バイアス Sinkhorn ダイバージェンス S(p,q)=OT(p,q)−½OT(p,p)−½OT(q,q)。

    エントロピー正則化 OT の自己バイアスを除去するため、同一分布で ≈0 になる
    proper な距離になる (生 Sinkhorn コストは同一分布でも正の値を持つ)。
    """
    pq = _sinkhorn_raw(p, q, cost, reg, iters)
    pp = _sinkhorn_raw(p, p, cost, reg, iters)
    qq = _sinkhorn_raw(q, q, cost, reg, iters)
    return max(0.0, float(pq - 0.5 * pp - 0.5 * qq))


# ---------------------------------------------------------------------------
# 選手間ペアワイズ距離行列
# ---------------------------------------------------------------------------

def pairwise_distance_matrix(
    hists: dict[int, np.ndarray],
    cost: np.ndarray,
    *,
    reg: float = 0.05,
    iters: int = 300,
) -> tuple[list[int], np.ndarray]:
    """選手ヒストグラム辞書からペアワイズ Sinkhorn 距離行列を計算する。

    hists : {player_id: normalized_histogram (長さ K)}
    cost  : K×K コスト行列

    返り値: (player_ids の順序付きリスト, D×D 距離行列)

    注意:
      - 距離行列は対称行列として計算する (d[i,j] = d[j,i] の平均を取る)
      - 辞書の要素が 1 以下の場合は空行列を返す
    """
    player_ids = sorted(hists.keys())
    D = len(player_ids)
    if D == 0:
        return [], np.empty((0, 0))

    dist_mat = np.zeros((D, D))

    for i in range(D):
        for j in range(i + 1, D):
            pi = hists[player_ids[i]]
            pj = hists[player_ids[j]]
            d = sinkhorn_distance(pi, pj, cost, reg=reg, iters=iters)
            dist_mat[i, j] = d
            dist_mat[j, i] = d   # 対称性: Sinkhorn は対称なので同値だが念のため

    return player_ids, dist_mat


# ---------------------------------------------------------------------------
# 古典 MDS (スタイルマップ埋め込み)
# ---------------------------------------------------------------------------

def classical_mds(D: np.ndarray, dims: int = 2) -> np.ndarray:
    """距離行列 D から古典 MDS 埋め込み座標 (N × dims) を計算する。

    アルゴリズム:
      1. D^2 を二重中心化して内積行列 B を作る
      2. B を固有値分解し、上位 dims 固有ベクトルを取る
      3. 固有値の平方根をスケーリングして座標を構成する

    返り値: (N, dims) ndarray (N = 選手数)
            固有値が負になる場合は 0 にクリップして虚部を除去する。

    注意:
      - 入力が 1×1 の場合は原点を返す
    """
    D = np.asarray(D, dtype=float)
    N = D.shape[0]
    if N == 0:
        return np.empty((0, dims))
    if N == 1:
        return np.zeros((1, dims))

    dims = min(dims, N - 1)   # MDS の自由度は N-1 まで

    # 二重中心化: B = -1/2 * H D^2 H,  H = I - (1/N) 11^T
    D2 = D ** 2
    J = np.eye(N) - np.ones((N, N)) / N
    B = -0.5 * J @ D2 @ J

    # 固有値分解 (numpy は降順保証なし → 降順ソート)
    eigvals, eigvecs = np.linalg.eigh(B)   # eigh: 対称行列専用 (実数保証)
    order = np.argsort(eigvals)[::-1]      # 降順
    eigvals = eigvals[order]
    eigvecs = eigvecs[:, order]

    # 負の固有値をゼロにクリップ (数値誤差で僅かに負になる場合がある)
    eigvals_clipped = np.maximum(eigvals[:dims], 0.0)

    # 座標: X = V_k * diag(sqrt(λ_k))
    coords = eigvecs[:, :dims] * np.sqrt(eigvals_clipped)[None, :]
    return coords
