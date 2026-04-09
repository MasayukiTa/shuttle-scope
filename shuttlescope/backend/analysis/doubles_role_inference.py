"""
doubles_role_inference.py — ダブルスロール推定 (Research Spine RS-5, DB-1 フェーズ)

フェーズ:
  DB-1（本実装）: ルールベースのロール推定 + 信頼スコア
  DB-2（将来）: HMM + スムージング
  DB-3（将来）: ロール条件付き価値モデル

ロール定義:
  front: 前衛（ネット付近）— net_shot / drop / push_rush / cross_net 優位
  back:  後衛（バックコート）— smash / clear / lob / drive 優位
  mixed: 混合（切り替えあり）

推定根拠（DB-1）:
  - ショット種別の比率からルールベースでロールを判定
  - ラリー内打球番号（早い番号 → 前衛受けが多い）
  - confidence_score: フロント・バックへの偏りの強さ
"""
from __future__ import annotations
from collections import defaultdict
from typing import Optional


# ── ショット種別のロール重み ────────────────────────────────────────────────

FRONT_SHOTS = {"net_shot", "cross_net", "push_rush", "drop", "short_service", "block"}
BACK_SHOTS = {"smash", "half_smash", "clear", "lob", "long_service", "drive", "defensive", "slice"}
NEUTRAL_SHOTS = {"flick", "around_head", "other"}

# ロール判定閾値
ROLE_THRESHOLD = 0.60   # 60%以上でロール確定
MIN_SHOTS_ROLE = 20     # 最低ショット数


def classify_role_from_shots(
    front_count: int,
    back_count: int,
    total: int,
) -> tuple[str, float]:
    """
    フロント・バックショット比率からロールと信頼スコアを返す。
    Returns: (role, confidence_score)
    """
    if total < MIN_SHOTS_ROLE:
        return ("unknown", 0.0)
    front_ratio = front_count / total
    back_ratio = back_count / total
    if front_ratio >= ROLE_THRESHOLD:
        return ("front", round(front_ratio, 4))
    if back_ratio >= ROLE_THRESHOLD:
        return ("back", round(back_ratio, 4))
    return ("mixed", round(max(front_ratio, back_ratio), 4))


# ── ラリー内ポジション推定 ───────────────────────────────────────────────────

def classify_stroke_position(stroke_num: int, shot_type: str) -> str:
    """
    ストローク番号とショット種別からポジション推定を返す。
    """
    if shot_type in FRONT_SHOTS:
        return "front"
    if shot_type in BACK_SHOTS:
        return "back"
    if stroke_num <= 2:
        return "front"  # サーブ直後は前衛受けが多い
    return "neutral"


# ── メイン計算 ───────────────────────────────────────────────────────────────

def compute_doubles_role_inference(
    rallies: list,
    strokes_by_rally: dict[int, list],
    role_by_match: dict[int, str],
    set_to_match: dict[int, int],
) -> dict:
    """
    ダブルス試合のラリーからプレイヤーのロール（前衛/後衛）を推定する。

    Returns:
        {
          "inferred_role": str,        // "front" / "back" / "mixed" / "unknown"
          "confidence_score": float,
          "front_shot_count": int,
          "back_shot_count": int,
          "total_shots": int,
          "front_shot_ratio": float,
          "back_shot_ratio": float,
          "shot_breakdown": {shot_type: int},
          "rally_position_summary": {
            "front_rallies": int,
            "back_rallies": int,
            "mixed_rallies": int,
          },
          "phase_breakdown": {
            "early_role": str,
            "mid_role": str,
            "late_role": str,
          },
        }
    """
    front_count = 0
    back_count = 0
    shot_breakdown: dict[str, int] = defaultdict(int)
    total = 0

    # ラリー内フェーズ別集計
    phase_front: dict[str, int] = {"early": 0, "mid": 0, "late": 0}
    phase_back: dict[str, int] = {"early": 0, "mid": 0, "late": 0}
    phase_total: dict[str, int] = {"early": 0, "mid": 0, "late": 0}

    # ラリー単位のポジション
    rally_front = 0
    rally_back = 0
    rally_mixed = 0

    for rally in rallies:
        mid = set_to_match.get(rally.set_id)
        if mid is None:
            continue
        role = role_by_match.get(mid)
        if not role:
            continue

        stks = sorted(strokes_by_rally.get(rally.id, []), key=lambda x: x.stroke_num)
        player_stks = [s for s in stks if s.player == role and s.shot_type]

        rally_f = 0
        rally_b = 0
        for s in player_stks:
            shot_type = s.shot_type
            shot_breakdown[shot_type] += 1
            pos = classify_stroke_position(s.stroke_num, shot_type)

            if s.stroke_num <= 3:
                phase = "early"
            elif s.stroke_num <= 7:
                phase = "mid"
            else:
                phase = "late"

            if shot_type in FRONT_SHOTS:
                front_count += 1
                rally_f += 1
                phase_front[phase] += 1
            elif shot_type in BACK_SHOTS:
                back_count += 1
                rally_b += 1
                phase_back[phase] += 1
            phase_total[phase] += 1
            total += 1

        if rally_f > rally_b * 1.5:
            rally_front += 1
        elif rally_b > rally_f * 1.5:
            rally_back += 1
        else:
            rally_mixed += 1

    role, conf = classify_role_from_shots(front_count, back_count, total)

    # フェーズ別ロール
    phase_roles = {}
    for phase in ("early", "mid", "late"):
        pt = phase_total[phase]
        if pt == 0:
            phase_roles[f"{phase}_role"] = "unknown"
        else:
            pf = phase_front[phase] / pt
            pb = phase_back[phase] / pt
            if pf >= ROLE_THRESHOLD:
                phase_roles[f"{phase}_role"] = "front"
            elif pb >= ROLE_THRESHOLD:
                phase_roles[f"{phase}_role"] = "back"
            else:
                phase_roles[f"{phase}_role"] = "mixed"

    return {
        "inferred_role": role,
        "confidence_score": conf,
        "front_shot_count": front_count,
        "back_shot_count": back_count,
        "total_shots": total,
        "front_shot_ratio": round(front_count / total, 4) if total else 0.0,
        "back_shot_ratio": round(back_count / total, 4) if total else 0.0,
        "shot_breakdown": dict(shot_breakdown),
        "rally_position_summary": {
            "front_rallies": rally_front,
            "back_rallies": rally_back,
            "mixed_rallies": rally_mixed,
        },
        "phase_breakdown": phase_roles,
    }
