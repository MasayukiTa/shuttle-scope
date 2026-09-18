"""A-5: (set_id, rally_num) の一意性のテスト。

一意性が無かったため、再開・再送・複数端末で同じラリー番号が二重に入り、
スコア推移も集計も静かに壊れていた。migration 0053 の部分一意インデックスと、
POST /rallies 側の「既にあればそれを返す」挙動を固定する。

部分インデックスにしているのは、論理削除 (deleted_at) 済みの行と
衝突させないため。
"""
from __future__ import annotations

from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from backend.main import app
from backend.db.database import get_db
from backend.db.models import Player, Match, GameSet, Rally


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, headers={"X-Role": "admin"})
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def game_set(db_session):
    a = Player(name="一意A", dominant_hand="R")
    b = Player(name="一意B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="一意テスト",
        tournament_level="practice",
        round="R1",
        date=date(2026, 9, 18),
        format="singles",
        player_a_id=a.id,
        player_b_id=b.id,
        result="unknown",
    )
    db_session.add(m)
    db_session.flush()
    gs = GameSet(match_id=m.id, set_num=1)
    db_session.add(gs)
    db_session.flush()
    db_session.commit()
    return gs


def _rally(set_id: int, rally_num: int) -> Rally:
    return Rally(
        set_id=set_id,
        rally_num=rally_num,
        server="player_a",
        winner="player_a",
        end_type="ace",
        rally_length=3,
        score_a_after=rally_num,
        score_b_after=0,
    )


def _payload(set_id: int, rally_num: int) -> dict:
    return {
        "set_id": set_id,
        "rally_num": rally_num,
        "server": "player_a",
        "winner": "player_a",
        "end_type": "ace",
        "rally_length": 3,
        "score_a_after": rally_num,
        "score_b_after": 0,
    }


class TestRallyUniqueIndex:
    def test_index_exists(self, db_session):
        names = {ix["name"] for ix in inspect(db_session.get_bind()).get_indexes("rallies")}
        assert "uq_rallies_set_id_rally_num_active" in names

    def test_duplicate_rally_num_is_rejected(self, db_session, game_set):
        db_session.add(_rally(game_set.id, 1))
        db_session.commit()
        db_session.add(_rally(game_set.id, 1))
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

    def test_soft_deleted_row_does_not_block_reuse(self, db_session, game_set):
        first = _rally(game_set.id, 1)
        db_session.add(first)
        db_session.commit()
        first.deleted_at = datetime.utcnow()
        db_session.commit()
        db_session.add(_rally(game_set.id, 1))
        db_session.commit()  # 部分インデックスなので通るのが正しい

    def test_same_number_in_another_set_is_fine(self, db_session, game_set):
        other = GameSet(match_id=game_set.match_id, set_num=2)
        db_session.add(other)
        db_session.flush()
        db_session.add(_rally(game_set.id, 1))
        db_session.add(_rally(other.id, 1))
        db_session.commit()


class TestCreateRallyIsIdempotentOnNumber:
    def test_second_post_returns_the_existing_rally(self, client, game_set):
        first = client.post("/api/rallies", json=_payload(game_set.id, 1))
        assert first.status_code == 201
        first_id = first.json()["data"]["id"]

        second = client.post("/api/rallies", json=_payload(game_set.id, 1))
        assert second.status_code in (200, 201)
        # 新しい行を作らず、既にある行を返すこと
        assert second.json()["data"]["id"] == first_id

    def test_distinct_numbers_still_create_rows(self, client, game_set):
        a = client.post("/api/rallies", json=_payload(game_set.id, 1))
        b = client.post("/api/rallies", json=_payload(game_set.id, 2))
        assert a.json()["data"]["id"] != b.json()["data"]["id"]
