"""rvm1-03 / rvm1-04 の回帰テスト。

- rvm1-04: SharedSession を持つ試合の削除は 200 で成功し、SharedSession を残さない。
  (PostgreSQL では FK 違反で 500 になり得る欠陥。SQLite では孤児が残っていた。)
- rvm1-03: 記録済みの GameSet がある試合で選手を差し替えると 409 で拒否される。
  大会名など選手以外の項目だけの更新は従来どおり 200 で通る。

ORM 行は NOT NULL 列を全て埋める (conftest の test_engine にバインドされた
SessionLocal を使い、アプリと同じ DB に書く)。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

ADMIN_USER = "admin_h20a"
ADMIN_PASS = "H20aAdmin1!"  # テスト用の固定値。実在の資格情報ではない。  # nosec B105


@pytest.fixture()
def client(test_engine, monkeypatch):
    from backend.routers import auth as _auth_module
    _auth_module._IP_LOGIN_TIMES.clear()
    from backend.db.models import (
        User, RefreshToken, RevokedToken, AccessLog, Match, Player, Team,
    )
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=test_engine)
    with Session() as s:
        s.query(AccessLog).delete()
        s.query(RefreshToken).delete()
        s.query(RevokedToken).delete()
        s.query(Match).delete()
        s.query(Player).delete()
        s.query(User).delete()
        s.query(Team).delete()
        s.commit()

    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", ADMIN_PASS)
    from backend.config import settings
    settings.BOOTSTRAP_ADMIN_USERNAME = ADMIN_USER
    settings.BOOTSTRAP_ADMIN_PASSWORD = ADMIN_PASS
    from backend.main import app, AdminWriteRateLimitMiddleware
    AdminWriteRateLimitMiddleware._state.clear()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    AdminWriteRateLimitMiddleware._state.clear()


def _login(client, username: str, password: str) -> str:
    r = client.post("/api/auth/login", json={
        "grant_type": "credential", "identifier": username, "password": password,
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _team(client, admin_token: str, name: str, display_id: str) -> int:
    r = client.post("/api/auth/teams", json={"name": name, "display_id": display_id},
                    headers=_h(admin_token))
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]["id"]


def _user(client, admin_token: str, *, username: str, password: str,
          role: str, team_id: int) -> None:
    r = client.post("/api/auth/users", json={
        "username": username, "role": role, "display_name": username,
        "password": password, "team_id": team_id,
    }, headers=_h(admin_token))
    assert r.status_code in (200, 201), r.text


def _player(client, token: str, name: str, team: str) -> int:
    r = client.post("/api/players", json={
        "name": name, "team": team, "dominant_hand": "R",
        "profile_status": "provisional", "needs_review": True,
    }, headers=_h(token))
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]["id"]


def _match(client, token: str, player_a_id: int, player_b_id: int,
           tournament: str = "H20A") -> int:
    r = client.post("/api/matches", json={
        "tournament": tournament, "tournament_level": "IC", "round": "1R",
        "date": "2026-01-01", "format": "singles", "result": "win",
        "player_a_id": player_a_id, "player_b_id": player_b_id,
    }, headers=_h(token))
    assert r.status_code == 201, r.text
    return r.json()["data"]["id"]


def _db():
    """conftest の test_engine にバインド済みの SessionLocal を返す。"""
    from backend.db import database as db_module
    return db_module.SessionLocal()


def _add_game_set(match_id: int, set_num: int = 1) -> int:
    from backend.db.models import GameSet
    s = _db()
    try:
        gs = GameSet(match_id=match_id, set_num=set_num, score_a=21, score_b=15)
        s.add(gs)
        s.commit()
        s.refresh(gs)
        return gs.id
    finally:
        s.close()


def _add_shared_session(match_id: int, code: str) -> int:
    from backend.db.models import SharedSession
    s = _db()
    try:
        ss = SharedSession(match_id=match_id, session_code=code)
        s.add(ss)
        s.commit()
        s.refresh(ss)
        return ss.id
    finally:
        s.close()


def _count_shared_sessions(match_id: int) -> int:
    from backend.db.models import SharedSession
    s = _db()
    try:
        return s.query(SharedSession).filter(SharedSession.match_id == match_id).count()
    finally:
        s.close()


@pytest.fixture()
def world(client):
    admin = _login(client, ADMIN_USER, ADMIN_PASS)
    a = _team(client, admin, "H20aTeamA", "HA-001")
    # テスト用の固定パスワード。実在の資格情報ではない。
    _user(client, admin, username="an_h20a", password="AnalystH20a-1234567!",  # nosec B106
          role="analyst", team_id=a)
    analyst = _login(client, "an_h20a", "AnalystH20a-1234567!")
    pa = _player(client, analyst, "H20A PlayerA", "H20aTeamA")
    pb = _player(client, analyst, "H20A PlayerB", "H20aTeamA")
    pc = _player(client, analyst, "H20A PlayerC", "H20aTeamA")
    return {"admin": admin, "analyst": analyst, "team_a": a,
            "pa": pa, "pb": pb, "pc": pc}


def test_delete_match_with_shared_session_returns_200_and_leaves_none(client, world):
    tok = world["analyst"]
    mid = _match(client, tok, world["pa"], world["pb"])
    _add_shared_session(mid, code="H20ASS1")
    assert _count_shared_sessions(mid) == 1

    r = client.delete(f"/api/matches/{mid}", headers=_h(tok))
    assert r.status_code == 200, r.text
    assert _count_shared_sessions(mid) == 0


def test_swap_player_with_a_game_set_returns_409(client, world):
    tok = world["analyst"]
    mid = _match(client, tok, world["pa"], world["pb"])
    _add_game_set(mid, set_num=1)

    r = client.put(f"/api/matches/{mid}", json={"player_a_id": world["pc"]},
                   headers=_h(tok))
    assert r.status_code == 409, r.text
    assert "選手は変更できません" in r.json().get("detail", "")


def test_update_tournament_name_with_a_game_set_returns_200(client, world):
    tok = world["analyst"]
    mid = _match(client, tok, world["pa"], world["pb"])
    _add_game_set(mid, set_num=1)

    r = client.put(f"/api/matches/{mid}", json={"tournament": "H20A Renamed"},
                   headers=_h(tok))
    assert r.status_code == 200, r.text
    assert r.json()["data"]["tournament"] == "H20A Renamed"
