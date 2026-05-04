"""
epv_engine.py — State-based EPV / Shot Influence 再設計 (Stage 3-B)

改善点:
  - EPV: P(win|shot) - baseline → P(win|shot, state) - P(win|state) に拡張
  - shot_influence: ヒューリスティック固定 → state 変数（score_diff, rally_phase, momentum）考慮
  - 既存の MarkovAnalyzer / ShotInfluenceAnalyzer を破壊せず、state-based 層を追加

State 定義:
  1. score_state  : "leading" / "tied" / "trailing"（自分視点のスコア差）
  2. rally_phase  : "early"(1-3打) / "mid"(4-7打) / "late"(8+打)
  3. momentum     : "hot"(直近3ラリー中2勝以上) / "cold"(2敗以上) / "neutral"

設計原則:
  - 全関数は純粋関数（副作用なし）
  - DB アクセスなし（呼び出し元で取得したデータを受け取る）
  - state 定義が不適切でも既存 EPV を壊さない（フォールバック構造）
"""
from __future__ import annotations
from collections import defaultdict
from typing import Optional

from backend.analysis.analysis_config import AnalysisConfig


# ── State 分類 ────────────────────────────────────────────────────────────────

def classify_score_state(score_a: int, score_b: int, player_is_a: bool) -> str:
    """スコア差からリード状態を返す。"""
    my = score_a if player_is_a else score_b
    opp = score_b if player_is_a else score_a
    if my > opp:
        return "leading"
    if my < opp:
        return "trailing"
    return "tied"


def classify_rally_phase(stroke_num: int) -> str:
    """ラリー内フェーズを返す。"""
    if stroke_num <= 3:
        return "early"
    if stroke_num <= 7:
        return "mid"
    return "late"


def classify_momentum(recent_results: list[bool]) -> str:
    """直近ラリー結果リスト（True=勝利）からモメンタムを返す。"""
    if len(recent_results) < 3:
        return "neutral"
    last3 = recent_results[-3:]
    wins = sum(last3)
    if wins >= 2:
        return "hot"
    if wins <= 1:
        return "cold"
    return "neutral"


def build_state_key(score_state: str, rally_phase: str, momentum: str) -> tuple:
    """状態キーを構築。"""
    return (score_state, rally_phase, momentum)


# ── State-based EPV 計算 ──────────────────────────────────────────────────────

