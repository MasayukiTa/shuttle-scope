"""peer_comparison.py — admin 専用 community peer cohort 集計 (research tier)

privacy 設計:
  - k-anonymity: cohort N < MIN_COHORT_N の場合は metrics を一切返さず
    {'available': False, 'reason': 'insufficient_cohort'} を返す。
  - aggregate-only: 個別選手の値は返さない。p25/p50/p75/mean/sd のみ。
  - demo team は team.display_id == '__demo__' で識別して必ず除外する。
  - 識別側チャネル防止: min/max は返さない（個人特定の足掛かりを残さない）。

将来: opt-in/opt-out consent flag を Player に追加し、player レベルで
participation を切り替えられるようにする。Phase 1 では admin oversight 下で
全 non-demo player を対象とする。
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Optional, TypedDict

from sqlalchemy.orm import Session

from backend.db.models import (
    Match, GameSet, Rally, Stroke, Player, Team,
)


MIN_COHORT_N: int = 5
DEMO_DISPLAY_ID: str = "__demo__"

SUPPORTED_METRICS: tuple[str, ...] = (
    "smash_win_rate",
    "net_front_win_rate",
    "avg_rally_length",
    "serve_win_rate",
    "around_head_freq",
)

METRIC_UNITS: dict[str, str] = {
    "smash_win_rate":      "ratio",
    "net_front_win_rate":  "ratio",
    "avg_rally_length":    "strokes",
    "serve_win_rate":      "ratio",
    "around_head_freq":    "ratio",
}


class CohortSpec(TypedDict, total=False):
    age_bucket: str   # '18-21' | '22-25' | '26-29' | '30+'
    level: str        # 'local' | 'regional' | 'national' | 'international'
    handedness: str   # 'right' | 'left'
    gender: str       # 'm' | 'f' | 'other'
    singles_doubles: str  # 'singles' | 'doubles'


# ── cohort matching ─────────────────────────────────────────────────────────

def _age_bucket(birth_year: Optional[int], today_year: int = 2026) -> Optional[str]:
    if not birth_year:
        return None
    age = today_year - birth_year
    if age < 18:
        return None
    if age <= 21:
        return "18-21"
    if age <= 25:
        return "22-25"
    if age <= 29:
        return "26-29"
    return "30+"


def _hand_norm(d: Optional[str]) -> Optional[str]:
    if not d:
        return None
    s = d.strip().lower()
    if s.startswith("r"):
        return "right"
    if s.startswith("l"):
        return "left"
    return None


def _player_matches_cohort(p: Player, spec: CohortSpec) -> bool:
    """player に対する非試合系フィルタの当てはめ。"""
    if "age_bucket" in spec and spec["age_bucket"]:
        if _age_bucket(p.birth_year) != spec["age_bucket"]:
            return False
    if "handedness" in spec and spec["handedness"]:
        if _hand_norm(p.dominant_hand) != spec["handedness"]:
            return False
    # gender / level / singles_doubles は Player カラムが存在しないため、
    # gender / level はスキーマ未対応として silent ignore する
    # (フィルタ条件として除外されない = 全員 match 扱い)。
    # singles_doubles は試合 format で判定するため _filter_matches_for_format で扱う。
    return True


def _player_level(db: Session, player_id: int) -> Optional[str]:
    """最頻出 tournament_level から player level を推定 (heuristic)。
    国際/全日本 → international, IS/IC → national, SJL/国内 → regional, その他 → local。
    """
    rows = (
        db.query(Match.tournament_level)
        .filter((Match.player_a_id == player_id) | (Match.player_b_id == player_id))
        .all()
    )
    if not rows:
        return None
    levels: dict[str, int] = defaultdict(int)
    for (lv,) in rows:
        if lv in ("国際", "全日本"):
            levels["international"] += 1
        elif lv in ("IS", "IC"):
            levels["national"] += 1
        elif lv in ("SJL", "国内"):
            levels["regional"] += 1
        else:
            levels["local"] += 1
    return max(levels.items(), key=lambda kv: kv[1])[0]


# ── per-player metric computation ───────────────────────────────────────────

def _compute_per_player_metrics(
    db: Session,
    player_id: int,
    metrics: list[str],
    singles_doubles: Optional[str] = None,
) -> Optional[dict[str, float]]:
    """player について各 metric を計算する。
    metric ごとに分母が 0 になる場合は dict から omit する。
    matches が 0 の場合は None を返す。
    """
    q = db.query(Match).filter(
        (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
    )
    if singles_doubles == "singles":
        q = q.filter(Match.format == "singles")
    elif singles_doubles == "doubles":
        q = q.filter(Match.format != "singles")
    matches = q.all()
    if not matches:
        return None

    match_ids = [m.id for m in matches]
    role_by_match = {
        m.id: ("player_a" if m.player_a_id == player_id else "player_b") for m in matches
    }
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]
    rallies = (
        db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    )
    if not rallies:
        return None
    rally_ids = [r.id for r in rallies]
    strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(rally_ids))
        .all()
    )

    rally_to_role: dict[int, str] = {}
    rally_won: dict[int, bool] = {}
    for r in rallies:
        mid = set_to_match.get(r.set_id)
        role = role_by_match.get(mid) if mid else None
        if role is None:
            continue
        rally_to_role[r.id] = role
        rally_won[r.id] = (r.winner == role)

    rally_length_total = 0
    rally_length_count = 0
    for r in rallies:
        if r.id in rally_to_role and r.rally_length is not None:
            rally_length_total += r.rally_length
            rally_length_count += 1

    # ショット種別ごとの player ストローク勝率
    shot_count: dict[str, int] = defaultdict(int)
    shot_wins: dict[str, int] = defaultdict(int)
    serve_count = 0
    serve_wins = 0
    total_player_strokes = 0
    around_head_count = 0

    for s in strokes:
        role = rally_to_role.get(s.rally_id)
        if role is None or s.player != role:
            continue
        total_player_strokes += 1
        if not s.shot_type:
            continue
        won = 1 if rally_won.get(s.rally_id, False) else 0
        shot_count[s.shot_type] += 1
        shot_wins[s.shot_type] += won
        if s.shot_type == "serve" or (s.stroke_num == 1):
            # stroke_num==1 をサーブ近似（shot_type が serve として記録されない
            # ケースが多いため heuristic を併用）
            if s.shot_type == "serve" or s.stroke_num == 1:
                serve_count += 1
                serve_wins += won
        if s.shot_type in ("around_head", "around_the_head"):
            around_head_count += 1

    result: dict[str, float] = {}

    if "smash_win_rate" in metrics:
        c = shot_count.get("smash", 0)
        if c > 0:
            result["smash_win_rate"] = shot_wins["smash"] / c

    if "net_front_win_rate" in metrics:
        # net_shot + hair_pin を「ネット前」とみなす
        c = shot_count.get("net_shot", 0) + shot_count.get("hair_pin", 0)
        w = shot_wins.get("net_shot", 0) + shot_wins.get("hair_pin", 0)
        if c > 0:
            result["net_front_win_rate"] = w / c

    if "avg_rally_length" in metrics:
        if rally_length_count > 0:
            result["avg_rally_length"] = rally_length_total / rally_length_count

    if "serve_win_rate" in metrics:
        if serve_count > 0:
            result["serve_win_rate"] = serve_wins / serve_count

    if "around_head_freq" in metrics:
        if total_player_strokes > 0:
            result["around_head_freq"] = around_head_count / total_player_strokes

    return result if result else None


# ── aggregation ─────────────────────────────────────────────────────────────

def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    # linear interpolation
    pos = (len(sorted_vals) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = pos - lo
    return float(sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac)


def _aggregate(values: list[float]) -> dict[str, float]:
    sv = sorted(values)
    mean = statistics.fmean(sv)
    sd = statistics.pstdev(sv) if len(sv) >= 2 else 0.0
    return {
        "p25":  round(_percentile(sv, 0.25), 4),
        "p50":  round(_percentile(sv, 0.50), 4),
        "p75":  round(_percentile(sv, 0.75), 4),
        "mean": round(mean, 4),
        "sd":   round(sd, 4),
    }


def _demo_team_ids(db: Session) -> set[int]:
    rows = (
        db.query(Team.id)
        .filter(Team.display_id == DEMO_DISPLAY_ID)
        .all()
    )
    return {r[0] for r in rows}


def compute_peer_cohort_stats(
    db: Session,
    cohort: CohortSpec,
    metrics: Optional[list[str]] = None,
) -> dict:
    """指定 cohort に該当する non-demo player について集計値を返す。

    Returns:
        {'available': True, 'n': N, 'metrics': {metric_name: {p25, p50, p75, mean, sd, unit}}}
        または {'available': False, 'n': N, 'reason': 'insufficient_cohort'}.
    """
    metrics = list(metrics) if metrics else list(SUPPORTED_METRICS)
    # サポート外 metric は silent drop
    metrics = [m for m in metrics if m in SUPPORTED_METRICS]
    if not metrics:
        return {"available": False, "n": 0, "reason": "no_supported_metrics"}

    demo_team_ids = _demo_team_ids(db)

    # 候補 player 抽出
    q = db.query(Player).filter(Player.deleted_at.is_(None))
    if demo_team_ids:
        q = q.filter(~Player.team_id.in_(demo_team_ids))
    players = q.all()

    # non-match cohort フィルタ
    players = [p for p in players if _player_matches_cohort(p, cohort)]

    # level フィルタ (試合ベース heuristic、player ごとに 1 回計算)
    level_filter = cohort.get("level")
    if level_filter:
        players = [p for p in players if _player_level(db, p.id) == level_filter]

    singles_doubles = cohort.get("singles_doubles")

    # 各 player の metric 値
    metric_values: dict[str, list[float]] = {m: [] for m in metrics}
    cohort_n = 0
    for p in players:
        per = _compute_per_player_metrics(db, p.id, metrics, singles_doubles)
        if not per:
            continue
        cohort_n += 1
        for m, v in per.items():
            metric_values[m].append(v)

    if cohort_n < MIN_COHORT_N:
        return {
            "available": False,
            "n": cohort_n,
            "reason": "insufficient_cohort",
        }

    out_metrics: dict[str, dict] = {}
    for m in metrics:
        vals = metric_values.get(m, [])
        if len(vals) < MIN_COHORT_N:
            # 個別 metric も k-anon を満たさない場合は省く（identifying side-channel 防止）
            continue
        agg = _aggregate(vals)
        agg["unit"] = METRIC_UNITS.get(m, "")
        out_metrics[m] = agg

    return {
        "available": True,
        "n": cohort_n,
        "metrics": out_metrics,
    }
