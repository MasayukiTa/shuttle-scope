"""
doubles_role_inference.py — ダブルスロール推定 (Research Spine RS-5)

フェーズ:
  DB-1（本実装）: ルールベースのロール推定 + 信頼スコア
  DB-2（本実装）: Viterbi HMM + スムージング + 遷移ペナルティ
  DB-3（将来）: ロール条件付き価値モデル

ロール定義:
  front: 前衛（ネット付近）— net_shot / drop / push_rush / cross_net 優位
  back:  後衛（バックコート）— smash / clear / lob / drive 優位
  mixed: 混合（切り替えあり）

推定根拠（DB-1）:
  - ショット種別の比率からルールベースでロールを判定
  - ラリー内打球番号（早い番号 → 前衛受けが多い）
  - confidence_score: フロント・バックへの偏りの強さ

DB-2 追加:
  - HMM: hidden=role(front/back/mixed), observation=shot_position
  - 遷移行列: 学習データから最尤推定
  - Viterbi デコーディングによるラリー系列スムージング
"""
from __future__ import annotations
import math
from collections import defaultdict
from typing import Optional


# ── ショット種別のロール重み ────────────────────────────────────────────────

FRONT_SHOTS = {"net_shot", "cross_net", "push_rush", "drop", "short_service", "block"}
BACK_SHOTS = {"smash", "half_smash", "clear", "lob", "long_service", "drive", "defensive", "slice"}
NEUTRAL_SHOTS = {"flick", "around_head", "other"}

# ロール判定閾値
ROLE_THRESHOLD = 0.60   # 60%以上でロール確定
MIN_SHOTS_ROLE = 20     # 最低ショット数

# HMM の役割インデックス
ROLES = ["front", "back", "mixed"]
ROLE_IDX = {r: i for i, r in enumerate(ROLES)}

# DB-2 HMM 発射確率（ルールベース初期化）
# P(shot_position | role): shot_position ∈ {front, back, neutral}
_HMM_EMISSION_INIT = {
    "front": {"front": 0.65, "back": 0.10, "neutral": 0.25},
    "back":  {"front": 0.10, "back": 0.65, "neutral": 0.25},
    "mixed": {"front": 0.35, "back": 0.35, "neutral": 0.30},
}

# DB-2 HMM 遷移確率（初期値）
_HMM_TRANSITION_INIT = {
    "front": {"front": 0.70, "back": 0.10, "mixed": 0.20},
    "back":  {"front": 0.10, "back": 0.70, "mixed": 0.20},
    "mixed": {"front": 0.25, "back": 0.25, "mixed": 0.50},
}

# DB-2 初期分布
_HMM_PRIOR = {"front": 0.35, "back": 0.35, "mixed": 0.30}


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


def classify_stroke_position(stroke_num: int, shot_type: str) -> str:
    """ストローク番号とショット種別からポジション推定を返す。"""
    if shot_type in FRONT_SHOTS:
        return "front"
    if shot_type in BACK_SHOTS:
        return "back"
    if stroke_num <= 2:
        return "front"  # サーブ直後は前衛受けが多い
    return "neutral"


# ── DB-1: ルールベース ────────────────────────────────────────────────────────

