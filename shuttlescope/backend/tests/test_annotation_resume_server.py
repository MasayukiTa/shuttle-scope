"""A-2: 再開時のサーブ権のテスト。

`/annotation/{match_id}/state` はサーブ権を返しておらず、途中まで入力した
試合を開き直すと次のラリーが必ず player_a のサーブで始まっていた。
以降の打者が全部ずれるが、画面には何も出ない。

バドミントンでは前ラリーの勝者が次のサーバ。セット頭なら前セットの勝者、
それも無ければ試合の初期サーバ。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

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
def match(db_session):
    a = Player(name="サーブ権A", dominant_hand="R")
    b = Player(name="サーブ権B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="サーブ権テスト",
        date="2026-09-18",
        format="singles",
        player_a_id=a.id,
        player_b_id=b.id,
        result="unknown",
        initial_server="player_b",
    )
    db_session.add(m)
    db_session.flush()
    db_session.commit()
    return m


def _rally(db_session, gs: GameSet, rally_num: int, winner: str) -> Rally:
    r = Rally(
        set_id=gs.id,
        rally_num=rally_num,
        server="player_a",
        winner=winner,
        end_type="ace",
        rally_length=4,
        score_a_after=rally_num if winner == "player_a" else 0,
        score_b_after=rally_num if winner == "player_b" else 0,
    )
    db_session.add(r)
    db_session.flush()
    return r


class TestAnnotationResumeServer:
    def test_no_sets_falls_back_to_match_initial_server(self, client, match):
        res = client.get(f"/api/annotation/{match.id}/state")
        assert res.status_code == 200
        assert res.json()["data"]["next_server"] == "player_b"

    def test_next_server_is_last_rally_winner(self, client, match, db_session):
        gs = GameSet(match_id=match.id, set_num=1)
        db_session.add(gs)
        db_session.flush()
        _rally(db_session, gs, 1, "player_a")
        _rally(db_session, gs, 2, "player_b")
        db_session.commit()

        data = client.get(f"/api/annotation/{match.id}/state").json()["data"]
        assert data["current_rally_num"] == 3
        assert data["next_server"] == "player_b"

    def test_empty_new_set_uses_previous_set_winner(self, client, match, db_session):
        s1 = GameSet(match_id=match.id, set_num=1, winner="player_a")
        s2 = GameSet(match_id=match.id, set_num=2)
        db_session.add_all([s1, s2])
        db_session.flush()
        _rally(db_session, s1, 1, "player_b")
        db_session.commit()

        data = client.get(f"/api/annotation/{match.id}/state").json()["data"]
        assert data["current_set_num"] == 2
        assert data["current_rally_num"] == 1
        # 第2セットのサーバは第1セットの勝者であって、
        # 第1セット最後のラリーの勝者ではない
        assert data["next_server"] == "player_a"


class TestRallyCountServer:
    def test_rally_count_returns_next_server(self, client, match, db_session):
        gs = GameSet(match_id=match.id, set_num=1)
        db_session.add(gs)
        db_session.flush()
        _rally(db_session, gs, 1, "player_a")
        db_session.commit()

        data = client.get(f"/api/sets/{gs.id}/rally_count").json()["data"]
        assert data["next_rally_num"] == 2
        assert data["next_server"] == "player_a"

    def test_rally_count_404s_for_unknown_set(self, client):
        assert client.get("/api/sets/99999999/rally_count").status_code == 404
