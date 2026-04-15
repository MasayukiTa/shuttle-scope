"""コンディション × 試合パフォーマンス解析（Phase 3）。

Phase 3 スコープ:
- 相関解析（コンディション指標 × 試合指標）
- ベストパフォーマンスプロファイル算出
- InBody × メンタル乖離検出（coach/analyst のみ UI 公開）
- 選手向け growth-oriented インサイト

本モジュールは純関数・副作用なし。DB I/O は router 側が行い、ここには
dict/list を渡す。`conditions` は Phase 2 `_full_dict` 相当、`matches` は
`{id, date, result, player_a_id, player_b_id}` を最低限持つ dict の list。

プロダクトルール（CLAUDE.md）:
- 選手向け文言は「〜が通常以上のとき伸びる」（growth-oriented）に限定
- 「弱い」「悪い」「苦手」等のネガ表記は文言から禁止
- i18n キーのみ返し、日本語文字列は backend に置かない
"""
from __future__ import annotations

import math
from datetime import date as _date, datetime, timedelta
from statistics import mean, pstdev
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# 基本統計
# ─────────────────────────────────────────────────────────────────────────────


def pearson(
    xs: Sequence[float], ys: Sequence[float]
) -> Tuple[Optional[float], Optional[float]]:
    """Pearson 相関係数と近似 p 値を返す。サンプル < 3 → (None, None)。

    p 値は t = r * sqrt((n-2)/(1-r^2)) を両側 t 分布で近似。学術用途ではなく
    UI 表示向けの粗い近似として、`math.erfc` を用いた正規近似を利用する。
    """
    if xs is None or ys is None:
        return None, None
    n = min(len(xs), len(ys))
    if n < 3:
        return None, None
    xs = list(xs)[:n]
    ys = list(ys)[:n]
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx2 = sum((x - mx) ** 2 for x in xs)
    dy2 = sum((y - my) ** 2 for y in ys)
    if dx2 <= 0 or dy2 <= 0:
        return None, None
    r = num / math.sqrt(dx2 * dy2)
    # clamp
    r = max(-1.0, min(1.0, r))
    if abs(r) >= 0.9999:
        return r, 0.0
    # 近似 p 値（正規近似）
    t = r * math.sqrt((n - 2) / max(1e-12, (1 - r * r)))
    # 両側
    p = math.erfc(abs(t) / math.sqrt(2))
    return r, p


def _parse_date(v: Any) -> Optional[_date]:
    if v is None:
        return None
    if isinstance(v, _date) and not isinstance(v, datetime):
        return v
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, str):
        try:
            return _date.fromisoformat(v[:10])
        except ValueError:
            return None
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 試合指標ヘルパ
# ─────────────────────────────────────────────────────────────────────────────


def _match_won_by_player(match: Dict[str, Any], player_id: int) -> Optional[bool]:
    """match.result は player_a 視点。player_id が a/b で反転。不明は None。"""
    result = match.get("result")
    if result not in ("win", "loss"):
        return None
    is_a = match.get("player_a_id") == player_id or match.get("partner_a_id") == player_id
    is_b = match.get("player_b_id") == player_id or match.get("partner_b_id") == player_id
    if not (is_a or is_b):
        return None
    if is_a:
        return result == "win"
    return result == "loss"


def _win_rate(matches: Iterable[Dict[str, Any]], player_id: int) -> Optional[float]:
    wins = 0
    n = 0
    for m in matches:
        w = _match_won_by_player(m, player_id)
        if w is None:
            continue
        n += 1
        if w:
            wins += 1
    if n == 0:
        return None
    return wins / n


# ─────────────────────────────────────────────────────────────────────────────
# condition ↔ match join
# ─────────────────────────────────────────────────────────────────────────────


