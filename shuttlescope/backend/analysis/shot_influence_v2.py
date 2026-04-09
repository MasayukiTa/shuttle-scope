"""shot_influence_v2.py — 状態条件付きショット影響度エンジン（Spine 4）+ Bootstrap CI

Spine 4 の要件:
  - state_spec の RallyState を使って状態条件付きの影響度を計算する
  - EPV state テーブルを参照し、現在の状態期待値に対するアウトカム差分をクレジットとして割り当てる
  - Terminal bonus: ラリー最終打は勝敗アウトカムの100%を受け取る

アルゴリズム:
  各ラリーの RallyState → epv(state) を参照
  各ストロークへの帰属:
    position_weight = (i+1) / n  (後半打ほど重み大)
    attack_weight   = ショット種別ヒューリスティック (既存継承)
    quality_weight  = ショット品質係数 (既存継承)
    state_credit    = (outcome - state_epv)  # 状態ベースライン補正
    influence_v2    = position_weight × attack_weight × quality_weight × state_credit_multiplier
"""
from __future__ import annotations
import random
from dataclasses import dataclass, field
from typing import Any

BOOTSTRAP_N = 300  # CI 計算用リサンプル回数（速度とのトレードオフ）
MIN_N_CI = 5       # CI を計算する最低サンプル数


def _bootstrap_mean_ci(values: list[float], n_bootstrap: int = BOOTSTRAP_N) -> tuple[float, float]:
    """list[float] のブートストラップ 95% CI を返す。"""
    if len(values) < MIN_N_CI:
        avg = sum(values) / len(values) if values else 0.0
        return (round(avg * 0.8, 4), round(min(avg * 1.2, 1.0), 4))
    n = len(values)
    boot_means = []
    for _ in range(n_bootstrap):
        sample = random.choices(values, k=n)
        boot_means.append(sum(sample) / n)
    boot_means.sort()
    lo = int(n_bootstrap * 0.025)
    hi = int(n_bootstrap * 0.975)
    return (round(boot_means[lo], 4), round(boot_means[hi], 4))

from backend.analysis.state_spec import build_rally_state, RallyState
from backend.analysis.epv_state_model import compute_rally_state_epv

# 既存の attack/quality 重みを再利用
from backend.analysis.shot_influence import _SHOT_ATTACK_WEIGHT, _SHOT_QUALITY_WEIGHT


@dataclass
class ShotInfluenceV2Result:
    """ストローク単位の状態条件付き影響度"""
    stroke_id: int | None
    stroke_num: int
    shot_type: str
    state_key: str
    state_epv: float        # ラリー開始時の EPV（状態ベースライン）
    influence_v2: float     # 状態補正後影響度
    terminal: bool          # ラリー最終打かどうか


@dataclass
class RallyInfluenceV2:
    """ラリー単位の集計"""
    rally_id: int | None
    state_key: str
    state_epv: float
    outcome: float          # 1.0=勝 / 0.0=負
    strokes: list[ShotInfluenceV2Result] = field(default_factory=list)


