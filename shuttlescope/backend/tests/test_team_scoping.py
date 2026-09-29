"""Phase B チーム境界（team scoping）の動作検証。

カバレッジ:
- coach が他チーム所有試合を直叩きしても 404
- admin が is_public_pool=true で登録した試合は他チームから閲覧可
- 公開プール試合に自チーム選手が登場すれば一覧に出る
- coach/analyst が POST /matches で owner_team_id を指定しても ctx.team_id 強制
- is_public_pool は admin のみ true 設定可
- team_id 変更は admin のみ
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

ADMIN_USER = "admin_ts"
ADMIN_PASS = "TeamScope1!"


@pytest.fixture()
def client(test_engine, monkeypatch):
    from backend.routers import auth as _auth_module
    _auth_module._IP_LOGIN_TIMES.clear()
    from backend.db.models import (
        User, RefreshToken, RevokedToken, AccessLog,
        Match, Player, Team,
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
    from backend.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _login(client, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={
        "grant_type": "credential", "identifier": username, "password": password,
    })
    assert r.status_code == 200, r.text
    return r.json()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_team(client, admin_token: str, name: str, display_id: str) -> int:
    r = client.post(
        "/api/auth/teams",
        json={"name": name, "display_id": display_id},
        headers=_h(admin_token),
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]["id"]


def _create_user(client, admin_token: str, *, username: str, password: str,
                 role: str, team_id: int) -> int:
    r = client.post(
        "/api/auth/users",
        json={
            "username": username,
            "role": role,
            "display_name": username,
            "password": password,
            "team_id": team_id,
        },
        headers=_h(admin_token),
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]["id"]


def _create_player(client, token: str, name: str, team: str = "TestTeam") -> int:
    body = {"name": name, "dominant_hand": "R", "team": team}
    r = client.post("/api/players", json=body, headers=_h(token))
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]["id"]


def _create_match(client, token: str, *, player_a_id: int, player_b_id: int,
                  is_public_pool: bool = False, owner_team_id: int | None = None) -> dict:
    body = {
        "tournament": "Test",
        "tournament_level": "IC",
        "round": "1R",
        "date": "2026-01-01",
        "format": "singles",
        "player_a_id": player_a_id,
        "player_b_id": player_b_id,
        "result": "win",
    }
    if is_public_pool:
        body["is_public_pool"] = True
    if owner_team_id is not None:
        body["owner_team_id"] = owner_team_id
    r = client.post("/api/matches", json=body, headers=_h(token))
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]


class TestTeamScoping:
    def test_coach_cannot_access_other_team_match(self, client):
        admin = _login(client, ADMIN_USER, ADMIN_PASS)
        admin_token = admin["access_token"]

        team_a = _create_team(client, admin_token, "TeamA", "TA-001")
        team_b = _create_team(client, admin_token, "TeamB", "TB-001")
        _create_user(client, admin_token, username="coach_a01", password="CoachA-1234567!",
                     role="coach", team_id=team_a)
        _create_user(client, admin_token, username="coach_b01", password="CoachB-1234567!",
                     role="coach", team_id=team_b)
        coach_a = _login(client, "coach_a01", "CoachA-1234567!")
        coach_b = _login(client, "coach_b01", "CoachB-1234567!")

        # 選手は admin が作成。coach_a が試合作成するため自チーム選手が必要
        pa = _create_player(client, admin_token, "PA", team="TeamA")
        pb = _create_player(client, admin_token, "PB", team="TeamA")
        # coach_a が試合を作成（owner=TeamA に強制注入される）
        m = _create_match(client, coach_a["access_token"], player_a_id=pa, player_b_id=pb)
        assert m["owner_team_id"] == team_a
        assert m["is_public_pool"] is False

        # coach_b が直叩き → 404（存在を隠す）
        r = client.get(f"/api/matches/{m['id']}", headers=_h(coach_b["access_token"]))
        assert r.status_code == 404

        # coach_b の一覧にも出ない
        r = client.get("/api/matches", headers=_h(coach_b["access_token"]))
        assert r.status_code == 200
        ids = [x["id"] for x in r.json()["data"]]
        assert m["id"] not in ids

    def test_admin_public_pool_visible_to_other_teams(self, client):
        admin = _login(client, ADMIN_USER, ADMIN_PASS)
        admin_token = admin["access_token"]

        team_a = _create_team(client, admin_token, "TeamA", "TA-002")
        team_b = _create_team(client, admin_token, "TeamB", "TB-002")
        _create_user(client, admin_token, username="coach_a02", password="CoachA-1234567!",
                     role="coach", team_id=team_a)
        _create_user(client, admin_token, username="coach_b02", password="CoachB-1234567!",
                     role="coach", team_id=team_b)
        coach_b = _login(client, "coach_b02", "CoachB-1234567!")

        # admin が公開プールで作成
        pa = _create_player(client, admin_token, "BWF-A")
        pb = _create_player(client, admin_token, "BWF-B")
        m = _create_match(
            client, admin_token,
            player_a_id=pa, player_b_id=pb,
            is_public_pool=True, owner_team_id=team_a,
        )
        assert m["is_public_pool"] is True

        # 他チームの coach_b からも閲覧可
        r = client.get(f"/api/matches/{m['id']}", headers=_h(coach_b["access_token"]))
        assert r.status_code == 200
        # 一覧にも出る
        r = client.get("/api/matches", headers=_h(coach_b["access_token"]))
        ids = [x["id"] for x in r.json()["data"]]
        assert m["id"] in ids

    def test_coach_cannot_set_public_pool(self, client):
        admin = _login(client, ADMIN_USER, ADMIN_PASS)
        admin_token = admin["access_token"]
        team_a = _create_team(client, admin_token, "TeamA", "TA-003")
        _create_user(client, admin_token, username="coach_a03", password="CoachA-1234567!",
                     role="coach", team_id=team_a)
        coach_a = _login(client, "coach_a03", "CoachA-1234567!")

        pa = _create_player(client, admin_token, "PA3", team="TeamA")
        pb = _create_player(client, admin_token, "PB3", team="TeamA")
        # coach が is_public_pool=True を投げてもサーバ側で False に強制される
        m = _create_match(
            client, coach_a["access_token"],
            player_a_id=pa, player_b_id=pb,
            is_public_pool=True,
            # owner_team_id を別チームに偽装しようとしても ctx.team_id に強制
            owner_team_id=999,
        )
        assert m["is_public_pool"] is False
        assert m["owner_team_id"] == team_a

    def test_team_id_change_admin_only(self, client):
        admin = _login(client, ADMIN_USER, ADMIN_PASS)
        admin_token = admin["access_token"]
        team_a = _create_team(client, admin_token, "TeamA", "TA-004")
        team_b = _create_team(client, admin_token, "TeamB", "TB-004")
        coach_id = _create_user(client, admin_token, username="coach_a04",
                                password="CoachA-1234567!", role="coach", team_id=team_a)
        coach_a = _login(client, "coach_a04", "CoachA-1234567!")

        # coach 自身が他人の team_id を変えようとしても 403
        r = client.put(
            f"/api/auth/users/{coach_id}",
            json={"team_id": team_b},
            headers=_h(coach_a["access_token"]),
        )
        assert r.status_code == 403

        # admin なら可能
        r = client.put(
            f"/api/auth/users/{coach_id}",
            json={"team_id": team_b},
            headers=_h(admin_token),
        )
        assert r.status_code == 200, r.text
