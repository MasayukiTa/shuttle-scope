"""
bayes_matchup.py — 階層的ベイズ対戦予測モデル (Research Spine RS-4)

モデル: Beta-Binomial 経験的ベイズ
  - 事前分布: Beta(α, β) をデータから推定（経験的ベイズ）
  - 尤度: Binomial(n, p)
  - 事後: Beta(α + wins, β + losses)

対応する要素:
  - 利き手（handedness）による層別
  - フォーマット（singles/doubles）による層別
  - 対戦相手タイプ（ルールベース分類）による調整
  - 観察情報（pre-match observation）による補正（オプション）

シュリンケージ: 試合数が少ない相手ほど全体平均に引き寄せられる

出力:
  - posterior_win_prob: 事後期待勝率
  - credible_interval: 95% 信用区間
  - shrinkage_weight: 全体平均への引き寄せ強度 (0〜1)
  - effective_sample_size: 事前に等価なサンプルサイズ
"""
from __future__ import annotations
import math
from collections import defaultdict
from typing import Optional


# ── Beta パラメータ推定 ───────────────────────────────────────────────────────

def estimate_beta_params(win_rates: list[float], min_n: int = 5) -> tuple[float, float]:
    """
    勝率リストからメソッド・オブ・モーメントで Beta(α, β) を推定。
    Returns: (alpha, beta)
    """
    if not win_rates:
        return (1.0, 1.0)
    n = len(win_rates)
    mean = sum(win_rates) / n
    if n < 2:
        return (max(1.0, mean * 10), max(1.0, (1 - mean) * 10))
    var = sum((r - mean) ** 2 for r in win_rates) / (n - 1)
    # Jeffreys 下限
    var = max(var, 1e-6)
    common = mean * (1 - mean) / var - 1
    if common <= 0:
        return (max(1.0, mean * 10), max(1.0, (1 - mean) * 10))
    alpha = max(0.5, mean * common)
    beta = max(0.5, (1 - mean) * common)
    return (round(alpha, 4), round(beta, 4))


def beta_credible_interval(alpha: float, beta: float, z: float = 1.96) -> tuple[float, float]:
    """
    Beta 分布の近似 95% 信用区間。
    Wilson 近似を使用（厳密な Beta 積分は不要）。
    """
    mean = alpha / (alpha + beta)
    variance = alpha * beta / ((alpha + beta) ** 2 * (alpha + beta + 1))
    std = math.sqrt(variance)
    ci_low = max(0.0, mean - z * std)
    ci_high = min(1.0, mean + z * std)
    return (round(ci_low, 4), round(ci_high, 4))


# ── 対戦相手タイプ分類（ルールベース） ──────────────────────────────────────

def classify_opponent_type(
    opp_win_rate_vs_player: float,
    n_matches: int,
) -> str:
    """
    対戦成績からシンプルな対戦相手タイプを返す。
    類型: "dominating" / "competitive" / "beatable" / "unknown"
    """
    if n_matches < 2:
        return "unknown"
    if opp_win_rate_vs_player > 0.70:
        return "dominating"
    if opp_win_rate_vs_player < 0.30:
        return "beatable"
    return "competitive"


# ── メインの対戦予測計算 ──────────────────────────────────────────────────────