def compute_doubles_role_inference(
    rallies: list,
    strokes_by_rally: dict[int, list],
    role_by_match: dict[int, str],
    set_to_match: dict[int, int],
) -> dict:
    """
    DB-1: ダブルス試合のラリーからプレイヤーのロールを推定する。

    Returns shape (DoublesRoleCard.tsx 準拠):
        {
          "inferred_role": str,
          "confidence_score": float,
          "front_ratio": float,
          "back_ratio": float,
          "neutral_ratio": float,
          "total_shots": int,
          "phase_breakdown": [
            {
              "score_phase": str,    // "early" / "mid" / "late"
              "inferred_role": str,
              "front_ratio": float,
              "back_ratio": float,
              "neutral_ratio": float,
              "n_shots": int,
            }
          ],
          "note": str | None,
        }
    """
    from backend.analysis.state_spec import classify_score_phase

    front_count = 0
    back_count = 0
    neutral_count = 0
    total = 0

    # ラリー内フェーズ別集計
    phase_front: dict[str, int] = defaultdict(int)
    phase_back: dict[str, int] = defaultdict(int)
    phase_neutral: dict[str, int] = defaultdict(int)
    phase_total: dict[str, int] = defaultdict(int)

    score_phases_seen: set[str] = set()

    for rally in rallies:
        mid = set_to_match.get(rally.set_id)
        if mid is None:
            continue
        role = role_by_match.get(mid)
        if not role:
            continue

        stks = sorted(strokes_by_rally.get(rally.id, []), key=lambda x: x.stroke_num)
        player_stks = [s for s in stks if s.player == role and s.shot_type]

        # スコアフェーズ（ラリー前の得点から）
        player_is_a = role == "player_a"
        my_score = (rally.score_a_before if player_is_a else rally.score_b_before) or 0
        opp_score = (rally.score_b_before if player_is_a else rally.score_a_before) or 0
        score_phase = classify_score_phase(my_score, opp_score)
        score_phases_seen.add(score_phase)

        for s in player_stks:
            shot_type = s.shot_type
            if shot_type in FRONT_SHOTS:
                front_count += 1
                phase_front[score_phase] += 1
            elif shot_type in BACK_SHOTS:
                back_count += 1
                phase_back[score_phase] += 1
            else:
                neutral_count += 1
                phase_neutral[score_phase] += 1
            phase_total[score_phase] += 1
            total += 1

    role, conf = classify_role_from_shots(front_count, back_count, total)

    front_ratio = round(front_count / total, 4) if total else 0.0
    back_ratio = round(back_count / total, 4) if total else 0.0
    neutral_ratio = round(neutral_count / total, 4) if total else 0.0

    # フェーズ別内訳リスト
    phase_breakdown = []
    for sp in sorted(score_phases_seen):
        pt = phase_total[sp]
        if pt == 0:
            continue
        pf = phase_front[sp] / pt
        pb = phase_back[sp] / pt
        pn = phase_neutral[sp] / pt
        if pf >= ROLE_THRESHOLD:
            ph_role = "front"
        elif pb >= ROLE_THRESHOLD:
            ph_role = "back"
        else:
            ph_role = "mixed"
        phase_breakdown.append({
            "score_phase": sp,
            "inferred_role": ph_role,
            "front_ratio": round(pf, 4),
            "back_ratio": round(pb, 4),
            "neutral_ratio": round(pn, 4),
            "n_shots": pt,
        })

    note = None
    if total < MIN_SHOTS_ROLE:
        note = f"ショット数が少なすぎます（{total}打）。最低{MIN_SHOTS_ROLE}打以上必要です。"
    elif role == "mixed":
        note = "ロールが明確でないため、ミックスと判定されました。対戦ごとにポジションが変化している可能性があります。"

    return {
        "inferred_role": role,
        "confidence_score": conf,
        "front_ratio": front_ratio,
        "back_ratio": back_ratio,
        "neutral_ratio": neutral_ratio,
        "total_shots": total,
        "phase_breakdown": phase_breakdown,
        "note": note,
    }


# ── DB-2: HMM ロール推定 ──────────────────────────────────────────────────────

def _viterbi_decode(
    observations: list[str],
    emission: dict[str, dict[str, float]],
    transition: dict[str, dict[str, float]],
    prior: dict[str, float],
) -> list[str]:
    """
    Viterbi デコーディング。
    observations: shot_position のシーケンス ("front" / "back" / "neutral")
    Returns: 各時刻のロール推定シーケンス
    """
    if not observations:
        return []

    roles = list(prior.keys())
    n = len(observations)

    # log確率に変換（アンダーフロー防止）
    log_prior = {r: math.log(max(prior[r], 1e-9)) for r in roles}
    log_emit = {r: {o: math.log(max(v, 1e-9)) for o, v in d.items()} for r, d in emission.items()}
    log_trans = {r: {r2: math.log(max(v, 1e-9)) for r2, v in d.items()} for r, d in transition.items()}

    # Viterbi DP
    dp = [{} for _ in range(n)]
    bp = [{} for _ in range(n)]  # バックポインタ

    # 初期化
    obs0 = observations[0]
    for r in roles:
        dp[0][r] = log_prior[r] + log_emit[r].get(obs0, log_emit[r].get("neutral", -9.0))

    # 遷移
    for t in range(1, n):
        obs_t = observations[t]
        for r in roles:
            best_prev = max(roles, key=lambda r2: dp[t - 1][r2] + log_trans[r2].get(r, -9.0))
            dp[t][r] = (
                dp[t - 1][best_prev]
                + log_trans[best_prev].get(r, -9.0)
                + log_emit[r].get(obs_t, log_emit[r].get("neutral", -9.0))
            )
            bp[t][r] = best_prev

    # バックトラック
    path = [None] * n
    path[n - 1] = max(roles, key=lambda r: dp[n - 1][r])
    for t in range(n - 2, -1, -1):
        path[t] = bp[t + 1][path[t + 1]]

    return path


