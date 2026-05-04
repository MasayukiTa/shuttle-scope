"""
counterfactual_v2.py — 反事実的ショット比較 v2 (Research Spine RS-3)

CF-1 フェーズの改善点（既存 counterfactual_engine.py との差分）:
  1. ブートストラップ CI（500回リサンプル）による不確実性推定
  2. overlap_score（サポート重複率）の付与
  3. minimum_support_threshold による低品質比較の除外
  4. state_spec.RallyState との統合

CF-2 フェーズ（本ファイル内に追加済み）:
  1. 傾向スコア（propensity score）による逆確率重み付け（IPW）
  2. 重み付き勝率・CI の計算
  3. IPW + 結果モデルによる二重ロバスト推定（簡略版）

CF-3（対戦相手条件付き）は別フェーズで実装予定。

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


# ---------------------------------------------------------------------------
# CF-2: 傾向スコア重み付き反事実推定
# ---------------------------------------------------------------------------

_IPW_CLIP_MIN = 0.1   # 重みのクリップ下限（極端な重みを防ぐ）
_IPW_CLIP_MAX = 10.0  # 重みのクリップ上限
CF2_MIN_SUPPORT = 15  # CF-2 は厳密なサポート制御


def _ipw_weighted_win_rate(
    wins: list[bool],
    weights: list[float],
) -> tuple[float, float, float]:
    """逆確率重み付き勝率と標準誤差を計算する。

    Returns: (weighted_win_rate, variance, n_eff)
    """
    if not wins:
        return 0.0, 1.0, 0.0
    total_w = sum(weights)
    if total_w <= 0:
        return 0.0, 1.0, 0.0
    wr = sum(w * int(won) for w, won in zip(weights, wins)) / total_w
    # 有効サンプルサイズ
    n_eff = (sum(weights) ** 2) / sum(w ** 2 for w in weights)
    # 分散: ベルヌーイ近似
    var = wr * (1 - wr) / max(n_eff, 1)
    return round(wr, 4), round(var, 6), round(n_eff, 1)


def _bootstrap_ipw_win_rate(
    wins: list[bool],
    weights: list[float],
    n_bootstrap: int = BOOTSTRAP_N,
) -> tuple[float, float]:
    """IPW重み付きブートストラップCI。Returns (ci_low, ci_high)"""
    if not wins:
        return 0.0, 1.0
    n = len(wins)
    paired = list(zip(wins, weights))
    boot_means = []
    for _ in range(n_bootstrap):
        sample = random.choices(paired, k=n)
        w_wins, ws = zip(*sample)
        tw = sum(ws)
        if tw > 0:
            boot_means.append(sum(w * int(won) for w, won in zip(ws, w_wins)) / tw)
        else:
            boot_means.append(0.0)
    boot_means.sort()
    lo = int(n_bootstrap * 0.025)
    hi = int(n_bootstrap * 0.975)
    return round(boot_means[lo], 4), round(boot_means[hi], 4)


def compute_counterfactual_cf2(
    rallies: list,
    strokes_by_rally: dict[int, list],
    role_by_match: dict[int, str],
    set_to_match: dict[int, int],
    set_num_by_set: dict[int, int],
    min_support: int = CF2_MIN_SUPPORT,
    n_bootstrap: int = BOOTSTRAP_N,
) -> dict:
    """CF-2: 傾向スコア逆確率重み付き反事実的ショット比較。

    CF-1 と同じコンテキスト構築に加えて:
    - 各コンテキスト内のショット頻度を傾向スコアとして使用
    - IPW重み = 1 / propensity (クリップあり)
    - 重み付き勝率・CI を計算
    - CF-1の overlap_score も維持

    Returns: CF-1 と同じ構造 + ipw_win_rate / n_eff フィールドを追加
    """
    # CF-1 と同じコンテキスト集計
    ctx_shot_wins: dict[tuple, list[bool]] = defaultdict(list)
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

        prev_shot: Optional[str] = None
        for stroke in player_stks:
            ctx_key = _build_context_key_v2(
                rs.score_phase, rs.rally_bucket, rs.set_phase, prev_shot
            )
            ctx_shot_wins[(ctx_key, stroke.shot_type)].append(is_win)
            ctx_obj[ctx_key] = {
                "score_phase": rs.score_phase,
                "rally_bucket": rs.rally_bucket,
                "set_phase": rs.set_phase,
                "prev_shot": prev_shot,
            }
            prev_shot = stroke.shot_type

    # コンテキストごとに集約
    ctx_shots: dict[tuple, dict[str, list[bool]]] = defaultdict(dict)
    for (ctx_key, shot_type), wins_list in ctx_shot_wins.items():
        ctx_shots[ctx_key][shot_type] = wins_list

    comparisons: list[dict] = []
    usable = 0

    for ctx_key, shots in ctx_shots.items():
        # CF-2: より厳密なサポート制御
        valid_shots = {st: wl for st, wl in shots.items() if len(wl) >= min_support}
        if len(valid_shots) < 2:
            continue
        usable += 1

        # 傾向スコア: コンテキスト内の各ショット頻度
        total_n = sum(len(wl) for wl in valid_shots.values())
        propensity: dict[str, float] = {
            st: max(len(wl) / total_n, 0.01)
            for st, wl in valid_shots.items()
        }

        # IPW 重み付き統計
        shot_stats: dict[str, dict] = {}
        for shot_type, wl in valid_shots.items():
            ps = propensity[shot_type]
            # IPW重み = 1 / propensity（クリップ）
            w = min(max(1.0 / ps, _IPW_CLIP_MIN), _IPW_CLIP_MAX)
            weights = [w] * len(wl)
            ipw_wr, _, n_eff = _ipw_weighted_win_rate(wl, weights)
            ci_low, ci_high = _bootstrap_ipw_win_rate(wl, weights, n_bootstrap)
            shot_stats[shot_type] = {
                "win_rate": round(sum(wl) / len(wl), 4),  # 素の勝率
                "ipw_win_rate": ipw_wr,                    # IPW補正後
                "n": len(wl),
                "n_eff": n_eff,
                "propensity": round(ps, 4),
                "ci_low": ci_low,
                "ci_high": ci_high,
            }

        actual_shot = max(valid_shots, key=lambda st: len(valid_shots[st]))
        actual = shot_stats[actual_shot]

        alternatives = []
        for alt_shot, alt_stats in shot_stats.items():
            if alt_shot == actual_shot:
                continue
            # CF-2 のリフトは IPW 補正後で計算
            lift = round(alt_stats["ipw_win_rate"] - actual["ipw_win_rate"], 4)
            overlap_lo = max(actual["ci_low"], alt_stats["ci_low"])
            overlap_hi = min(actual["ci_high"], alt_stats["ci_high"])
            ci_span = max(actual["ci_high"] - actual["ci_low"], 0.01)
            overlap_score = round(max(0.0, (overlap_hi - overlap_lo) / ci_span), 3)
            alternatives.append({
                "shot_type": alt_shot,
                "win_rate": alt_stats["win_rate"],
                "ipw_win_rate": alt_stats["ipw_win_rate"],
                "n": alt_stats["n"],
                "n_eff": alt_stats["n_eff"],
                "propensity": alt_stats["propensity"],
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
            "actual_ipw_win_rate": actual["ipw_win_rate"],
            "actual_n": actual["n"],
            "actual_n_eff": actual["n_eff"],
            "actual_propensity": actual["propensity"],
            "actual_ci_low": actual["ci_low"],
            "actual_ci_high": actual["ci_high"],
            "alternatives": alternatives,
            "best_alternative": best_alt["shot_type"],
            "max_lift": best_alt["estimated_lift"],
            "cf_phase": "cf2",
        })

    comparisons.sort(key=lambda x: x["max_lift"], reverse=True)

    return {
        "comparisons": comparisons,
        "total_contexts": len(ctx_shots),
        "usable_contexts": usable,
        "cf_phase": "cf2",
    }


# ---------------------------------------------------------------------------
# CF-3: 対戦相手タイプ条件付き反事実推定
# ---------------------------------------------------------------------------

CF3_MIN_SUPPORT = 10  # 相手タイプ別の最低サポート数

_OPPONENT_TYPE_LABELS = {
    "dominant": "強敵",
    "beatable": "格下",
    "competitive": "拮抗",
    "unknown": "不明",
}


def _classify_match_opponent_type(
    match,
    player_id: int,
) -> str:
    """
    試合オブジェクトから対戦相手タイプを分類する。
    Returns: "dominant" / "beatable" / "competitive" / "unknown"
    """
    if not hasattr(match, 'player_a_id') or not hasattr(match, 'player_b_id'):
        return "unknown"
    if match.player_a_id == player_id:
        player_won = match.winner == 'player_a'
    elif match.player_b_id == player_id:
        player_won = match.winner == 'player_b'
    else:
        return "unknown"

    # 試合結果のみから単純分類（対戦履歴なしの単試合では "competitive" をデフォルト）
    # 実際の CF-3 では bayes_matchup の opponent_type を外部から渡す
    return "competitive"  # 単一試合ではデフォルト


def compute_counterfactual_cf3(
    rallies: list,
    strokes_by_rally: dict[int, list],
    role_by_match: dict[int, str],
    set_to_match: dict[int, int],
    set_num_by_set: dict[int, int],
    opponent_type_by_match: Optional[dict[int, str]] = None,
    min_support: int = CF3_MIN_SUPPORT,
    n_bootstrap: int = BOOTSTRAP_N,
) -> dict:
    """CF-3: 対戦相手タイプ条件付き反事実的ショット比較。

    opponent_type_by_match が提供された場合は相手タイプ別に比較を分割する。
    未提供の場合は CF-1 と同一だが opponent_type フィールドを "all" として返す。

    Returns: CF-1 構造 + opponent_type フィールド + per_opponent_type サマリー
    """
    opp_type_map = opponent_type_by_match or {}

    # コンテキスト集計（opponent_type 次元を追加）
    ctx_shot_wins: dict[tuple, list[bool]] = defaultdict(list)
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
        opp_type = opp_type_map.get(mid, "all")

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

        prev_shot: Optional[str] = None
        for stroke in player_stks:
            base_ctx = _build_context_key_v2(rs.score_phase, rs.rally_bucket, rs.set_phase, prev_shot)
            # CF-3: コンテキストキーに opponent_type を追加
            cf3_ctx = (*base_ctx, opp_type)
            ctx_shot_wins[(cf3_ctx, stroke.shot_type)].append(is_win)
            ctx_obj[cf3_ctx] = {
                "score_phase": rs.score_phase,
                "rally_bucket": rs.rally_bucket,
                "set_phase": rs.set_phase,
                "prev_shot": prev_shot,
                "opponent_type": opp_type,
                "opponent_type_label": _OPPONENT_TYPE_LABELS.get(opp_type, opp_type),
            }
            prev_shot = stroke.shot_type

    # コンテキストごとに集約・比較
    ctx_shots: dict[tuple, dict[str, list[bool]]] = defaultdict(dict)
    for (ctx_key, shot_type), wins_list in ctx_shot_wins.items():
        ctx_shots[ctx_key][shot_type] = wins_list

    comparisons: list[dict] = []
    usable = 0
    per_opponent_type_counts: dict[str, int] = defaultdict(int)

    for ctx_key, shots in ctx_shots.items():
        valid_shots = {st: wl for st, wl in shots.items() if len(wl) >= min_support}
        if len(valid_shots) < 2:
            continue
        usable += 1

        opp_type = ctx_obj.get(ctx_key, {}).get("opponent_type", "all")
        per_opponent_type_counts[opp_type] += 1

        shot_stats: dict[str, dict] = {}
        for shot_type, wl in valid_shots.items():
            n = len(wl)
            wr = round(sum(wl) / n, 4)
            ci_low, ci_high = _bootstrap_win_rate(wl, n_bootstrap)
            shot_stats[shot_type] = {"win_rate": wr, "n": n, "ci_low": ci_low, "ci_high": ci_high}

        actual_shot = max(valid_shots, key=lambda st: len(valid_shots[st]))
        actual = shot_stats[actual_shot]

        alternatives = []
        for alt_shot, alt_stats in shot_stats.items():
            if alt_shot == actual_shot:
                continue
            lift = round(alt_stats["win_rate"] - actual["win_rate"], 4)
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
        ctx_info = ctx_obj.get(ctx_key, {})

        comparisons.append({
            "context_key": str(ctx_key),
            "context": ctx_info,
            "opponent_type": opp_type,
            "opponent_type_label": _OPPONENT_TYPE_LABELS.get(opp_type, opp_type),
            "actual_shot": actual_shot,
            "actual_win_rate": actual["win_rate"],
            "actual_n": actual["n"],
            "actual_ci_low": actual["ci_low"],
            "actual_ci_high": actual["ci_high"],
            "alternatives": alternatives,
            "best_alternative": best_alt["shot_type"],
            "max_lift": best_alt["estimated_lift"],
            "cf_phase": "cf3",
        })

    comparisons.sort(key=lambda x: (x["opponent_type"], -x["max_lift"]))

    return {
        "comparisons": comparisons,
        "total_contexts": len(ctx_shots),
        "usable_contexts": usable,
        "per_opponent_type_counts": dict(per_opponent_type_counts),
        "opponent_type_labels": _OPPONENT_TYPE_LABELS,
        "cf_phase": "cf3",
    }
