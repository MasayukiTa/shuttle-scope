"""
opponent_policy_engine.py — 対戦相手ポリシー応答エンジン (Research Spine RS-4)

目的:
  - 対戦相手のショット選択ポリシー（多軸条件付き分布）を推定する
  - 単純なスタイルラベルより細粒度な戦術応答の傾向を把握する
  - 状態条件（スコア・ラリーフェーズ・ゾーン）ごとの優先ショットを出力

設計:
  - 純粋関数（DB アクセスなし）
  - 対戦相手のショットデータが必要（opponent role のストロークを集計）
  - 出力は確率分布 + エントロピー（ポリシーの「読みやすさ」指標）
"""
from __future__ import annotations
import math
from collections import defaultdict
from typing import Optional

from backend.analysis.state_spec import build_rally_state


# ── エントロピー計算 ─────────────────────────────────────────────────────────

def _shannon_entropy(dist: dict[str, float]) -> float:
    """ショット確率分布のシャノンエントロピーを計算。0〜log2(N) の範囲。"""
    entropy = 0.0
    for p in dist.values():
        if p > 0:
            entropy -= p * math.log2(p)
    return round(entropy, 4)


def _normalize(counts: dict[str, int]) -> dict[str, float]:
    """カウントを確率分布に正規化する。"""
    total = sum(counts.values())
    if total == 0:
        return {}
    return {st: round(c / total, 4) for st, c in counts.items()}


# ── コンテキストキー ─────────────────────────────────────────────────────────

def _policy_context_key(score_phase: str, rally_bucket: str, zone: Optional[str]) -> tuple:
    """ポリシー推定のコンテキストキー（3軸）。"""
    return (score_phase, rally_bucket, zone or "all")


# ── メイン計算 ───────────────────────────────────────────────────────────────

def compute_opponent_policy(
    rallies: list,
    strokes_by_rally: dict[int, list],
    role_by_match: dict[int, str],
    set_to_match: dict[int, int],
    set_num_by_set: dict[int, int],
    min_support: int = 15,
) -> dict:
    """
    対戦相手のポリシー（コンテキスト条件付きショット分布）を推定する。

    対戦相手ロール = opponent（非 player_role）のショットを集計。

    Returns:
        {
          "global_policy": {shot_type: float},
          "global_entropy": float,
          "context_policies": [
            {
              "context_key": str,
              "context": {"score_phase": str, "rally_bucket": str, "zone": str},
              "n": int,
              "shot_distribution": {shot_type: float},
              "entropy": float,
              "dominant_shot": str,
              "dominant_prob": float,
              "predictability": str,  // "unpredictable" / "mixed" / "predictable"
            }
          ],
          "total_opponent_shots": int,
          "usable_contexts": int,
        }
    """
    # 全体集計
    global_counts: dict[str, int] = defaultdict(int)
    total_opp_shots = 0

    # コンテキスト×ショット集計
    ctx_counts: dict[tuple, dict[str, int]] = defaultdict(lambda: defaultdict(int))
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

        rs = build_rally_state(
            my_score=my_score,
            opp_score=opp_score,
            set_num=set_num,
            rally_length=rally.rally_length,
            server=rally.server,
            player_role=role,
        )

        # 対戦相手のショットを集計（opponent role = player でないほう）
        opp_role = "player_b" if role == "player_a" else "player_a"
        stks = sorted(strokes_by_rally.get(rally.id, []), key=lambda x: x.stroke_num)
        opp_stks = [s for s in stks if s.player == opp_role and s.shot_type]

        for stroke in opp_stks:
            zone = getattr(stroke, 'land_zone', None)
            ctx_key = _policy_context_key(rs.score_phase, rs.rally_bucket, zone)
            ctx_counts[ctx_key][stroke.shot_type] += 1
            ctx_obj[ctx_key] = {
                "score_phase": rs.score_phase,
                "rally_bucket": rs.rally_bucket,
                "zone": zone,
            }
            global_counts[stroke.shot_type] += 1
            total_opp_shots += 1

    # 全体ポリシー
    global_policy = _normalize(global_counts)
    global_entropy = _shannon_entropy(global_policy)

    # コンテキストポリシー
    context_policies = []
    usable = 0

    for ctx_key, counts in ctx_counts.items():
        total_ctx = sum(counts.values())
        if total_ctx < min_support:
            continue
        usable += 1

        dist = _normalize(counts)
        entropy = _shannon_entropy(dist)
        dominant = max(dist, key=lambda st: dist[st])
        dominant_prob = dist[dominant]

        # 予測可能性
        if dominant_prob >= 0.60:
            predictability = "predictable"
        elif dominant_prob >= 0.40:
            predictability = "mixed"
        else:
            predictability = "unpredictable"

        context_policies.append({
            "context_key": str(ctx_key),
            "context": ctx_obj[ctx_key],
            "n": total_ctx,
            "shot_distribution": dist,
            "entropy": entropy,
            "dominant_shot": dominant,
            "dominant_prob": dominant_prob,
            "predictability": predictability,
        })

    # n 降順でソート
    context_policies.sort(key=lambda x: x["n"], reverse=True)

    return {
        "global_policy": global_policy,
        "global_entropy": global_entropy,
        "context_policies": context_policies,
        "total_opponent_shots": total_opp_shots,
        "usable_contexts": usable,
    }