def compute_shot_influence_v2(
    rallies: list,
    strokes_by_rally: dict[int, list],
    role_by_match: dict[int, str],
    set_to_match: dict[int, int],
    set_num_by_set: dict[int, int],
) -> dict[str, Any]:
    """状態条件付きショット影響度を計算する。

    Parameters
    ----------
    rallies          : Rally ORM オブジェクトリスト
    strokes_by_rally : {rally_id: [Stroke ORM]}
    role_by_match    : {match_id: 'server'|'receiver'}
    set_to_match     : {set_id: match_id}
    set_num_by_set   : {set_id: set_num}

    Returns
    -------
    {
        "per_shot_type": {shot_type: avg_influence_v2},
        "state_breakdown": [
            {
                "state_key": str,
                "state_epv": float,
                "avg_influence": float,
                "n_rallies": int,
                "top_shots": [{"shot_type": str, "avg_influence": float, "n": int}]
            }
        ],
        "rally_details": [RallyInfluenceV2],  # 生データ (上限50)
        "total_rallies": int,
        "usable_rallies": int,
    }
    """
    # ── 1. EPV state テーブルを事前計算 ──
    epv_result = compute_rally_state_epv(
        rallies=rallies,
        strokes_by_rally=strokes_by_rally,
        role_by_match=role_by_match,
        set_to_match=set_to_match,
        set_num_by_set=set_num_by_set,
    )
    state_table = epv_result.get("state_table", [])
    global_win_rate: float = epv_result.get("global_win_rate", 0.5)

    # state_key → epv マップ
    epv_map: dict[str, float] = {row["state_key"]: row["epv"] for row in state_table}

    # ── 2. 各ラリーの影響度計算 ──
    rally_results: list[RallyInfluenceV2] = []
    usable = 0

    for rally in rallies:
        set_id = getattr(rally, 'set_id', None)
        match_id = set_to_match.get(set_id) if set_id else None
        if match_id is None:
            continue

        player_role = role_by_match.get(match_id, 'server')
        set_num = set_num_by_set.get(set_id, 1)

        my_score = getattr(rally, 'score_before_my', None) or 0
        opp_score = getattr(rally, 'score_before_opp', None) or 0
        won = bool(getattr(rally, 'won', False))
        outcome = 1.0 if won else 0.0

        strokes = strokes_by_rally.get(rally.id, [])
        rally_length = len(strokes)
        if rally_length == 0:
            continue

        # ラリー全体の RallyState を決定
        rally_state: RallyState = build_rally_state(
            my_score=my_score,
            opp_score=opp_score,
            set_num=set_num,
            rally_length=rally_length,
            server=(player_role == 'server'),
            player_role=player_role,
        )
        state_key = rally_state.to_key()
        state_epv = epv_map.get(state_key, global_win_rate)

        # state_credit_multiplier: アウトカムと状態期待値の差分
        # 大きいほど「状態から見て予想外の寄与」を意味する
        credit_base = outcome - state_epv  # [-1, +1]

        shot_results: list[ShotInfluenceV2Result] = []
        for i, stroke in enumerate(
            sorted(strokes, key=lambda s: getattr(s, 'stroke_num', i))
        ):
            shot_type = getattr(stroke, 'shot_type', 'other') or 'other'
            quality = getattr(stroke, 'shot_quality', 'neutral') or 'neutral'
            terminal = (i == rally_length - 1)

            position_weight = (i + 1) / rally_length
            attack_weight = _SHOT_ATTACK_WEIGHT.get(shot_type, 0.4)
            quality_weight = _SHOT_QUALITY_WEIGHT.get(quality, 1.0)

            if terminal:
                # 最終打はアウトカムを直接帰属
                influence = round(attack_weight * quality_weight * (outcome - state_epv + 0.5), 4)
            else:
                influence = round(
                    position_weight * attack_weight * quality_weight * (credit_base + 0.5),
                    4,
                )

            # クランプ: 0-1 range
            influence = max(0.0, min(1.0, influence))

            shot_results.append(ShotInfluenceV2Result(
                stroke_id=getattr(stroke, 'id', None),
                stroke_num=getattr(stroke, 'stroke_num', i + 1),
                shot_type=shot_type,
                state_key=state_key,
                state_epv=state_epv,
                influence_v2=influence,
                terminal=terminal,
            ))

        rally_results.append(RallyInfluenceV2(
            rally_id=getattr(rally, 'id', None),
            state_key=state_key,
            state_epv=state_epv,
            outcome=outcome,
            strokes=shot_results,
        ))
        usable += 1

    # ── 3. 集計 ──
    # ショット種別ごとの平均影響度
    from collections import defaultdict
    shot_type_scores: dict[str, list[float]] = defaultdict(list)
    state_shot_scores: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))

    for rv in rally_results:
        for sr in rv.strokes:
            shot_type_scores[sr.shot_type].append(sr.influence_v2)
            state_shot_scores[rv.state_key][sr.shot_type].append(sr.influence_v2)

    # ショット種別ごとの平均影響度 + Bootstrap CI
    per_shot_type = {}
    for st, scores in sorted(shot_type_scores.items(), key=lambda x: -sum(x[1]) / len(x[1])):
        avg = round(sum(scores) / len(scores), 4)
        ci_low, ci_high = _bootstrap_mean_ci(scores)
        per_shot_type[st] = {
            "avg": avg,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "n": len(scores),
        }

    # 状態別内訳
    state_breakdown = []
    state_rally_counts: dict[str, int] = defaultdict(int)
    for rv in rally_results:
        state_rally_counts[rv.state_key] += 1

    for state_key, shot_map in state_shot_scores.items():
        all_scores_for_state = [sc for scl in shot_map.values() for sc in scl]
        avg_influence = round(sum(all_scores_for_state) / len(all_scores_for_state), 4) if all_scores_for_state else 0.0
        ci_low, ci_high = _bootstrap_mean_ci(all_scores_for_state)
        top_shots = sorted(
            [
                {
                    "shot_type": st,
                    "avg_influence": round(sum(sc) / len(sc), 4),
                    "ci_low": _bootstrap_mean_ci(sc)[0],
                    "ci_high": _bootstrap_mean_ci(sc)[1],
                    "n": len(sc),
                }
                for st, sc in shot_map.items()
            ],
            key=lambda x: -x["avg_influence"],
        )[:5]
        state_breakdown.append({
            "state_key": state_key,
            "state_epv": epv_map.get(state_key, global_win_rate),
            "avg_influence": avg_influence,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "n_rallies": state_rally_counts[state_key],
            "top_shots": top_shots,
        })
    state_breakdown.sort(key=lambda x: -x["n_rallies"])

    return {
        "per_shot_type": per_shot_type,
        "state_breakdown": state_breakdown,
        "rally_details": rally_results[:50],
        "total_rallies": len(rallies),
        "usable_rallies": usable,
    }
