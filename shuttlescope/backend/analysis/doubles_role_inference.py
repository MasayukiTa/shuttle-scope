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


# ── DB-2 HMM: Baum-Welch EM + Viterbi ───────────────────────────────────────

def _forward_scaled(
    obs_seq: list[str],
    emission: dict,
    transition: dict,
    prior: dict,
) -> tuple[list[dict], list[float]]:
    """スケーリング版フォワードアルゴリズム。数値アンダーフローを防止する。"""
    roles = list(prior.keys())
    T = len(obs_seq)
    alpha: list[dict] = [{} for _ in range(T)]
    c: list[float] = [0.0] * T  # スケーリング係数

    for r in roles:
        e = emission[r].get(obs_seq[0], emission[r].get("neutral", 1e-6))
        alpha[0][r] = prior.get(r, 1.0 / len(roles)) * e
    c[0] = max(sum(alpha[0].values()), 1e-300)
    for r in roles:
        alpha[0][r] /= c[0]

    for t in range(1, T):
        obs = obs_seq[t]
        for r in roles:
            e = emission[r].get(obs, emission[r].get("neutral", 1e-6))
            alpha[t][r] = sum(alpha[t - 1][r2] * transition[r2].get(r, 1e-6) for r2 in roles) * e
        c[t] = max(sum(alpha[t].values()), 1e-300)
        for r in roles:
            alpha[t][r] /= c[t]

    return alpha, c


def _backward_scaled(
    obs_seq: list[str],
    emission: dict,
    transition: dict,
    c: list[float],
) -> list[dict]:
    """スケーリング版バックワードアルゴリズム。"""
    roles = list(emission.keys())
    T = len(obs_seq)
    beta: list[dict] = [{} for _ in range(T)]

    for r in roles:
        beta[T - 1][r] = 1.0 / max(c[T - 1], 1e-300)

    for t in range(T - 2, -1, -1):
        obs_next = obs_seq[t + 1]
        for r in roles:
            beta[t][r] = sum(
                transition[r].get(r2, 1e-6)
                * emission[r2].get(obs_next, emission[r2].get("neutral", 1e-6))
                * beta[t + 1][r2]
                for r2 in roles
            ) / max(c[t], 1e-300)

    return beta


def _baum_welch_update(
    per_rally_obs: list[list[str]],
    emission: dict,
    transition: dict,
    prior: dict,
    n_iter: int = 5,
) -> tuple[dict, dict]:
    """
    Baum-Welch EM 更新（スケーリング版）。

    各ラリーのストロークシーケンスを使って HMM パラメータを更新する。
    シーケンス数が少ない場合は更新せずに元のパラメータを返す。

    Returns:
        (updated_emission, updated_transition)
    """
    import copy

    roles = list(prior.keys())
    obs_symbols = ["front", "back", "neutral"]

    em = copy.deepcopy(emission)
    tr = copy.deepcopy(transition)

    valid_seqs = [s for s in per_rally_obs if len(s) >= 2]
    if len(valid_seqs) < 10:
        # データ不足: 元のパラメータをそのまま返す
        return em, tr

    for _ in range(n_iter):
        # 累積統計量
        xi_sum = {r: {r2: 1e-9 for r2 in roles} for r in roles}
        emit_num = {r: {o: 1e-9 for o in obs_symbols} for r in roles}
        emit_den = {r: 1e-9 for r in roles}

        for obs_seq in valid_seqs:
            T = len(obs_seq)
            alpha, c_arr = _forward_scaled(obs_seq, em, tr, prior)
            beta = _backward_scaled(obs_seq, em, tr, c_arr)

            # gamma: P(q_t=r | obs)
            for t in range(T):
                total_g = sum(alpha[t][r] * beta[t][r] for r in roles)
                if total_g < 1e-300:
                    continue
                for r in roles:
                    g = alpha[t][r] * beta[t][r] / total_g
                    obs_sym = obs_seq[t] if obs_seq[t] in obs_symbols else "neutral"
                    emit_num[r][obs_sym] += g
                    emit_den[r] += g

            # xi: P(q_t=r, q_{t+1}=r2 | obs)
            for t in range(T - 1):
                obs_next = obs_seq[t + 1] if obs_seq[t + 1] in obs_symbols else "neutral"
                xi_t: dict[str, dict[str, float]] = {r: {} for r in roles}
                total_xi = 0.0
                for r in roles:
                    for r2 in roles:
                        v = (
                            alpha[t][r]
                            * tr[r].get(r2, 1e-6)
                            * em[r2].get(obs_next, em[r2].get("neutral", 1e-6))
                            * beta[t + 1][r2]
                        )
                        xi_t[r][r2] = v
                        total_xi += v
                if total_xi > 1e-300:
                    for r in roles:
                        for r2 in roles:
                            xi_sum[r][r2] += xi_t[r][r2] / total_xi

        # M-step: 遷移確率の更新
        for r in roles:
            denom = sum(xi_sum[r][r2] for r2 in roles)
            if denom > 1e-9:
                for r2 in roles:
                    tr[r][r2] = xi_sum[r][r2] / denom

        # M-step: 発射確率の更新
        for r in roles:
            if emit_den[r] > 1e-9:
                for o in obs_symbols:
                    em[r][o] = emit_num[r][o] / emit_den[r]

    return em, tr


