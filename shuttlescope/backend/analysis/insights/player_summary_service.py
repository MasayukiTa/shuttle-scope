"""コンパクトな選手サマリ生成サービス (Slice Y).

LLM プロンプトに直接埋め込める ≤5KB の JSON 構造を返す。
SQLAlchemy 集約クエリで N+1 を避ける。
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from typing import Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from backend.db.models import (
    Condition,
    GameSet,
    Match,
    Player,
    Rally,
    Stroke,
)


_ALLOWED_SECTIONS = (
    "identity",
    "sample",
    "outcomes",
    "shot_mix",
    "zones",
    "conditions",
    "recent_trend",
)


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except Exception:
        try:
            return datetime.fromisoformat(s).date()
        except Exception:
            return None


def _match_player_side(m: Match, player_id: int) -> Optional[str]:
    if m.player_a_id == player_id:
        return "player_a"
    if m.player_b_id == player_id:
        return "player_b"
    return None


def build_player_summary(
    db: Session,
    player_id: int,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    sections: Optional[list[str]] = None,
) -> dict:
    """選手の集約サマリを返す.

    sections=None なら全セクション。
    """
    df = _parse_date(date_from)
    dt = _parse_date(date_to)

    selected = set(sections) if sections else set(_ALLOWED_SECTIONS)
    selected &= set(_ALLOWED_SECTIONS)

    player = db.get(Player, player_id)
    player_name = player.name if player is not None else ""

    # 対象選手の試合を一括取得（期間フィルタ込み）
    match_q = db.query(Match).filter(
        Match.deleted_at.is_(None),
        (Match.player_a_id == player_id) | (Match.player_b_id == player_id),
    )
    if df:
        match_q = match_q.filter(Match.date >= df)
    if dt:
        match_q = match_q.filter(Match.date <= dt)
    matches = match_q.all()
    match_ids = [m.id for m in matches]

    # ── outcomes: match-level win-rate と set-level win-rate ──
    n_matches = len(matches)
    match_wins = 0
    for m in matches:
        side = _match_player_side(m, player_id)
        if side == "player_a" and m.result == "win":
            match_wins += 1
        elif side == "player_b" and m.result == "loss":
            # result は player_a 視点
            match_wins += 1
    match_win_rate = (match_wins / n_matches) if n_matches > 0 else 0.0

    set_rows: list[tuple[int, Optional[str]]] = []
    if match_ids:
        set_rows = (
            db.query(GameSet.match_id, GameSet.winner)
            .filter(
                GameSet.match_id.in_(match_ids),
                GameSet.deleted_at.is_(None),
            )
            .all()
        )
    side_by_match = {m.id: _match_player_side(m, player_id) for m in matches}
    n_sets = len(set_rows)
    set_wins = sum(
        1
        for mid, w in set_rows
        if w is not None and side_by_match.get(mid) == w
    )
    set_win_rate = (set_wins / n_sets) if n_sets > 0 else 0.0

    # ── strokes 集約: shot_mix / zones / rally count ──
    set_ids: list[int] = []
    if match_ids:
        set_ids = [
            sid
            for (sid,) in db.query(GameSet.id)
            .filter(
                GameSet.match_id.in_(match_ids),
                GameSet.deleted_at.is_(None),
            )
            .all()
        ]

    n_rallies = 0
    n_strokes = 0
    shot_mix_rows: list[tuple[str, int]] = []
    hit_zone_rows: list[tuple[str, int]] = []
    land_zone_rows: list[tuple[str, int]] = []

    if set_ids:
        n_rallies = (
            db.query(func.count(Rally.id))
            .filter(Rally.set_id.in_(set_ids), Rally.deleted_at.is_(None))
            .scalar()
            or 0
        )
        rally_ids = [
            rid
            for (rid,) in db.query(Rally.id)
            .filter(Rally.set_id.in_(set_ids), Rally.deleted_at.is_(None))
            .all()
        ]
        if rally_ids:
            # Stroke.player は "player_a" / "player_b" のリテラル。
            # rally → set → match 経由で side を絞る必要があるので、
            # 1 クエリで rally_id, stroke fields を取って Python 側で集約。
            # ただし shot_mix/zone のみ「対象選手の打点」に限定したいので
            # match→side マップを使う。
            rally_to_match: dict[int, int] = dict(
                db.query(Rally.id, GameSet.match_id)
                .join(GameSet, Rally.set_id == GameSet.id)
                .filter(Rally.id.in_(rally_ids))
                .all()
            )

            # 集約: shot_type / hit_zone / land_zone (対象選手 stroke のみ)
            # まず全 stroke を 1 回読み、Python 側で側分岐 (rally→match→side)
            stroke_rows = (
                db.query(
                    Stroke.rally_id,
                    Stroke.player,
                    Stroke.shot_type,
                    Stroke.hit_zone,
                    Stroke.land_zone,
                )
                .filter(
                    Stroke.rally_id.in_(rally_ids),
                    Stroke.deleted_at.is_(None),
                )
                .all()
            )
            n_strokes = len(stroke_rows)

            shot_counter: Counter[str] = Counter()
            hit_counter: Counter[str] = Counter()
            land_counter: Counter[str] = Counter()
            for rid, sp, stype, hz, lz in stroke_rows:
                mid = rally_to_match.get(rid)
                if mid is None:
                    continue
                side = side_by_match.get(mid)
                if side != sp:
                    continue
                if stype:
                    shot_counter[stype] += 1
                if hz:
                    hit_counter[hz] += 1
                if lz:
                    land_counter[lz] += 1

            total_shot = sum(shot_counter.values())
            shot_mix_rows = shot_counter.most_common(5)
            total_hit = sum(hit_counter.values())
            total_land = sum(land_counter.values())
            hit_zone_rows = hit_counter.most_common(3)
            land_zone_rows = land_counter.most_common(3)
        else:
            total_shot = total_hit = total_land = 0
    else:
        total_shot = total_hit = total_land = 0

    # ── conditions: 期間内 RPE / Hooper 平均 ──
    cond_q = db.query(
        func.avg(Condition.session_rpe),
        func.avg(Condition.hooper_index),
        func.count(Condition.id),
    ).filter(Condition.player_id == player_id)
    if df:
        cond_q = cond_q.filter(Condition.measured_at >= df)
    if dt:
        cond_q = cond_q.filter(Condition.measured_at <= dt)
    avg_rpe, avg_hooper, cond_n = cond_q.first() or (None, None, 0)

    # ── recent_trend: 最新 5 試合 vs その前 5 試合 ──
    matches_sorted = sorted(
        matches, key=lambda m: (m.date or date.min, m.id), reverse=True
    )

    def _win_rate(ms: list[Match]) -> Optional[float]:
        if not ms:
            return None
        wins = 0
        for m in ms:
            side = _match_player_side(m, player_id)
            if side == "player_a" and m.result == "win":
                wins += 1
            elif side == "player_b" and m.result == "loss":
                wins += 1
        return wins / len(ms)

    last5 = matches_sorted[:5]
    prior5 = matches_sorted[5:10]
    last5_wr = _win_rate(last5)
    prior5_wr = _win_rate(prior5)
    delta = None
    if last5_wr is not None and prior5_wr is not None:
        delta = round(last5_wr - prior5_wr, 4)

    # ── 組み立て ──
    full: dict = {
        "player_id": player_id,
        "player_name": player_name,
        "date_from": date_from,
        "date_to": date_to,
        "sample": {
            "matches": int(n_matches),
            "rallies": int(n_rallies),
            "strokes": int(n_strokes),
        },
        "outcomes": {
            "win_rate": round(match_win_rate, 4),
            "set_win_rate": round(set_win_rate, 4),
            "n": int(n_matches),
        },
        "shot_mix": [
            {
                "shot_type": st,
                "count": int(c),
                "share": round((c / total_shot) if total_shot else 0.0, 4),
            }
            for st, c in shot_mix_rows
        ],
        "zones": {
            "hit_top": [
                {
                    "zone": z,
                    "share": round((c / total_hit) if total_hit else 0.0, 4),
                }
                for z, c in hit_zone_rows
            ],
            "land_top": [
                {
                    "zone": z,
                    "share": round((c / total_land) if total_land else 0.0, 4),
                }
                for z, c in land_zone_rows
            ],
        },
        "conditions": {
            "avg_rpe": (round(float(avg_rpe), 2) if avg_rpe is not None else None),
            "avg_hooper": (
                round(float(avg_hooper), 2) if avg_hooper is not None else None
            ),
            "n": int(cond_n or 0),
        },
        "recent_trend": {
            "last_5_match_win_rate": (
                round(last5_wr, 4) if last5_wr is not None else None
            ),
            "delta_vs_prior_5": delta,
        },
    }

    # identity は player_id / player_name / date_from / date_to を含むトップキー扱い
    identity_keys = {"player_id", "player_name", "date_from", "date_to"}
    section_keys: dict[str, set[str]] = {
        "identity": identity_keys,
        "sample": {"sample"},
        "outcomes": {"outcomes"},
        "shot_mix": {"shot_mix"},
        "zones": {"zones"},
        "conditions": {"conditions"},
        "recent_trend": {"recent_trend"},
    }
    if sections is not None:
        keep: set[str] = set()
        for s in selected:
            keep |= section_keys.get(s, set())
        return {k: v for k, v in full.items() if k in keep}
    return full
