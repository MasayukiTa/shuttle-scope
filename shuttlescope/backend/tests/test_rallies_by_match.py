"""GET /api/rallies/match/{match_id} のテスト (A-4)。

このルートは存在せず、モバイル注釈は無い `GET /rallies?match_id=` を叩いて
405 を受けていた。既存ラリーが一件も取れないので、リロードのたびに
スコアが 0-0 に戻り rally_num が 1 から重複していた。

ここで固定するのは 3 点:
  - セット順 → ラリー番号順で、その試合の全ラリーが返ること
  - `uuid` が入っていること (クライアントの重複排除キー。返していなかったため
    ガードが死んでいた)
  - 別の試合のラリーが混ざらないこと
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


def _make_match(db_session, tournament: str) -> Match:
    a = Player(name=f"{tournament}-A", dominant_hand="R")
    b = Player(name=f"{tournament}-B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament=tournament,
        date="2026-09-18",
        format="singles",
        player_a_id=a.id,
        player_b_id=b.id,
        result="unknown",
    )
    db_session.add(m)
    db_session.flush()
    return m


def _add_rally(db_session, gs: GameSet, rally_num: int) -> Rally:
    r = Rally(
        set_id=gs.id,
        rally_num=rally_num,
        server="player_a",
        winner="player_a",
        end_type="ace",
        rally_length=3,
        score_a_after=rally_num,
        score_b_after=0,
    )
    db_session.add(r)
    db_session.flush()
    return r


@pytest.fixture()
def match_with_rallies(db_session):
    m = _make_match(db_session, "対象試合")
    # わざとセットを逆順に作って、並び順が set_num 由来であることを確かめる
    s2 = GameSet(match_id=m.id, set_num=2)
    s1 = GameSet(match_id=m.id, set_num=1)
    db_session.add_all([s2, s1])
    db_session.flush()
    _add_rally(db_session, s1, 1)
    _add_rally(db_session, s1, 2)
    _add_rally(db_session, s2, 1)

    other = _make_match(db_session, "別の試合")
    so = GameSet(match_id=other.id, set_num=1)
    db_session.add(so)
    db_session.flush()
    _add_rally(db_session, so, 1)

    db_session.commit()
    return m


class TestRalliesByMatch:
    def test_returns_all_rallies_in_set_then_rally_order(self, client, match_with_rallies):
        res = client.get(f"/api/rallies/match/{match_with_rallies.id}")
        assert res.status_code == 200
        data = res.json()["data"]
        assert [(r["rally_num"]) for r in data] == [1, 2, 1]
        assert len(data) == 3

    def test_includes_uuid_for_client_dedupe(self, client, match_with_rallies):
        res = client.get(f"/api/rallies/match/{match_with_rallies.id}")
        data = res.json()["data"]
        uuids = [r.get("uuid") for r in data]
        assert all(u for u in uuids), "uuid が無いとクライアントの重複排除が効かない"
        assert len(set(uuids)) == len(uuids)

    def test_does_not_leak_other_matches(self, client, match_with_rallies):
        res = client.get(f"/api/rallies/match/{match_with_rallies.id}")
        set_ids = {r["set_id"] for r in res.json()["data"]}
        assert len(set_ids) == 2

    def test_unknown_match_is_404(self, client):
        res = client.get("/api/rallies/match/99999999")
        assert res.status_code == 404
