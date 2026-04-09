"""
epv_state_model.py — 状態ベース EPV モデル (Research Spine RS-1)

state_spec.GameState / RallyState を使って:
  - 状態ごとのベースライン勝率を推定
  - 状態ごとのショット EPV（P(win|shot,state) - P(win|state)）を計算
  - Wilson CI による信頼区間を付与
  - 状態テーブル・状態マップ形式で出力

既存の epv_engine.py とは独立。epv_engine は後方互換性のため維持。
"""
from __future__ import annotations
import math
from collections import defaultdict
from typing import Optional

from backend.analysis.state_spec import (
    RallyState, build_rally_state,
    GameState, build_game_state,
    classify_player_role,
)


# ── Wilson 信頼区間 ──────────────────────────────────────────────────────────

def wilson_ci(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """
    Wilson スコア法による比率の信頼区間。
    Returns (ci_low, ci_high) in [0, 1].
    """
    if n == 0:
        return (0.0, 1.0)
    p_hat = successes / n
    denominator = 1 + z * z / n
    center = (p_hat + z * z / (2 * n)) / denominator
    margin = (z * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n))) / denominator
    return (round(max(0.0, center - margin), 4), round(min(1.0, center + margin), 4))


def reliability_score(n: int, min_n: int = 30) -> float:
    """サンプルサイズから信頼性スコア (0〜1) を返す。"""
    return round(min(1.0, n / min_n), 3)


# ── Rally-level State EPV 計算 ───────────────────────────────────────────────

def compute_rally_state_epv(
    rallies: list,
    strokes_by_rally: dict[int, list],
    role_by_match: dict[int, str],
    set_to_match: dict[int, int],
    set_num_by_set: dict[int, int],
    min_cell: int = 10,
) -> dict:
    """
    ラリー単位の RallyState ごとに EPV を計算する。

    Parameters:
        rallies: Rally ORM オブジェクトのリスト
        strokes_by_rally: rally.id → [Stroke, ...] のマップ
        role_by_match: match.id → "player_a" / "player_b" のマップ
        set_to_match: set.id → match.id のマップ
        set_num_by_set: set.id → set_num のマップ
        min_cell: 信頼推定に必要な最低セル件数

    Returns:
        {
          "state_table": [
            {
              "state": {...},
              "state_key": str,
              "n": int,
              "wins": int,
              "win_rate": float,
              "ci_low": float,
              "ci_high": float,
              "reliability": float,
              "shots": {
                shot_type: {
                  "n": int,
                  "wins": int,
                  "win_rate": float,
                  "epv": float,
                  "ci_low": float,
                  "ci_high": float,
                }
              }
            }
          ],
          "global_win_rate": float,
          "total_rallies": int,
          "total_shots_by_state": int,
        }
    """
    # 状態ごとの集計
    state_wins: dict[str, int] = defaultdict(int)
    state_total: dict[str, int] = defaultdict(int)
    state_obj: dict[str, RallyState] = {}

    # 状態×ショット種別集計
    state_shot_wins: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    state_shot_total: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    global_wins = 0
    global_total = 0

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
        key = rs.to_key()
        state_obj[key] = rs
        state_total[key] += 1
        if is_win:
            state_wins[key] += 1

        global_total += 1
        if is_win:
            global_wins += 1

        # ショット種別集計（プレイヤーのショットのみ）
        stks = sorted(strokes_by_rally.get(rally.id, []), key=lambda x: x.stroke_num)
        for s in stks:
            if s.player == role and s.shot_type:
                state_shot_total[key][s.shot_type] += 1
                if is_win:
                    state_shot_wins[key][s.shot_type] += 1

    global_win_rate = round(global_wins / global_total, 4) if global_total else 0.5

    # 状態テーブル構築
    state_table = []
    for key, rs in state_obj.items():
        n = state_total[key]
        wins = state_wins[key]
        wr = round(wins / n, 4) if n else global_win_rate
        ci_low, ci_high = wilson_ci(wins, n)

        shots: dict[str, dict] = {}
        for st, sn in state_shot_total[key].items():
            if sn < 3:
                continue
            sw = state_shot_wins[key].get(st, 0)
            swr = round(sw / sn, 4)
            s_ci_low, s_ci_high = wilson_ci(sw, sn)
            shots[st] = {
                "n": sn,
                "wins": sw,
                "win_rate": swr,
                "epv": round(swr - wr, 4),
                "ci_low": s_ci_low,
                "ci_high": s_ci_high,
            }

        state_table.append({
            "state": rs.to_dict(),
            "state_key": key,
            "n": n,
            "wins": wins,
            "win_rate": wr,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "reliability": reliability_score(n),
            "shots": shots,
        })

    # n 降順でソート
    state_table.sort(key=lambda x: x["n"], reverse=True)

    return {
        "state_table": state_table,
        "global_win_rate": global_win_rate,
        "total_rallies": global_total,
    }


def compute_epv_state_map(state_table: list[dict]) -> list[dict]:
    """
    state_table から状態マップ表示用データを構築する。

    Returns:
        ステートキーごとのサマリ（ win_rate・reliability・上位EPVショット）
    """
    result = []
    for row in state_table:
        top_shots = sorted(
            [(st, d["epv"]) for st, d in row["shots"].items() if d["n"] >= 5],
            key=lambda x: x[1],
            reverse=True,
        )[:3]
        result.append({
            "state_key": row["state_key"],
            "state": row["state"],
            "n": row["n"],
            "win_rate": row["win_rate"],
            "ci_low": row["ci_low"],
            "ci_high": row["ci_high"],
            "reliability": row["reliability"],
            "top_epv_shots": [{"shot_type": st, "epv": epv} for st, epv in top_shots],
        })
    return result
