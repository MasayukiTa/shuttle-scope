"""試合の状態機械: 決着した試合に追加のセットを作らせない / 30 点を超えるスコアは存在しない。

モバイルのアノテーションは PUT /sets/{id}/end を呼ばずに次のセットへ進むため、
2-0 で試合が決着していても POST /sets が第 3 セットを作ってしまっていた。
空の第 3 セットは再開位置・セット数・解析母集団を汚す。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, Rally
from backend.main import app
from backend.routers.sets import _winner_from_scores


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, headers={"X-Role": "admin"})
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def match_id(db_session):
    a = Player(name="状態機械A", dominant_hand="R")
    b = Player(name="状態機械B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="状態機械テスト",
        tournament_level="practice",
        round="R1",
        date=date(2026, 10, 22),
        format="singles",
        player_a_id=a.id,
        player_b_id=b.id,
        result="unknown",
    )
    db_session.add(m)
    db_session.commit()
    return m.id


def _finished_set_by_rally(db_session, match_id: int, set_num: int, score_a: int, score_b: int):
    """GameSet.winner を埋めず、最終ラリーのスコアだけで決着しているセット (モバイル相当)。"""
    gs = GameSet(match_id=match_id, set_num=set_num)
    db_session.add(gs)
    db_session.flush()
    db_session.add(Rally(
        set_id=gs.id, rally_num=1, server="player_a", winner="player_a",
        end_type="unknown", rally_length=0,
        score_a_after=score_a, score_b_after=score_b,
    ))
    db_session.commit()
    return gs


class TestNoSetAfterTheMatchIsDecided:
    def test_third_set_is_refused_after_two_straight_wins(self, client, db_session, match_id):
        _finished_set_by_rally(db_session, match_id, 1, 21, 15)
        _finished_set_by_rally(db_session, match_id, 2, 21, 10)
        res = client.post("/api/sets", json={"match_id": match_id, "set_num": 3})
        assert res.status_code == 409, res.text
        assert db_session.query(GameSet).filter(GameSet.match_id == match_id).count() == 2

    def test_third_set_is_allowed_at_one_all(self, client, db_session, match_id):
        _finished_set_by_rally(db_session, match_id, 1, 21, 15)
        _finished_set_by_rally(db_session, match_id, 2, 12, 21)
        res = client.post("/api/sets", json={"match_id": match_id, "set_num": 3})
        assert res.status_code == 201, res.text

    def test_second_set_is_allowed_after_one_win(self, client, db_session, match_id):
        _finished_set_by_rally(db_session, match_id, 1, 21, 15)
        res = client.post("/api/sets", json={"match_id": match_id, "set_num": 2})
        assert res.status_code == 201, res.text

    def test_confirmed_winner_column_counts_too(self, client, db_session, match_id):
        for n in (1, 2):
            db_session.add(GameSet(match_id=match_id, set_num=n, winner="player_b",
                                   score_a=10, score_b=21))
        db_session.commit()
        res = client.post("/api/sets", json={"match_id": match_id, "set_num": 3})
        assert res.status_code == 409, res.text

    @pytest.mark.parametrize("set_num", [4, 5])
    def test_best_of_three_has_no_fourth_or_fifth_set(self, client, match_id, set_num):
        res = client.post("/api/sets", json={"match_id": match_id, "set_num": set_num})
        assert res.status_code == 422, res.text


class TestScoreCap:
    @pytest.mark.parametrize("a,b", [(31, 30), (30, 31), (40, 39), (30, 30)])
    def test_scores_beyond_thirty_are_not_a_finished_set(self, a, b):
        assert _winner_from_scores(a, b) is None

    @pytest.mark.parametrize("a,b,expected", [
        (30, 29, "player_a"),
        (29, 30, "player_b"),
        (21, 19, "player_a"),
        (22, 24, "player_b"),
    ])
    def test_valid_endings_keep_their_winner(self, a, b, expected):
        assert _winner_from_scores(a, b) == expected

    def test_set_end_refuses_31_30(self, client, db_session, match_id):
        gs = GameSet(match_id=match_id, set_num=1)
        db_session.add(gs)
        db_session.commit()
        res = client.put(f"/api/sets/{gs.id}/end",
                         json={"winner": "player_a", "score_a": 31, "score_b": 30})
        assert res.status_code == 422, res.text