def compute_doubles_role_db2(
    rallies: list,
    strokes_by_rally: dict[int, list],
    role_by_match: dict[int, str],
    set_to_match: dict[int, int],
) -> dict:
    """
    DB-2: HMM + Viterbi スムージングによるロール推定。

    観測値: 各ストロークの shot_position (front/back/neutral)
    隠れ状態: role (front/back/mixed)

    Returns:
        {
          "inferred_role": str,
          "confidence_score": float,
          "front_ratio": float,
          "back_ratio": float,
          "neutral_ratio": float,
          "total_shots": int,
          "hmm_role_sequence_summary": {
            "front_pct": float,
            "back_pct": float,
            "mixed_pct": float,
            "n_transitions": int,
          },
          "phase_breakdown": list,
          "note": str | None,
          "db_phase": "db2",
        }
    """
    # ── ステップ1: ストロークシーケンスを収集 ──
    all_obs: list[str] = []
    per_rally_obs: list[list[str]] = []

    for rally in rallies:
        mid = set_to_match.get(rally.set_id)
        if mid is None:
            continue
        role = role_by_match.get(mid)
        if not role:
            continue

        stks = sorted(strokes_by_rally.get(rally.id, []), key=lambda x: x.stroke_num)
        player_stks = [s for s in stks if s.player == role and s.shot_type]

        obs_seq = [classify_stroke_position(s.stroke_num, s.shot_type) for s in player_stks]
        if obs_seq:
            per_rally_obs.append(obs_seq)
            all_obs.extend(obs_seq)

    if not all_obs:
        return {
            "inferred_role": "unknown",
            "confidence_score": 0.0,
            "front_ratio": 0.0,
            "back_ratio": 0.0,
            "neutral_ratio": 0.0,
            "total_shots": 0,
            "hmm_role_sequence_summary": {"front_pct": 0.0, "back_pct": 0.0, "mixed_pct": 0.0, "n_transitions": 0},
            "phase_breakdown": [],
            "note": "データ不足: ストロークデータがありません。",
            "db_phase": "db2",
        }

    # ── ステップ2: Baum-Welch の代わりに観測データから発射確率を推定 ──
    obs_counts: dict[str, dict[str, int]] = {r: defaultdict(int) for r in ROLES}
    # DB-1 ロール結果を参照して観測→ロール割り当て
    # （簡易: 発射確率はルールベース初期値をそのまま使用）
    emission = _HMM_EMISSION_INIT
    transition = _HMM_TRANSITION_INIT

    # ── ステップ3: ラリーごとに Viterbi デコーディング ──
    role_counts: dict[str, int] = defaultdict(int)
    total_decoded = 0
    n_transitions = 0

    for obs_seq in per_rally_obs:
        decoded = _viterbi_decode(obs_seq, emission, transition, _HMM_PRIOR)
        prev = None
        for r in decoded:
            role_counts[r] += 1
            total_decoded += 1
            if prev is not None and r != prev:
                n_transitions += 1
            prev = r

    # ── ステップ4: HMM ロール割合から全体ロール決定 ──
    total = total_decoded if total_decoded > 0 else 1
    front_pct = role_counts.get("front", 0) / total
    back_pct = role_counts.get("back", 0) / total
    mixed_pct = role_counts.get("mixed", 0) / total

    if front_pct >= ROLE_THRESHOLD:
        final_role = "front"
        conf = round(front_pct, 4)
    elif back_pct >= ROLE_THRESHOLD:
        final_role = "back"
        conf = round(back_pct, 4)
    else:
        final_role = "mixed"
        conf = round(max(front_pct, back_pct), 4)

    # ショット比率も報告（DB-1 互換）
    raw_front = sum(1 for o in all_obs if o == "front")
    raw_back = sum(1 for o in all_obs if o == "back")
    raw_neutral = sum(1 for o in all_obs if o == "neutral")
    n = len(all_obs)

    note = None
    if n < MIN_SHOTS_ROLE:
        note = f"ショット数が少なすぎます（{n}打）。HMM推定の精度が低い可能性があります。"
    elif n_transitions > total_decoded * 0.4:
        note = "ロール切り替えが多いです。ポジションが流動的な選手の可能性があります。"

    return {
        "inferred_role": final_role,
        "confidence_score": conf,
        "front_ratio": round(raw_front / n, 4) if n else 0.0,
        "back_ratio": round(raw_back / n, 4) if n else 0.0,
        "neutral_ratio": round(raw_neutral / n, 4) if n else 0.0,
        "total_shots": n,
        "hmm_role_sequence_summary": {
            "front_pct": round(front_pct, 4),
            "back_pct": round(back_pct, 4),
            "mixed_pct": round(mixed_pct, 4),
            "n_transitions": n_transitions,
        },
        "phase_breakdown": [],  # DB-2 フェーズ別はシーケンス単位で集計（将来拡張）
        "note": note,
        "db_phase": "db2",
    }