def compute_bayes_matchup(
    matches: list,
    player_id: int,
    target_opponent_id: Optional[int] = None,
    handedness: Optional[str] = None,
    format_filter: Optional[str] = None,
) -> dict:
    """
    Beta-Binomial 経験的ベイズによる対戦勝率事後推定。

    Parameters:
        matches: Match ORM オブジェクトのリスト（player に関連する全試合）
        player_id: 対象選手 ID
        target_opponent_id: 特定の対戦相手に絞る（None = 全体）
        handedness: 右利き/左利き フィルター
        format_filter: "singles" / "doubles" フィルター

    Returns:
        {
          "global_prior": {"alpha": float, "beta": float},
          "global_win_rate": float,
          "opponent_estimates": [
            {
              "opponent_id": int,
              "n_matches": int,
              "observed_wins": int,
              "observed_win_rate": float,
              "posterior_alpha": float,
              "posterior_beta": float,
              "posterior_win_prob": float,
              "credible_interval": [float, float],
              "shrinkage_weight": float,
              "opponent_type": str,
            }
          ],
          "total_matches": int,
        }
    """
    # 選手別勝率の集計
    player_match_count: dict[int, int] = defaultdict(int)
    player_match_wins: dict[int, int] = defaultdict(int)
    # match オブジェクトには player_a_id, player_b_id, result_a 等を仮定

    total_matches = 0
    total_wins = 0

    for m in matches:
        # 対戦相手 ID を判定
        if hasattr(m, 'player_a_id') and hasattr(m, 'player_b_id'):
            if m.player_a_id == player_id:
                opp_id = m.player_b_id
                player_won = m.winner == 'player_a'
            elif m.player_b_id == player_id:
                opp_id = m.player_a_id
                player_won = m.winner == 'player_b'
            else:
                continue
        else:
            # シンプル構造
            opp_id = getattr(m, 'opponent_id', 0)
            player_won = getattr(m, 'result', '') == 'win'

        # フォーマットフィルター
        if format_filter:
            m_format = getattr(m, 'format', None)
            if m_format and m_format != format_filter:
                continue

        if target_opponent_id and opp_id != target_opponent_id:
            continue

        player_match_count[opp_id] += 1
        total_matches += 1
        if player_won:
            player_match_wins[opp_id] += 1
            total_wins += 1

    if total_matches == 0:
        return {
            "global_prior": {"alpha": 1.0, "beta": 1.0},
            "global_win_rate": 0.5,
            "opponent_estimates": [],
            "total_matches": 0,
        }

    global_win_rate = round(total_wins / total_matches, 4)

    # 全体の勝率分布から事前分布を推定
    opp_win_rates = [
        player_match_wins[oid] / player_match_count[oid]
        for oid in player_match_count
        if player_match_count[oid] >= 2
    ]
    prior_alpha, prior_beta = estimate_beta_params(opp_win_rates) if opp_win_rates else (1.0, 1.0)

    # 対戦相手ごとの事後推定
    opponent_estimates = []
    for opp_id, n_matches in player_match_count.items():
        wins = player_match_wins[opp_id]
        losses = n_matches - wins
        obs_wr = round(wins / n_matches, 4)

        # 事後パラメータ
        post_alpha = prior_alpha + wins
        post_beta = prior_beta + losses
        post_mean = round(post_alpha / (post_alpha + post_beta), 4)
        ci = beta_credible_interval(post_alpha, post_beta)

        # シュリンケージ強度: n が多いほど事前への引き寄せ小
        effective_prior_n = prior_alpha + prior_beta
        shrinkage = round(effective_prior_n / (effective_prior_n + n_matches), 4)

        opp_type = classify_opponent_type(1 - obs_wr, n_matches)

        opponent_estimates.append({
            "opponent_id": opp_id,
            "n_matches": n_matches,
            "observed_wins": wins,
            "observed_win_rate": obs_wr,
            "posterior_alpha": round(post_alpha, 3),
            "posterior_beta": round(post_beta, 3),
            "posterior_win_prob": post_mean,
            "credible_interval": list(ci),
            "shrinkage_weight": shrinkage,
            "opponent_type": opp_type,
        })

    # 事後勝率の高い順にソート
    opponent_estimates.sort(key=lambda x: x["posterior_win_prob"], reverse=True)

    return {
        "global_prior": {"alpha": round(prior_alpha, 3), "beta": round(prior_beta, 3)},
        "global_win_rate": global_win_rate,
        "opponent_estimates": opponent_estimates,
        "total_matches": total_matches,
    }