def join_condition_match(
    conditions: Sequence[Dict[str, Any]],
    matches: Sequence[Dict[str, Any]],
    window_days: int = 3,
) -> List[Dict[str, Any]]:
    """各 condition に ±window_days 以内の試合群を紐付け、勝率を条件側に付与。

    返却: conditions の浅い copy に下記を付与した list
      - nearby_matches: list of match dicts
      - nearby_win_rate: float|None
      - nearby_match_count: int
    """
    result: List[Dict[str, Any]] = []
    for c in conditions:
        md = _parse_date(c.get("measured_at"))
        pid = c.get("player_id")
        nearby: List[Dict[str, Any]] = []
        if md is not None and pid is not None:
            for m in matches:
                mdate = _parse_date(m.get("date"))
                if mdate is None:
                    continue
                if abs((mdate - md).days) <= window_days:
                    if _match_won_by_player(m, pid) is None:
                        continue
                    nearby.append(m)
        wr = _win_rate(nearby, pid) if pid is not None else None
        out = dict(c)
        out["nearby_matches"] = nearby
        out["nearby_match_count"] = len(nearby)
        out["nearby_win_rate"] = wr
        result.append(out)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 相関シリーズ
# ─────────────────────────────────────────────────────────────────────────────


CONDITION_KEYS = {
    "ccs_score", "total_score", "f1_physical", "f2_stress", "f3_mood",
    "f4_motivation", "f5_sleep_life", "hooper_index", "session_load",
    "weight_kg", "muscle_mass_kg", "body_fat_pct", "ecw_ratio",
    "sleep_hours", "delta_prev", "delta_3ma", "delta_28ma", "z_score",
}

MATCH_METRIC_KEYS = {"win_rate"}
UNIMPLEMENTED_METRIC_KEYS = {"unforced_error_rate", "late_rally_loss_rate"}


def _confidence_note(n: int) -> str:
    if n < 10:
        return "condition.note.sample_small"  # i18n: "N<10 は参考値"
    if n >= 30:
        return "condition.note.sample_reliable"  # i18n: "N≥30 は信頼可"
    return "condition.note.sample_medium"


