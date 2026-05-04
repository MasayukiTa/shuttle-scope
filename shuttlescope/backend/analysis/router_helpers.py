"""router_helpers.py — analysis router 共通ヘルパー・定数"""
from collections import defaultdict
from datetime import date as DateType
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.db.models import Match, GameSet, Rally
from backend.analysis.player_context import target_role as _target_role_ctx
from backend.analysis.shot_taxonomy import SHOT_TYPE_JA as _SHOT_TYPE_JA_TAXONOMY, CANONICAL_SHOTS

SHOT_TYPE_JA = _SHOT_TYPE_JA_TAXONOMY
SHOT_KEYS = CANONICAL_SHOTS
SHOT_LABELS_JA = [SHOT_TYPE_JA[k] for k in SHOT_KEYS]

END_TYPE_JA = {
    "ace": "エース",
    "forced_error": "強制エラー",
    "unforced_error": "自滅",
    "net": "ネット",
    "out": "アウト",
    "cant_reach": "届かず",
}


def _shot_ja(shot_type: str | None) -> str:
    _MAP = {
        "smash": "スマッシュ", "clear": "クリア", "drop": "ドロップ",
        "net": "ネット", "drive": "ドライブ", "lob": "ロブ",
        "serve": "サーブ", "push": "プッシュ", "lift": "リフト",
        "hair_pin": "ヘアピン", "hairpin": "ヘアピン", "flick": "フリック",
    }
    if not shot_type:
        return "不明"
    return _MAP.get(shot_type.lower(), shot_type)


def _player_role_in_match(match: Match, player_id: int) -> str | None:
    return _target_role_ctx(match, player_id)


def _get_player_matches(
    db: Session, player_id: int, result=None, tournament_level=None,
    date_from=None, date_to=None,
) -> list[Match]:
    q = db.query(Match).filter(
        (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
    )
    if tournament_level:
        q = q.filter(Match.tournament_level == tournament_level)
    if date_from:
        q = q.filter(Match.date >= date_from)
    if date_to:
        q = q.filter(Match.date <= date_to)
    if result in ("win", "loss"):
        opposite = "loss" if result == "win" else "win"
        q = q.filter(
            or_(
                and_(Match.player_a_id == player_id, Match.result == result),
                and_(Match.player_b_id == player_id, Match.result == opposite),
            )
        )
    return q.all()


def _fetch_matches_sets_rallies(player_id: int, db: Session, include_skipped: bool = False):
    matches = (
        db.query(Match)
        .filter((Match.player_a_id == player_id) | (Match.player_b_id == player_id))
        .all()
    )
    if not matches:
        return [], {}, [], {}, [], {}
    match_ids = [m.id for m in matches]
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in matches}
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_ids = [s.id for s in sets]
    set_to_match = {s.id: s.match_id for s in sets}
    if set_ids:
        q = db.query(Rally).filter(Rally.set_id.in_(set_ids))
        if not include_skipped:
            q = q.filter(Rally.is_skipped == False)  # noqa: E712
        rallies = q.all()
    else:
        rallies = []
    return matches, role_by_match, sets, set_to_match, rallies, {}
