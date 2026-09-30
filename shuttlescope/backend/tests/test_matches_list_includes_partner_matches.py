"""試合一覧を選手 ID で絞った時に、ダブルスの相方として出た試合も入る。

選手ロールの一覧は「ダブルスの partner も含む 4 役」で、B 側の相方の勝敗反転まで対応している。
admin / analyst / coach が player_id で絞る時だけ、player_a / player_b しか見ておらず、
相方として出た試合が一覧から消えていた。
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import Match, Player
from backend.main import app
from backend.utils.auth import AuthCtx, get_auth


def _admin():
    return AuthCtx(role="admin", player_id=None, user_id=1, team_name=None, team_id=None)


@pytest.fixture()
def world(db_session, monkeypatch):
    names = ["T", "P", "O1", "O2", "Solo1", "Solo2"]
    ply = {}
    for nm in names:
        p = Player(name=nm, dominant_hand="R")
        db_session.add(p)
        db_session.flush()
        ply[nm] = p

    def match(a, b, pa=None, pb=None, fmt="mixed_doubles"):
        m = Match(tournament="t", tournament_level="IC", round="1", date=date(2025, 1, 1), format=fmt,
                  player_a_id=ply[a].id, player_b_id=ply[b].id,
                  partner_a_id=ply[pa].id if pa else None, partner_b_id=ply[pb].id if pb else None,
                  result="win", annotation_status="complete", annotation_progress=1.0)
        db_session.add(m)
        db_session.flush()
        return m

    doubles = match("T", "O1", pa="P", pb="O2")         # P は A 側の相方
    singles = match("Solo1", "Solo2", fmt="singles")
    db_session.commit()

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_auth] = _admin
    # 一覧ルートは get_auth(request) を直接呼ぶので、ルート内の参照も差し替える
    monkeypatch.setattr("backend.routers.matches.get_auth", lambda request: _admin())
    yield TestClient(app), ply, doubles, singles
    app.dependency_overrides.clear()


def _ids(client, player_id):
    r = client.get(f"/api/matches?player_id={player_id}")
    assert r.status_code == 200, r.text
    return {m["id"] for m in r.json()["data"]}


def test_partner_sees_the_doubles_match_they_played(world):
    client, ply, doubles, singles = world
    assert _ids(client, ply["P"].id) == {doubles.id}        # 旧: 空


def test_partner_on_the_b_side_too(world):
    client, ply, doubles, singles = world
    assert _ids(client, ply["O2"].id) == {doubles.id}


def test_the_named_players_still_see_theirs_and_nothing_else(world):
    client, ply, doubles, singles = world
    assert _ids(client, ply["T"].id) == {doubles.id}
    assert _ids(client, ply["O1"].id) == {doubles.id}
    assert _ids(client, ply["Solo1"].id) == {singles.id}