def correlation_series(
    conditions: Sequence[Dict[str, Any]],
    matches: Sequence[Dict[str, Any]],
    x_key: str,
    y_key: str,
    window_days: int = 3,
) -> Dict[str, Any]:
    """x=condition 指標、y=condition or 試合指標 の散布点列と Pearson r を返す。"""
    if y_key in UNIMPLEMENTED_METRIC_KEYS:
        return {
            "points": [], "pearson_r": None, "n": 0, "p_value": None,
            "confidence_note": "condition.note.metric_unimplemented",
            "x_key": x_key, "y_key": y_key,
        }
    joined = join_condition_match(conditions, matches, window_days=window_days)
    points: List[Dict[str, Any]] = []
    xs: List[float] = []
    ys: List[float] = []
    for c in joined:
        x = c.get(x_key)
        if x is None:
            continue
        if y_key in MATCH_METRIC_KEYS:
            if y_key == "win_rate":
                if c.get("nearby_match_count", 0) == 0:
                    continue
                y = c.get("nearby_win_rate")
        else:
            y = c.get(y_key)
        if y is None:
            continue
        try:
            xv = float(x)
            yv = float(y)
        except (TypeError, ValueError):
            continue
        xs.append(xv)
        ys.append(yv)
        points.append({
            "measured_at": c.get("measured_at"),
            "x": xv,
            "y": yv,
            "match_count": c.get("nearby_match_count", 0),
        })
    r, p = pearson(xs, ys)
    return {
        "points": points,
        "pearson_r": r,
        "n": len(points),
        "p_value": p,
        "confidence_note": _confidence_note(len(points)),
        "x_key": x_key,
        "y_key": y_key,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ベストパフォーマンスプロファイル
# ─────────────────────────────────────────────────────────────────────────────


PROFILE_KEYS = (
    "ccs_score", "f1_physical", "f2_stress", "f3_mood", "f4_motivation",
    "f5_sleep_life", "hooper_index", "session_load", "sleep_hours",
    "muscle_mass_kg", "ecw_ratio",
)


def _summarize(values: Sequence[float]) -> Dict[str, Optional[float]]:
    if not values:
        return {"mean": None, "std": None, "min": None, "max": None}
    return {
        "mean": mean(values),
        "std": pstdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def best_performance_profile(
    conditions: Sequence[Dict[str, Any]],
    matches: Sequence[Dict[str, Any]],
    window_days: int = 3,
    top_ratio: float = 0.3,
) -> Dict[str, Any]:
    """勝率上位 30% 試合群 vs 残りの condition 分布差から key_factors を抽出。"""
    joined = join_condition_match(conditions, matches, window_days=window_days)
    with_match = [c for c in joined if c.get("nearby_match_count", 0) > 0]
    if not with_match:
        return {
            "key_factors": [],
            "top_profile": {},
            "rest_profile": {},
            "n_top": 0,
            "n_rest": 0,
            "confidence": "none",
            "note": "condition.note.no_matches",
        }
    sorted_rows = sorted(
        with_match, key=lambda c: (c.get("nearby_win_rate") or 0.0), reverse=True
    )
    k = max(1, int(math.ceil(len(sorted_rows) * top_ratio)))
    top = sorted_rows[:k]
    rest = sorted_rows[k:]

    top_profile: Dict[str, Dict[str, Optional[float]]] = {}
    rest_profile: Dict[str, Dict[str, Optional[float]]] = {}
    diffs: List[Tuple[str, float]] = []
    for key in PROFILE_KEYS:
        tv = [float(c[key]) for c in top if c.get(key) is not None]
        rv = [float(c[key]) for c in rest if c.get(key) is not None]
        top_profile[key] = _summarize(tv)
        rest_profile[key] = _summarize(rv)
        if tv and rv:
            pooled = pstdev(tv + rv) or 1.0
            d = (mean(tv) - mean(rv)) / pooled
            diffs.append((key, d))
    diffs.sort(key=lambda kv: abs(kv[1]), reverse=True)
    key_factors = [
        {"key": k, "effect_size": round(v, 3),
         "direction": "higher_when_winning" if v > 0 else "lower_when_winning"}
        for k, v in diffs[:3]
    ]
    n_top = len(top)
    n_rest = len(rest)
    if n_top + n_rest < 5:
        confidence = "low"
    elif n_top + n_rest < 15:
        confidence = "medium"
    else:
        confidence = "high"
    return {
        "key_factors": key_factors,
        "top_profile": top_profile,
        "rest_profile": rest_profile,
        "n_top": n_top,
        "n_rest": n_rest,
        "confidence": confidence,
        "note": _confidence_note(n_top + n_rest),
    }


# ─────────────────────────────────────────────────────────────────────────────
# 乖離検出
# ─────────────────────────────────────────────────────────────────────────────


def detect_discrepancy(
    condition: Dict[str, Any],
    prev_condition: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """1 row に対し InBody × メンタル 乖離フラグを返す。

    返却: list of {type, severity, detail}
    """
    flags: List[Dict[str, Any]] = []
    ecw = condition.get("ecw_ratio")
    f1 = condition.get("f1_physical")
    if ecw is not None and f1 is not None:
        try:
            if float(ecw) > 0.40 and float(f1) < 16:
                severity = "high" if float(ecw) > 0.42 else "medium"
                flags.append({
                    "type": "inbody_mental_mismatch",
                    "severity": severity,
                    "detail": {"ecw_ratio": float(ecw), "f1_physical": float(f1)},
                })
        except (TypeError, ValueError):
            pass

    # 体重急減 × 睡眠自己申告良好
    w = condition.get("weight_kg")
    f5 = condition.get("f5_sleep_life")
    prev_w = prev_condition.get("weight_kg") if prev_condition else None
    if w is not None and prev_w is not None and f5 is not None:
        try:
            ratio = (float(w) - float(prev_w)) / float(prev_w) if float(prev_w) > 0 else 0.0
            if ratio <= -0.03 and float(f5) < 16:
                severity = "high" if ratio <= -0.05 else "medium"
                flags.append({
                    "type": "weight_loss_but_good_sleep_report",
                    "severity": severity,
                    "detail": {
                        "weight_kg": float(w),
                        "prev_weight_kg": float(prev_w),
                        "delta_ratio": round(ratio, 4),
                        "f5_sleep_life": float(f5),
                    },
                })
        except (TypeError, ValueError):
            pass

    # Hooper 高 × CCS 高
    hi = condition.get("hooper_index")
    ccs = condition.get("ccs_score")
    if hi is not None and ccs is not None:
        try:
            if float(hi) > 20 and float(ccs) > 130:
                severity = "high" if float(hi) > 24 else "medium"
                flags.append({
                    "type": "hooper_ccs_mismatch",
                    "severity": severity,
                    "detail": {"hooper_index": float(hi), "ccs_score": float(ccs)},
                })
        except (TypeError, ValueError):
            pass

    # 低 severity 拡張: ギリギリのケース
    for f in flags:
        if "severity" not in f:
            f["severity"] = "low"
    return flags


# ─────────────────────────────────────────────────────────────────────────────
# 選手向け growth-oriented インサイト
# ─────────────────────────────────────────────────────────────────────────────


# 許可された成長フレームキー。ここに無いキーは返却禁止（弱点表記防止）。
_GROWTH_I18N_WHITELIST = {
    "condition.insight.muscle_positive",
    "condition.insight.ccs_positive",
    "condition.insight.sleep_positive",
}


def _zscore_mask(values: Sequence[float], threshold: float = 1.0) -> List[bool]:
    if len(values) < 2:
        return [False] * len(values)
    m = mean(values)
    sd = pstdev(values) or 0.0
    if sd <= 0:
        return [False] * len(values)
    return [(v - m) / sd >= threshold for v in values]


def _effect(win_in: List[bool], win_out: List[bool]) -> Optional[float]:
    if not win_in or not win_out:
        return None
    return sum(win_in) / len(win_in) - sum(win_out) / len(win_out)


def player_growth_insights(
    conditions: Sequence[Dict[str, Any]],
    matches: Sequence[Dict[str, Any]],
    window_days: int = 3,
) -> Dict[str, Any]:
    """選手向け growth-oriented インサイト群。

    各カードは「〜が通常以上のとき伸びる」形のみ。効果量 ≥ 3% & N≥5 を満たす
    カードだけ返却する。文言は i18n キーのみ。
    """
    joined = join_condition_match(conditions, matches, window_days=window_days)
    # 試合紐付きの weekly 条件のみ対象
    rows = [c for c in joined if c.get("nearby_match_count", 0) > 0]

    cards: List[Dict[str, Any]] = []

    def _build_card(key: str, feature_key: str, i18n_key: str) -> None:
        if i18n_key not in _GROWTH_I18N_WHITELIST:
            return
        vals = [float(c[feature_key]) for c in rows if c.get(feature_key) is not None]
        if len(vals) < 5:
            return
        # 対応する勝率（nearby_win_rate）を True/False ラリー不要、row 単位で
        wins_by_row = [bool((c.get("nearby_win_rate") or 0.0) >= 0.5)
                       for c in rows if c.get(feature_key) is not None]
        mask = _zscore_mask(vals, threshold=1.0)
        win_in = [w for w, m in zip(wins_by_row, mask) if m]
        win_out = [w for w, m in zip(wins_by_row, mask) if not m]
        if len(win_in) < 2 or len(win_out) < 2:
            return
        eff = _effect(win_in, win_out)
        if eff is None or eff < 0.03:
            # growth-oriented ルール: 正方向効果のみ表示
            return
        cards.append({
            "key": key,
            "i18n_key": i18n_key,
            "feature": feature_key,
            "n_high": len(win_in),
            "n_other": len(win_out),
            "win_rate_high": round(sum(win_in) / len(win_in), 3),
            "win_rate_other": round(sum(win_out) / len(win_out), 3),
            "lift": round(eff, 3),
            "frame": "growth_positive",
        })

    _build_card("muscle", "muscle_mass_kg", "condition.insight.muscle_positive")
    _build_card("ccs", "ccs_score", "condition.insight.ccs_positive")
    _build_card("sleep", "f5_sleep_life", "condition.insight.sleep_positive")

    return {
        "growth_cards": cards,
        "n_sampled_weeks": len(rows),
        "confidence_note": _confidence_note(len(rows)),
    }
