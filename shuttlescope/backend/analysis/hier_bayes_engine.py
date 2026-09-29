"""
hier_bayes_engine.py — 階層的ベイズ Bradley-Terry 対戦予測モデル (Research ③)

モデル:
  θ_i ~ Normal(0, τ²)  (階層的正規事前分布; τ はハイパーパラメータとして固定渡し)
  P(i beats j) = σ(θ_i − θ_j)   (Bradley-Terry ロジスティック版)

最適化 (ペナルティ付き最尤):
  L(θ) = Σ_{(w,l)} log σ(θ_w − θ_l)  −  (1 / (2τ²)) Σ_i θ_i²

  リッジ罰則項 −(1/2τ²)Σθ_i² は階層的 Normal(0,τ²) 事前分布の対数確率に一致する。
  すなわちこれは MAP 推定であり、完全ベイズでなく Laplace 近似で不確実性を与える。

最適化手法:
  勾配上昇法 + バックトラッキング直線探索 (Armijo 条件)。
  NumPy のみ使用。

不確実性:
  Laplace 近似: θ の事後分散 ≈ diag(−H)^{-1}
  ここで H = ∂²L/∂θ² = ヘッシアン (負定値)。
  predict_matchup は θ_i−θ_j ~ Normal(Δ, var_i+var_j) を MC 伝搬させ
  σ を通して CI を得る。

識別可能性:
  罰則が θ=0 への正則化として機能するため絶対スケールは固定される。
  反復ごとに θ を平均 0 に中心化して数値安定性を保つ (罰則によりいずれ 0 に引き寄せられるが
  早期の発散を防ぐため明示的に施す)。
"""
from __future__ import annotations

import numpy as np


# ── 内部ユーティリティ ─────────────────────────────────────────────────────────

def _sigmoid(x: np.ndarray) -> np.ndarray:
    """数値安定なシグモイド関数。"""
    # 正の値と負の値で別々に計算してオーバーフローを防ぐ
    pos = x >= 0
    result = np.empty_like(x, dtype=float)
    result[pos] = 1.0 / (1.0 + np.exp(-x[pos]))
    exp_x = np.exp(x[~pos])
    result[~pos] = exp_x / (1.0 + exp_x)
    return result


def _log_likelihood_and_grad(
    theta: np.ndarray,
    winner_idx: np.ndarray,
    loser_idx: np.ndarray,
    tau: float,
) -> tuple[float, np.ndarray]:
    """ペナルティ付き対数尤度とその勾配を同時計算する。

    L(θ) = Σ log σ(θ_w − θ_l)  −  (1/2τ²) Σ θ_i²
    ∂L/∂θ_i = Σ_{(w,l): w=i} (1 − σ(θ_w − θ_l))
             − Σ_{(w,l): l=i} σ(θ_w − θ_l)
             − θ_i / τ²
    """
    delta = theta[winner_idx] - theta[loser_idx]   # shape (n_pairs,)
    sigma = _sigmoid(delta)                          # P(winner beats loser)
    penalty = -0.5 / (tau ** 2) * float(np.dot(theta, theta))
    ll = float(np.sum(np.log(np.maximum(sigma, 1e-15)))) + penalty

    # 勾配
    grad = np.zeros_like(theta)
    residual = 1.0 - sigma  # ∂log σ/∂delta = 1 − σ
    np.add.at(grad, winner_idx, residual)
    np.add.at(grad, loser_idx, -sigma)
    grad -= theta / (tau ** 2)  # 罰則の勾配
    return ll, grad


def _hessian_diagonal(
    theta: np.ndarray,
    winner_idx: np.ndarray,
    loser_idx: np.ndarray,
    tau: float,
) -> np.ndarray:
    """ヘッシアンの対角成分を返す。

    ∂²L/∂θ_i² = −Σ_{(w,l): w=i or l=i} σ(δ)(1−σ(δ))  −  1/τ²
    (交差項 ∂²/∂θ_w∂θ_l = σ(δ)(1−σ(δ)) > 0 はここでは計算しない; 対角近似)
    """
    delta = theta[winner_idx] - theta[loser_idx]
    sigma = _sigmoid(delta)
    curv = sigma * (1.0 - sigma)   # 2次曲率成分 ∈ (0, 0.25]

    diag_H = np.zeros_like(theta)
    np.add.at(diag_H, winner_idx, -curv)
    np.add.at(diag_H, loser_idx, -curv)
    diag_H -= 1.0 / (tau ** 2)    # 罰則の 2 階微分
    return diag_H  # 全成分 ≤ 0 (強凹性)


# ── 公開 API ──────────────────────────────────────────────────────────────────

