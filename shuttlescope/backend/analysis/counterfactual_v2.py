"""
counterfactual_v2.py — 反事実的ショット比較 v2 (Research Spine RS-3, CF-1 フェーズ)

CF-1 フェーズの改善点（既存 counterfactual_engine.py との差分）:
  1. ブートストラップ CI（1000回リサンプル）による不確実性推定
  2. overlap_score（サポート重複率）の付与
  3. minimum_support_threshold による低品質比較の除外
  4. state_spec.RallyState との統合

CF-2（傾向スコア重み付け）・CF-3（対戦相手条件付き）は別フェーズで実装予定。

設計:
  - 純粋関数（DB アクセスなし）
  - 既存 counterfactual_engine に対して後方互換を壊さない
"""
from __future__ import annotations
import math
import random
from collections import defaultdict
from typing import Optional

from backend.analysis.state_spec import build_rally_state

# ブートストラップ設定
BOOTSTRAP_N = 500          # リサンプル回数（精度と速度のバランス）
BOOTSTRAP_MIN_SUPPORT = 10  # 最低サポート数（未満は比較をスキップ）
CONFIDENCE_Z = 1.96         # 95% CI


def _bootstrap_win_rate(wins: list[bool], n_bootstrap: int = BOOTSTRAP_N) -> tuple[float, float]:
    """
    ブートストラップによる勝率の95% CI を返す。
    Returns: (ci_low, ci_high)
    """
    if not wins:
        return (0.0, 1.0)
    n = len(wins)
    boot_means = []
    for _ in range(n_bootstrap):
        sample = random.choices(wins, k=n)
        boot_means.append(sum(sample) / n)
    boot_means.sort()
    lo_idx = int(n_bootstrap * 0.025)
    hi_idx = int(n_bootstrap * 0.975)
    return (round(boot_means[lo_idx], 4), round(boot_means[hi_idx], 4))


def _build_context_key_v2(
    score_phase: str,
    rally_bucket: str,
    set_phase: str,
    prev_shot: Optional[str],
) -> tuple:
    """
    v2 コンテキストキー: state_spec 由来の次元 + 直前ショット
    """
    return (score_phase, rally_bucket, set_phase, prev_shot or "unknown")


