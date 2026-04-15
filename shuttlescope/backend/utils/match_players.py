"""試合に関与する選手ID を集める小さなヘルパ。

mutation 時のキャッシュ無効化スコープを決めるために利用する。
response_cache.bump_players() へ渡す player_id のリストを作る。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import Match, GameSet, Rally


def players_for_match(db: Session, match_id: Optional[int]) -> list[int]:
    """match_id から player_a/b/partner_a/b の選手ID一覧を返す。

    見つからない / match_id=None の場合は空リスト。
    None の選手枠はスキップ。
    """
    if match_id is None:
        return []
    m = db.get(Match, match_id)
    if not m:
        return []
    return [
        p for p in (m.player_a_id, m.player_b_id, m.partner_a_id, m.partner_b_id)
        if p is not None
    ]


def players_for_set(db: Session, set_id: Optional[int]) -> list[int]:
    """set_id から、その set が所属する match の選手ID一覧を返す。"""
    if set_id is None:
        return []
    s = db.get(GameSet, set_id)
    if not s:
        return []
    return players_for_match(db, s.match_id)


def players_for_rally(db: Session, rally_id: Optional[int]) -> list[int]:
    """rally_id から、関与する match の選手ID一覧を返す。"""
    if rally_id is None:
        return []
    r = db.get(Rally, rally_id)
    if not r:
        return []
    return players_for_set(db, r.set_id)
