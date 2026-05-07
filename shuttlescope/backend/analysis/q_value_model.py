"""
q_value_model.py — 状態-行動価値モデル (Research Spine RS-2)

Q(state, action) = E[勝率 | state, action] - E[勝率 | state]

action = ショット種別
state  = RallyState（state_spec.py 定義）

設計:
  - epv_state_model の state×shot 集計を基礎とする
  - Wilson CI による信頼区間付き
  - 各 state 内でのランキング付き出力
  - 「最善手」推定（十分サンプルがある state のみ）

Note: 即時報酬のみ（将来割引なし）。因果効果ではなく相関ベース。
"""
from __future__ import annotations
from collections import defaultdict
from typing import Optional

from backend.analysis.state_spec import build_rally_state
from backend.analysis.epv_state_model import wilson_ci, reliability_score


MIN_CELL_Q = 10  # Q値推定の最低セル件数


def compute_q_values(
    rallies: list,
    strokes_by_rally: dict[int, list],
    role_by_match: dict[int, str],
    set_to_match: dict[int, int],
    set_num_by_set: dict[int, int],
    min_cell: int = MIN_CELL_Q,
) -> dict:
    """
    全ラリーから状態-行動価値テーブルを計算する。

    Returns:
        {
          "q_table": [
            {
              "state_key": str,
              "state": dict,
              "action": str (shot_type),
              "n": int,
              "wins": int,
              "q_value": float,
              "ci_low": float,
              "ci_high": float,
              "baseline_win_rate": float,
              "ranking_within_state": int,
              "reliable": bool,
            }
          ],
          "best_actions": {
            state_key: {
              "best_action": str,
              "best_q": float,
              "n_actions": int,
            }
          },
          "total_states": int,
          "total_reliable_cells": int,
        }
    """
    # 状態ごとの集計
    state_wins: dict[str, int] = defaultdict(int)
    state_total: dict[str, int] = defaultdict(int)
    state_obj: dict[str, dict] = {}

    # 状態×ショット種別集計
    state_shot_wins: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    state_shot_total: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    # rereview NEW-Q: Σw² を蓄積して effective sample size を CI 計算に反映
    state_shot_w2: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

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
        state_obj[key] = rs.to_dict()
        state_total[key] += 1
        if is_win:
            state_wins[key] += 1

        # ショット種別集計
        # analysis #2 fix: 旧コードは「最後のストロークだけを行動」として
        # クレジットしていた。勝ち rally の最終 stroke は smash 等 (決め球)、
        # 負け rally の最終 stroke は defensive/lob/clear (守備復帰) になりやすく、
        # **完全に同一戦術の 50/50 プレイヤーでも smash > defensive にランクされる**
        # アーティファクトを生んでいた (best_actions が誤推奨)。
        # 修正: 全 stroke にフラクショナル重み 1/n を割り当て、baseline と action
        # を同じ denominator にする。total/wins は float で扱う (caller 側 wilson_ci
        # は int を要求するため round 後 int 化)。
        stks = sorted(strokes_by_rally.get(rally.id, []), key=lambda x: x.stroke_num)
        player_stks = [s for s in stks if s.player == role and s.shot_type]
        if player_stks:
            n_player = len(player_stks)
            weight = 1.0 / n_player
            for s in player_stks:
                state_shot_total[key][s.shot_type] += weight
                if is_win:
                    state_shot_wins[key][s.shot_type] += weight
                # rereview NEW-Q fix: フラクショナル重みのもと Wilson CI が
                # 過小幅にならないよう、effective sample size n_eff = (Σw)²/Σw² を
                # 後段で計算するために Σw² を蓄積する。
                state_shot_w2.setdefault(key, defaultdict(float))[s.shot_type] += weight * weight

    # Q値テーブル構築
    q_table: list[dict] = []
    best_actions: dict[str, dict] = {}
    total_reliable = 0

    for key in state_obj:
        s_n = state_total[key]
        s_wins = state_wins[key]
        baseline = round(s_wins / s_n, 4) if s_n else 0.5

        state_q_entries = []
        for shot_type, sn_f in state_shot_total[key].items():
            # フラクショナル重みのもと、点推定 q_val は素直に Σw_win/Σw、
            # CI は effective sample size n_eff = (Σw)² / Σw² で計算する
            # (rereview NEW-Q fix: フラクショナル重みでの分散膨張を反映)。
            sw_f = state_shot_wins[key].get(shot_type, 0.0)
            w2 = state_shot_w2[key].get(shot_type, 0.0)
            n_eff = (sn_f * sn_f / w2) if w2 > 0 else 0.0
            swr = round(sw_f / sn_f, 4) if sn_f > 0 else baseline
            q_val = round(swr - baseline, 4)
            n_eff_int = int(round(n_eff))
            sw_eff_int = int(round(swr * n_eff_int))
            sn = n_eff_int
            sw = sw_eff_int
            ci_low, ci_high = wilson_ci(sw, sn)
            reliable = sn >= min_cell

            if reliable:
                total_reliable += 1

            state_q_entries.append({
                "state_key": key,
                "state": state_obj[key],
                "action": shot_type,
                "n": sn,
                "wins": sw,
                "q_value": q_val,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "baseline_win_rate": baseline,
                "reliable": reliable,
            })

        # state 内ランキング（q_value 降順）
        state_q_entries.sort(key=lambda x: x["q_value"], reverse=True)
        for rank, entry in enumerate(state_q_entries, 1):
            entry["ranking_within_state"] = rank
            q_table.append(entry)

        # 最善手（reliable なものの中から最高 q_value）
        reliable_entries = [e for e in state_q_entries if e["reliable"]]
        if reliable_entries:
            best = reliable_entries[0]
            best_actions[key] = {
                "state": state_obj[key],
                "best_action": best["action"],
                "best_q": best["q_value"],
                "best_q_ci_low": best["ci_low"],
                "best_q_ci_high": best["ci_high"],
                "n_actions": len(state_q_entries),
                "n_reliable_actions": len(reliable_entries),
            }

    # 全体 q_value 降順でソート（同一 state は内部順序維持）
    q_table.sort(key=lambda x: (x["state_key"], x["ranking_within_state"]))

    return {
        "q_table": q_table,
        "best_actions": best_actions,
        "total_states": len(state_obj),
        "total_reliable_cells": total_reliable,
    }


def summarize_best_actions(best_actions: dict[str, dict]) -> list[dict]:
    """
    best_actions を Q値の高い順にリストとして返す。
    フロントエンドのテーブル表示に使用。
    """
    result = list(best_actions.values())
    result.sort(key=lambda x: x["best_q"], reverse=True)
    return result
