"""
hazard_fatigue.py — ハザード・疲労モデル (Research Spine RS-3)

目的:
  - ロングラリー後・終盤局面での「次の失点ハザード」を推定する
  - 通常の累積勝率とは別に、「崩壊リスク帯域」を識別する
  - 実際の生理指標は使用しない（ラリー結果の時系列パターンのみ）

モデル:
  - 離散時間ハザードの簡略版
  - ウィンドウ内の失点パターンからリスクスコアを計算
  - Cox比例ハザードは未実装（フルモデルはプロモーション後）

出力:
  - hazard_next_loss: 次ラリー失点ハザード推定
  - hazard_after_long: ロングラリー後の失点ハザード
  - hazard_endgame: 終盤（18点以上）での失点ハザード
  - collapse_risk_band: "low" / "moderate" / "high" / "critical"
  - calibrated_confidence: 信頼度スコア (0〜1)
"""
from __future__ import annotations
from collections import defaultdict
from typing import Optional
import math


# ハザード判定閾値
LONG_RALLY_THRESHOLD = 8   # ロングラリーの定義（打数）
WINDOW_SIZE = 5             # 直近ウィンドウサイズ（ラリー数）
ENDGAME_SCORE = 18          # 終盤スコア閾値
MIN_SAMPLE_HAZARD = 30      # 信頼推定最低サンプル数


def _hazard_from_window(losses_in_window: int, window_size: int) -> float:
    """ウィンドウ内失点数から離散ハザードを計算。"""
    if window_size == 0:
        return 0.5
    return round(losses_in_window / window_size, 4)


def _collapse_risk_band(hazard: float) -> str:
    """ハザード値からリスク帯域を返す。"""
    if hazard < 0.35:
        return "low"
    if hazard < 0.50:
        return "moderate"
    if hazard < 0.65:
        return "high"
    return "critical"


def compute_hazard_model(
    rallies: list,
    role_by_match: dict[int, str],
    set_to_match: dict[int, int],
    set_num_by_set: dict[int, int],
) -> dict:
    """
    ラリー時系列からハザード・疲労モデルを計算する。

    Returns:
        {
          "hazard_next_loss": float,
          "hazard_after_long": float,
          "hazard_endgame": float,
          "collapse_risk_band": str,
          "calibrated_confidence": float,
          "after_long_rally": {
            "n_long_rallies": int,
            "n_loss_after_long": int,
            "loss_rate": float,
            "vs_baseline": float,
          },
          "endgame_analysis": {
            "n_endgame": int,
            "n_loss_endgame": int,
            "loss_rate": float,
            "vs_baseline": float,
          },
          "window_trend": list,  // 5ラリーウィンドウごとのハザード推移
          "total_rallies": int,
        }
    """
    # セットごとにラリーを時系列で処理
    set_rallies: dict[int, list] = defaultdict(list)
    for rally in rallies:
        set_rallies[rally.set_id].append(rally)

    all_results: list[tuple[bool, int, int, int]] = []
    # (is_win, rally_length, my_score, set_num)

    for set_id, s_rallies in set_rallies.items():
        mid = set_to_match.get(set_id)
        if mid is None:
            continue
        role = role_by_match.get(mid)
        if not role:
            continue
        player_is_a = role == "player_a"
        set_num = set_num_by_set.get(set_id, 1)

        for rally in sorted(s_rallies, key=lambda r: r.rally_num):
            my_score = rally.score_a_before if player_is_a else rally.score_b_before
            is_win = rally.winner == role
            all_results.append((is_win, rally.rally_length, my_score, set_num))

    total = len(all_results)
    if total == 0:
        return {
            "hazard_next_loss": 0.5,
            "hazard_after_long": 0.5,
            "hazard_endgame": 0.5,
            "collapse_risk_band": "moderate",
            "calibrated_confidence": 0.0,
            "after_long_rally": {"n_long_rallies": 0, "n_loss_after_long": 0, "loss_rate": 0.5, "vs_baseline": 0.0},
            "endgame_analysis": {"n_endgame": 0, "n_loss_endgame": 0, "loss_rate": 0.5, "vs_baseline": 0.0},
            "window_trend": [],
            "total_rallies": 0,
        }

    # ベースライン失点率
    total_losses = sum(1 for (w, _, _, _) in all_results if not w)
    baseline_loss_rate = round(total_losses / total, 4)

    # ロングラリー後分析
    n_after_long = 0
    n_loss_after_long = 0
    for i in range(1, len(all_results)):
        prev_win, prev_length, _, _ = all_results[i - 1]
        curr_win, _, _, _ = all_results[i]
        if prev_length >= LONG_RALLY_THRESHOLD:
            n_after_long += 1
            if not curr_win:
                n_loss_after_long += 1
    loss_after_long = round(n_loss_after_long / n_after_long, 4) if n_after_long else baseline_loss_rate

    # 終盤スコア分析
    n_endgame = sum(1 for (_, _, score, _) in all_results if score >= ENDGAME_SCORE)
    n_loss_endgame = sum(1 for (w, _, score, _) in all_results if score >= ENDGAME_SCORE and not w)
    loss_endgame = round(n_loss_endgame / n_endgame, 4) if n_endgame else baseline_loss_rate

    # 直近ウィンドウ ハザード（全試合の最後WINDOW_SIZE件）
    last_window = all_results[-WINDOW_SIZE:]
    recent_losses = sum(1 for (w, _, _, _) in last_window if not w)
    hazard_next = _hazard_from_window(recent_losses, len(last_window))

    # ウィンドウ推移（WINDOW_SIZEおきのハザード）
    window_trend = []
    for i in range(0, len(all_results), WINDOW_SIZE):
        window = all_results[i:i + WINDOW_SIZE]
        if len(window) < 2:
            continue
        w_losses = sum(1 for (w, _, _, _) in window if not w)
        w_hazard = _hazard_from_window(w_losses, len(window))
        window_trend.append({
            "window_start": i + 1,
            "window_end": i + len(window),
            "hazard": w_hazard,
            "band": _collapse_risk_band(w_hazard),
        })

    # 信頼度スコア
    confidence = round(min(1.0, total / MIN_SAMPLE_HAZARD), 3)

    # 総合ハザードは直近ウィンドウ重視
    combined_hazard = round(
        0.5 * hazard_next + 0.25 * loss_after_long + 0.25 * loss_endgame, 4
    )

    return {
        "hazard_next_loss": hazard_next,
        "hazard_after_long": loss_after_long,
        "hazard_endgame": loss_endgame,
        "combined_hazard": combined_hazard,
        "collapse_risk_band": _collapse_risk_band(combined_hazard),
        "calibrated_confidence": confidence,
        "after_long_rally": {
            "n_long_rallies": n_after_long,
            "n_loss_after_long": n_loss_after_long,
            "loss_rate": loss_after_long,
            "vs_baseline": round(loss_after_long - baseline_loss_rate, 4),
        },
        "endgame_analysis": {
            "n_endgame": n_endgame,
            "n_loss_endgame": n_loss_endgame,
            "loss_rate": loss_endgame,
            "vs_baseline": round(loss_endgame - baseline_loss_rate, 4),
        },
        "window_trend": window_trend,
        "baseline_loss_rate": baseline_loss_rate,
        "total_rallies": total,
    }