def compute_state_epv(
    rallies: list,
    strokes_by_rally: dict[int, list],
    role_by_match: dict[int, str],
    set_to_match: dict[int, int],
) -> dict:
    """
    State-based EPV を計算する。

    EPV(shot, state) = P(win | shot, state) - P(win | state)

    Returns:
        {
          "global_epv": {shot_type: float},       # 従来互換のグローバル EPV
          "state_epv": {                           # state 別 EPV
            state_key_str: {
              "baseline": float,
              "shots": {shot_type: {"epv": float, "count": int, "win_rate": float}},
            }
          },
          "state_summary": {                       # state 別サマリ
            "by_score_state": {...},
            "by_rally_phase": {...},
            "by_momentum": {...},
          },
        }
    """
    # グローバル統計（従来互換）
    global_shot_wins: dict[str, int] = defaultdict(int)
    global_shot_total: dict[str, int] = defaultdict(int)
    global_total_wins = 0
    global_total_rallies = 0

    # State 別統計
    state_shot_wins: dict[tuple, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    state_shot_total: dict[tuple, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    state_wins: dict[tuple, int] = defaultdict(int)
    state_total: dict[tuple, int] = defaultdict(int)

    # 次元別集計
    dim_wins: dict[str, dict[str, int]] = {
        "score_state": defaultdict(int),
        "rally_phase": defaultdict(int),
        "momentum": defaultdict(int),
    }
    dim_total: dict[str, dict[str, int]] = {
        "score_state": defaultdict(int),
        "rally_phase": defaultdict(int),
        "momentum": defaultdict(int),
    }

    # ラリーの時系列順序でモメンタムを追跡
    # set_id ごとに結果を追跡
    set_results: dict[int, list[bool]] = defaultdict(list)

    # ラリーをセット内 rally_num 順にソート
    sorted_rallies = sorted(rallies, key=lambda r: (r.set_id, r.rally_num))

    for rally in sorted_rallies:
        mid = set_to_match.get(rally.set_id)
        if mid is None:
            continue
        role = role_by_match.get(mid)
        if not role:
            continue
        player_is_a = role == "player_a"
        is_win = rally.winner == role

        stks = sorted(strokes_by_rally.get(rally.id, []), key=lambda x: x.stroke_num)
        player_stks = [s for s in stks if s.player == role and s.shot_type]

        if not player_stks:
            set_results[rally.set_id].append(is_win)
            continue

        # State 計算
        score_state = classify_score_state(
            rally.score_a_before, rally.score_b_before, player_is_a
        )
        momentum = classify_momentum(set_results[rally.set_id])

        global_total_rallies += 1
        if is_win:
            global_total_wins += 1

        for s in player_stks:
            phase = classify_rally_phase(s.stroke_num)
            state_key = build_state_key(score_state, phase, momentum)

            # グローバル
            global_shot_total[s.shot_type] += 1
            if is_win:
                global_shot_wins[s.shot_type] += 1

            # State 別
            state_shot_total[state_key][s.shot_type] += 1
            state_total[state_key] += 1
            if is_win:
                state_shot_wins[state_key][s.shot_type] += 1
                state_wins[state_key] += 1

            # 次元別
            dim_total["score_state"][score_state] += 1
            dim_total["rally_phase"][phase] += 1
            dim_total["momentum"][momentum] += 1
            if is_win:
                dim_wins["score_state"][score_state] += 1
                dim_wins["rally_phase"][phase] += 1
                dim_wins["momentum"][momentum] += 1

        set_results[rally.set_id].append(is_win)

    # グローバル EPV
    global_baseline = global_total_wins / global_total_rallies if global_total_rallies else 0.5
    global_epv = {}
    for st in global_shot_total:
        wr = global_shot_wins[st] / global_shot_total[st] if global_shot_total[st] else global_baseline
        global_epv[st] = round(wr - global_baseline, 4)

    # State 別 EPV
    state_epv: dict[str, dict] = {}
    for skey in state_total:
        s_baseline = state_wins[skey] / state_total[skey] if state_total[skey] else global_baseline
        shots_data = {}
        for st in state_shot_total[skey]:
            n = state_shot_total[skey][st]
            if n < 3:
                continue
            wr = state_shot_wins[skey].get(st, 0) / n
            shots_data[st] = {
                "epv": round(wr - s_baseline, 4),
                "count": n,
                "win_rate": round(wr, 4),
            }
        if shots_data:
            label = f"{skey[0]}_{skey[1]}_{skey[2]}"
            state_epv[label] = {
                "baseline": round(s_baseline, 4),
                "total": state_total[skey],
                "shots": shots_data,
            }

    # 次元別サマリ
    state_summary = {}
    for dim_name in ("score_state", "rally_phase", "momentum"):
        dim_data = {}
        for val in dim_total[dim_name]:
            t = dim_total[dim_name][val]
            w = dim_wins[dim_name].get(val, 0)
            dim_data[val] = {
                "win_rate": round(w / t, 4) if t else None,
                "total": t,
                "wins": w,
            }
        state_summary[f"by_{dim_name}"] = dim_data

    return {
        "global_epv": global_epv,
        "state_epv": state_epv,
        "state_summary": state_summary,
    }


# ── State-aware Shot Influence ───────────────────────────────────────────────

# ショット種別の基本攻撃力（ShotInfluenceAnalyzer と同一）
_SHOT_ATTACK_WEIGHT = {
    "smash": 0.85, "push_rush": 0.80, "half_smash": 0.75,
    "drop": 0.70, "cross_net": 0.65, "flick": 0.60,
    "net_shot": 0.55, "drive": 0.50, "slice": 0.45,
    "around_head": 0.50, "block": 0.40, "clear": 0.35,
    "lob": 0.30, "defensive": 0.25, "long_service": 0.40,
    "short_service": 0.55, "cant_reach": 0.0, "other": 0.40,
}

_QUALITY_WEIGHT = {
    "excellent": 1.5, "good": 1.2, "neutral": 1.0, "poor": 0.6,
}

# State 補正係数
_PRESSURE_MULT = {
    "leading": 0.9,   # リード時は影響度やや低く
    "tied": 1.0,       # 同点は標準
    "trailing": 1.15,  # ビハインド時は影響度やや高く
}

_PHASE_MULT = {
    "early": 0.8,   # ラリー序盤は影響小
    "mid": 1.0,     # 中盤は標準
    "late": 1.2,    # 終盤は影響大
}

_MOMENTUM_MULT = {
    "hot": 1.1,     # 好調時はやや高く
    "neutral": 1.0,
    "cold": 0.9,    # 不調時はやや低く
}


def compute_state_influence(
    strokes: list[dict],
    rally_won: bool,
    score_state: str = "tied",
    momentum: str = "neutral",
) -> list[dict]:
    """
    State を考慮したショット影響度を計算する。

    influence = position_coef × attack_weight × quality_weight
                × win_mult × pressure_mult × phase_mult × momentum_mult

    Parameters:
        strokes:     [{id, shot_type, shot_quality, stroke_num, score_diff}, ...]
        rally_won:   ラリー勝利フラグ
        score_state: "leading" / "tied" / "trailing"
        momentum:    "hot" / "neutral" / "cold"

    Returns:
        [{stroke_id, stroke_num, shot_type, influence_score, state_factors}, ...]
    """
    results = []
    n = len(strokes)
    win_mult = 1.2 if rally_won else 0.8
    pressure_m = _PRESSURE_MULT.get(score_state, 1.0)
    momentum_m = _MOMENTUM_MULT.get(momentum, 1.0)

    for i, stroke in enumerate(strokes):
        shot_type = stroke.get("shot_type", "other")
        quality = stroke.get("shot_quality") or "neutral"
        stroke_num = stroke.get("stroke_num", i + 1)

        phase = classify_rally_phase(stroke_num)
        phase_m = _PHASE_MULT.get(phase, 1.0)

        position_coef = (i + 1) / n if n > 0 else 1.0
        attack_weight = _SHOT_ATTACK_WEIGHT.get(shot_type, 0.4)
        quality_weight = _QUALITY_WEIGHT.get(quality, 1.0)

        raw = position_coef * attack_weight * quality_weight * win_mult
        state_adjusted = raw * pressure_m * phase_m * momentum_m

        results.append({
            "stroke_id": stroke.get("id"),
            "stroke_num": stroke_num,
            "shot_type": shot_type,
            "influence_score": round(min(state_adjusted, 1.0), 4),
            "influence_raw": round(min(raw, 1.0), 4),
            "state_factors": {
                "score_state": score_state,
                "rally_phase": phase,
                "momentum": momentum,
                "pressure_mult": pressure_m,
                "phase_mult": phase_m,
                "momentum_mult": momentum_m,
            },
        })

    return results