def compute_counterfactual_v2(
    rallies: list,
    strokes_by_rally: dict[int, list],
    role_by_match: dict[int, str],
    set_to_match: dict[int, int],
    set_num_by_set: dict[int, int],
    min_support: int = BOOTSTRAP_MIN_SUPPORT,
    n_bootstrap: int = BOOTSTRAP_N,
) -> dict:
    """
    CF-1: コンテキスト一致 + ブートストラップCI の反事実的ショット比較。

    Returns:
        {
          "comparisons": [
            {
              "context_key": str,
              "context": dict,
              "actual_shot": str,
              "actual_win_rate": float,
              "actual_n": int,
              "actual_ci_low": float,
              "actual_ci_high": float,
              "alternatives": [
                {
                  "shot_type": str,
                  "win_rate": float,
                  "n": int,
                  "ci_low": float,
                  "ci_high": float,
                  "estimated_lift": float,
                  "overlap_score": float,
                }
              ],
              "best_alternative": str | None,
              "max_lift": float,
            }
          ],
          "total_contexts": int,
          "usable_contexts": int,
        }
    """
    # コンテキスト×ショット種別 集計
    # key: (context_key, shot_type) → list[bool] (wins)
    ctx_shot_wins: dict[tuple, list[bool]] = defaultdict(list)
    ctx_total: dict[tuple, int] = defaultdict(int)
    ctx_obj: dict[tuple, dict] = {}

    for rally in rallies:
        mid = set_to_match.get(rally.set_id)
        if mid is None:
            continue
        role = role_by_match.get(mid)
        if not role:
            continue
        set_num = set_num_by_set.get(rally.set_id, 1)
        player_is_a = role == "player_a"

        my_score = rally.score_a_before if player_is_a else rally.score_b_before
        opp_score = rally.score_b_before if player_is_a else rally.score_a_before
        is_win = rally.winner == role

        rs = build_rally_state(
            my_score=my_score,
            opp_score=opp_score,
            set_num=set_num,
            rally_length=rally.rally_length,
            server=rally.server,
            player_role=role,
        )

        stks = sorted(strokes_by_rally.get(rally.id, []), key=lambda x: x.stroke_num)
        player_stks = [s for s in stks if s.player == role and s.shot_type]
        if not player_stks:
            continue

        # 各ショットをコンテキスト条件で集計
        prev_shot: Optional[str] = None
        for stroke in player_stks:
            ctx_key = _build_context_key_v2(
                rs.score_phase, rs.rally_bucket, rs.set_phase, prev_shot
            )
            ctx_shot_key = (ctx_key, stroke.shot_type)
            ctx_shot_wins[ctx_shot_key].append(is_win)
            ctx_total[ctx_key] += 1
            ctx_obj[ctx_key] = {
                "score_phase": rs.score_phase,
                "rally_bucket": rs.rally_bucket,
                "set_phase": rs.set_phase,
                "prev_shot": prev_shot,
            }
            prev_shot = stroke.shot_type

    # コンテキストごとのショット別勝率を集計
    ctx_shots: dict[tuple, dict[str, list[bool]]] = defaultdict(dict)
    for (ctx_key, shot_type), wins_list in ctx_shot_wins.items():
        ctx_shots[ctx_key][shot_type] = wins_list

    # 比較テーブル構築
    comparisons: list[dict] = []
    usable = 0

    for ctx_key, shots in ctx_shots.items():
        # 十分なサポートを持つショットのみ
        valid_shots = {st: wl for st, wl in shots.items() if len(wl) >= min_support}
        if len(valid_shots) < 2:
            continue
        usable += 1

        # 各ショットの勝率と CI
        shot_stats: dict[str, dict] = {}
        for shot_type, wl in valid_shots.items():
            n = len(wl)
            wr = round(sum(wl) / n, 4)
            ci_low, ci_high = _bootstrap_win_rate(wl, n_bootstrap)
            shot_stats[shot_type] = {
                "win_rate": wr,
                "n": n,
                "ci_low": ci_low,
                "ci_high": ci_high,
            }

        # 実際の最多ショットを「実際のショット」とする
        actual_shot = max(valid_shots, key=lambda st: len(valid_shots[st]))
        actual = shot_stats[actual_shot]

        # 代替ショットとの比較
        alternatives = []
        for alt_shot, alt_stats in shot_stats.items():
            if alt_shot == actual_shot:
                continue
            lift = round(alt_stats["win_rate"] - actual["win_rate"], 4)
            # overlap_score: 2つのCIが重複している割合（不確実性の代理）
            overlap_lo = max(actual["ci_low"], alt_stats["ci_low"])
            overlap_hi = min(actual["ci_high"], alt_stats["ci_high"])
            ci_span = max(actual["ci_high"] - actual["ci_low"], 0.01)
            overlap_score = round(max(0.0, (overlap_hi - overlap_lo) / ci_span), 3)
            alternatives.append({
                "shot_type": alt_shot,
                "win_rate": alt_stats["win_rate"],
                "n": alt_stats["n"],
                "ci_low": alt_stats["ci_low"],
                "ci_high": alt_stats["ci_high"],
                "estimated_lift": lift,
                "overlap_score": overlap_score,
            })

        if not alternatives:
            continue

        alternatives.sort(key=lambda x: x["estimated_lift"], reverse=True)
        best_alt = alternatives[0]

        comparisons.append({
            "context_key": str(ctx_key),
            "context": ctx_obj.get(ctx_key, {}),
            "actual_shot": actual_shot,
            "actual_win_rate": actual["win_rate"],
            "actual_n": actual["n"],
            "actual_ci_low": actual["ci_low"],
            "actual_ci_high": actual["ci_high"],
            "alternatives": alternatives,
            "best_alternative": best_alt["shot_type"],
            "max_lift": best_alt["estimated_lift"],
        })

    # lift 降順でソート
    comparisons.sort(key=lambda x: x["max_lift"], reverse=True)

    return {
        "comparisons": comparisons,
        "total_contexts": len(ctx_shots),
        "usable_contexts": usable,
    }