def fit_bradley_terry(
    pairs: list[tuple[int, int]],
    n_players: int,
    prior_tau: float = 1.0,
    iters: int = 100,
) -> dict:
    """Bradley-Terry モデルを ペナルティ付き MLE (= 階層的 Normal 事前の MAP) で推定する。

    Parameters
    ----------
    pairs : list of (winner_idx, loser_idx)
        0-indexed の選手ペア。各 idx は [0, n_players) の範囲内。
    n_players : int
        選手総数。pairs に登場しない選手も含む。
    prior_tau : float
        事前分布 θ_i ~ Normal(0, τ²) のスケール。
        大きいほど正則化が弱まり (= データ優先)、小さいほど収縮が強まる。
    iters : int
        勾配上昇の最大反復回数。

    Returns
    -------
    dict with:
        theta           : np.ndarray shape (n_players,)  — 推定強度 (平均 ≈ 0)
        theta_var       : np.ndarray shape (n_players,)  — Laplace 後分散 (対角)
        tau             : float
        n_obs_per_player: np.ndarray shape (n_players,)  — 各選手の登場試合数
    """
    # ── エッジケース ──────────────────────────────────────────────────────────
    theta = np.zeros(n_players, dtype=float)
    n_obs = np.zeros(n_players, dtype=int)

    if n_players < 2 or len(pairs) == 0:
        # 試合無し: θ=0、大きな分散 (= 情報無し)
        var = np.full(n_players, prior_tau ** 2)
        return {
            "theta": theta,
            "theta_var": var,
            "tau": float(prior_tau),
            "n_obs_per_player": n_obs,
        }

    winner_idx = np.array([p[0] for p in pairs], dtype=int)
    loser_idx  = np.array([p[1] for p in pairs], dtype=int)

    # 各選手の登場数を集計
    for w, l in pairs:
        n_obs[w] += 1
        n_obs[l] += 1

    # ── 勾配上昇 + バックトラッキング直線探索 ───────────────────────────────
    tau = float(prior_tau)
    lr_init = 0.5      # 初期学習率
    armijo_c = 1e-4    # Armijo 条件の定数
    max_backtrack = 20 # バックトラック最大回数

    for _it in range(int(iters)):
        ll, grad = _log_likelihood_and_grad(theta, winner_idx, loser_idx, tau)
        grad_norm = float(np.linalg.norm(grad))
        if grad_norm < 1e-8:
            break  # 収束

        direction = grad  # 上昇方向

        # バックトラッキング直線探索 (Armijo)
        lr = lr_init
        for _ in range(max_backtrack):
            theta_new = theta + lr * direction
            # 識別可能性のため中心化
            theta_new -= theta_new.mean()
            ll_new, _ = _log_likelihood_and_grad(theta_new, winner_idx, loser_idx, tau)
            if ll_new >= ll + armijo_c * lr * grad_norm ** 2:
                break
            lr *= 0.5
        else:
            # 全バックトラック失敗時は微小ステップで前進
            theta_new = theta + 1e-6 * direction
            theta_new -= theta_new.mean()

        theta = theta_new

    # 最終中心化
    theta -= theta.mean()

    # ── Laplace 近似: 後分散 = 1 / (−∂²L/∂θ_i²) ─────────────────────────
    diag_H = _hessian_diagonal(theta, winner_idx, loser_idx, tau)
    # diag_H は全成分 < 0; −diag_H > 0 が Fisher 情報対角
    theta_var = 1.0 / np.maximum(-diag_H, 1e-12)

    return {
        "theta": theta,
        "theta_var": theta_var,
        "tau": tau,
        "n_obs_per_player": n_obs,
    }


def predict_matchup(
    theta_i: float,
    var_i: float,
    theta_j: float,
    var_j: float,
    n_mc: int = 2000,
    seed: int = 0,
) -> dict:
    """2 選手の対戦勝率と信頼区間を MC で計算する。

    θ_i − θ_j ~ Normal(Δ, var_i + var_j) を利用して
    P(i beats j) = σ(θ_i − θ_j) の分布を Monte Carlo 伝搬させる。

    Parameters
    ----------
    theta_i, var_i : 選手 i の強度点推定と Laplace 後分散
    theta_j, var_j : 選手 j の強度点推定と Laplace 後分散
    n_mc           : MC サンプル数
    seed           : numpy default_rng シード (再現性)

    Returns
    -------
    dict with:
        p_win    : float  — 点推定 σ(Δ)
        ci_low   : float  — 90% 信用区間下限
        ci_high  : float  — 90% 信用区間上限
    """
    delta_mean = float(theta_i) - float(theta_j)
    delta_std  = float(np.sqrt(max(float(var_i) + float(var_j), 1e-12)))

    # 点推定
    p_win = float(_sigmoid(np.array([delta_mean]))[0])

    # MC による CI (90%)
    rng = np.random.default_rng(int(seed))
    samples = rng.normal(loc=delta_mean, scale=delta_std, size=int(n_mc))
    p_samples = _sigmoid(samples)

    ci_low  = float(np.percentile(p_samples, 5.0))
    ci_high = float(np.percentile(p_samples, 95.0))

    return {
        "p_win":    round(p_win,   4),
        "ci_low":   round(ci_low,  4),
        "ci_high":  round(ci_high, 4),
    }