# ── DB-3: ロール安定性スコア ──────────────────────────────────────────────────

def compute_doubles_role_stability(
    matches: list,
    rallies: list,
    strokes_by_rally: dict[int, list],
    role_by_match: dict[int, str],
    set_to_match: dict[int, int],
) -> dict:
    """
    DB-3: 試合・シーズン単位のロール安定性スコアを計算する。

    試合ごとに独立してロールを推定し、試合間の一貫性を測定する。

    Returns:
        {
          "role_stability_score": float,       # 0-1, 高いほど一貫
          "dominant_role": str,
          "n_matches_analyzed": int,
          "per_match_roles": list,
          "season_variation": list,
          "consistency_label": str,            # "consistent" | "moderate" | "volatile"
          "note": str | None,
        }
    """
    from collections import Counter

    # set_id → match_id マップからラリーを試合ごとに分類
    rally_by_match: dict[int, list] = {}
    for rally in rallies:
        mid = set_to_match.get(rally.set_id)
        if mid is not None:
            rally_by_match.setdefault(mid, []).append(rally)

    per_match_roles = []
    for match in matches:
        mid = match.id
        role = role_by_match.get(mid)
        match_rallies = rally_by_match.get(mid, [])
        if not role or not match_rallies:
            continue

        f, b, n, total = 0, 0, 0, 0
        for r in match_rallies:
            for s in strokes_by_rally.get(r.id, []):
                if s.player != role or not s.shot_type:
                    continue
                if s.shot_type in FRONT_SHOTS:
                    f += 1
                elif s.shot_type in BACK_SHOTS:
                    b += 1
                else:
                    n += 1
                total += 1

        if total < 5:
            continue

        inferred, conf = classify_role_from_shots(f, b, total)
        match_date = getattr(match, "match_date", None) or getattr(match, "date", None)
        season = str(match_date.year) if match_date else "unknown"

        per_match_roles.append({
            "match_id": mid,
            "inferred_role": inferred,
            "confidence": conf,
            "n_shots": total,
            "season": season,
        })

    if not per_match_roles:
        return {
            "role_stability_score": 0.0,
            "dominant_role": "unknown",
            "n_matches_analyzed": 0,
            "per_match_roles": [],
            "season_variation": [],
            "consistency_label": "insufficient_data",
            "note": "試合ごとのロール推定に十分なデータがありません（各試合5打以上必要）。",
        }

    role_counter = Counter(r["inferred_role"] for r in per_match_roles)
    dominant_role = role_counter.most_common(1)[0][0]
    n_consistent = role_counter[dominant_role]
    n_total = len(per_match_roles)
    stability_score = round(n_consistent / n_total, 4)

    if stability_score >= 0.75:
        consistency_label = "consistent"
    elif stability_score >= 0.50:
        consistency_label = "moderate"
    else:
        consistency_label = "volatile"

    # シーズン別集計
    season_data: dict[str, list] = {}
    for r in per_match_roles:
        season_data.setdefault(r["season"], []).append(r["inferred_role"])

    season_variation = []
    for season, role_list in sorted(season_data.items()):
        sc = Counter(role_list)
        dominant = sc.most_common(1)[0][0]
        season_variation.append({
            "season": season,
            "dominant_role": dominant,
            "n_matches": len(role_list),
            "role_counts": dict(sc),
        })

    note = None
    if consistency_label == "volatile":
        note = "試合ごとにロールが大きく変動しています。ポジションが固定されていない可能性があります。"
    elif n_total < 5:
        note = f"試合数が少ないため（{n_total}試合）、安定性スコアの信頼性が低いです。"

    return {
        "role_stability_score": stability_score,
        "dominant_role": dominant_role,
        "n_matches_analyzed": n_total,
        "per_match_roles": per_match_roles,
        "season_variation": season_variation,
        "consistency_label": consistency_label,
        "note": note,
    }


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

    # ── ステップ2: Baum-Welch EM でパラメータを学習 ──
    # シーケンス数が十分な場合は Baum-Welch で更新、不足時はルールベース初期値を使用
    if len(per_rally_obs) >= 10:
        emission, transition = _baum_welch_update(
            per_rally_obs, _HMM_EMISSION_INIT, _HMM_TRANSITION_INIT, _HMM_PRIOR, n_iter=5
        )
    else:
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

    bw_used = len(per_rally_obs) >= 10
    note = None
    if n < MIN_SHOTS_ROLE:
        note = f"ショット数が少なすぎます（{n}打）。HMM推定の精度が低い可能性があります。"
    elif n_transitions > total_decoded * 0.4:
        note = "ロール切り替えが多いです。ポジションが流動的な選手の可能性があります。"
    if bw_used:
        note = (note or "") + "（Baum-Welch EM でパラメータ学習済み）"

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
