"""ダブルスのパートナーが選手一覧から消えていた。

`match_count` を `player_a_id | player_b_id` だけで数えていたので、
パートナー枠 (`partner_a_id` / `partner_b_id`) でしか出ていない選手は 0 になる。
ダッシュボードの選手セレクタは `match_count > 0` で絞る
(`src/pages/dashboard/DashboardShell.tsx`) ので、**その選手はダブルスの
解析データを持っているのに一覧に出てこない**。

`backend.main` を import しない。
"""
from __future__ import annotations

from datetime import date

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from backend.db.models import Base, Match, Player
from backend.routers.players import _match_counts


@pytest.fixture()
def db():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _player(db, name: str) -> Player:
    p = Player(name=name, dominant_hand="R")
    db.add(p)
    db.flush()
    return p


def _match(db, **slots) -> Match:
    m = Match(
        tournament="パートナー集計テスト",
        tournament_level="practice",
        round="R1",
        date=date(2026, 9, 19),
        format="womens_doubles",
        result="unknown",
        **slots,
    )
    db.add(m)
    db.flush()
    return m


def test_a_partner_is_counted(db):
    a, pa, b, pb = (_player(db, n) for n in ("A", "Aの相方", "B", "Bの相方"))
    _match(db, player_a_id=a.id, partner_a_id=pa.id,
           player_b_id=b.id, partner_b_id=pb.id)
    counts = _match_counts(db, [a, pa, b, pb])
    assert counts[pa.id] == 1, "パートナー枠が数えられていない"
    assert counts[pb.id] == 1
    assert counts[a.id] == 1
    assert counts[b.id] == 1


def test_singles_is_unchanged(db):
    a, b = _player(db, "単A"), _player(db, "単B")
    _match(db, player_a_id=a.id, player_b_id=b.id)
    counts = _match_counts(db, [a, b])
    assert counts == {a.id: 1, b.id: 1}


def test_a_player_with_no_matches_is_zero_not_missing(db):
    """欠落と 0 を区別する。呼び出し側は `.get(id, 0)` で埋めている。"""
    ghost = _player(db, "未出場")
    counts = _match_counts(db, [ghost])
    assert counts == {ghost.id: 0}


def test_counts_accumulate_across_matches(db):
    a, pa, b = _player(db, "A2"), _player(db, "相方2"), _player(db, "B2")
    _match(db, player_a_id=a.id, partner_a_id=pa.id, player_b_id=b.id)
    _match(db, player_a_id=b.id, partner_a_id=pa.id, player_b_id=a.id)
    counts = _match_counts(db, [a, pa, b])
    assert counts[pa.id] == 2
    assert counts[a.id] == 2


def test_an_empty_list_does_not_query(db):
    assert _match_counts(db, []) == {}


def test_only_the_requested_players_are_returned(db):
    a, b, other = _player(db, "対象A"), _player(db, "対象B"), _player(db, "範囲外")
    _match(db, player_a_id=a.id, player_b_id=other.id)
    counts = _match_counts(db, [a, b])
    assert set(counts) == {a.id, b.id}
    assert counts[b.id] == 0
