"""POST /matches は未登録の選手を試合と同じトランザクションで作る。

背景:
  画面は暫定選手を1人ずつ POST /players で作ってから POST /matches を呼んでいた。
  途中の失敗で、試合に紐付かない選手だけが選手マスタに残った。
  *_new を渡すと全部を1回の commit にし、失敗したら選手も残さない。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

ADMIN_USER = "admin_atomic"
ADMIN_PASS = "AtomicAdmin1!"  # テスト用の固定値。実在の資格情報ではない。  # nosec B105


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
    # 管理者の書込み上限 (チーム作成は 30 回/分) はプロセス内の共有状態に溜まる。
    # このファイルの各テストが世界を作り直すたびにチームを作るので、前のテストの分を持ち越さない。
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


def _data(r):
    """成功応答の data を取り出す。status を先に突きつける。

    以前はこのファイル中が `r.json()["data"]` 直書きで、サーバが 500 を返すと
    `KeyError: 'data'` としか出なかった。`raise_server_exceptions=False` なので
    例外も飛んでこず、CI ログから原因を読み取れない。
    """
    assert r.status_code in (200, 201), f"{r.status_code}: {r.text}"
    return r.json()["data"]


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


def _scouting_player(client, token: str, name: str):
    return client.post("/api/players", json={
        "name": name, "dominant_hand": "R", "is_scouting": True,
    }, headers=_h(token))


@pytest.fixture()
def world(client):
    """TeamA (analyst/coach/player) と TeamB を用意する。"""
    admin = _login(client, ADMIN_USER, ADMIN_PASS)
    a = _team(client, admin, "AtomicTeamA", "AA-001")
    b = _team(client, admin, "AtomicTeamB", "AB-001")
    # テスト用の固定パスワード。実在の資格情報ではない。
    _user(client, admin, username="an_at1", password="AnalystA-1234567!",  # nosec B106
          role="analyst", team_id=a)
    _user(client, admin, username="co_at1", password="CoachA-1234567!",  # nosec B106
          role="coach", team_id=a)
    _user(client, admin, username="an_bt1", password="AnalystB-1234567!",  # nosec B106
          role="analyst", team_id=b)
    return {
        "admin": admin,
        "team_a": a,
        "team_b": b,
        "analyst_a": _login(client, "an_at1", "AnalystA-1234567!"),
        "coach_a": _login(client, "co_at1", "CoachA-1234567!"),
        "analyst_b": _login(client, "an_bt1", "AnalystB-1234567!"),
    }



def _names(client, admin_token: str) -> list[str]:
    r = client.get("/api/players", headers=_h(admin_token))
    assert r.status_code == 200, r.text
    return [p["name"] for p in r.json()["data"]]


def _body(**extra) -> dict:
    body = {
        "tournament": "Atomic", "tournament_level": "IC", "round": "1R",
        "date": "2026-01-01", "format": "singles", "result": "win",
    }
    body.update(extra)
    return body


def _new(name: str, team: str, **extra) -> dict:
    return {"name": name, "team": team, "dominant_hand": "R",
            "profile_status": "provisional", "needs_review": True, **extra}


def test_new_players_are_created_with_the_match(client, world):
    tok = world["analyst_a"]
    r = client.post("/api/matches", json=_body(
        player_a_new=_new("Atomic A", "AtomicTeamA", is_target=True),
        player_b_new=_new("Atomic B", "AtomicTeamA"),
    ), headers=_h(tok))
    assert r.status_code == 201, r.text
    data = r.json()["data"]
    assert data["player_a_id"] and data["player_b_id"]
    names = _names(client, world["admin"])
    assert "Atomic A" in names and "Atomic B" in names


def test_failure_after_the_first_player_leaves_no_orphan(client, world):
    """B の登録が拒否されたら、先に作った A も残らない。"""
    tok = world["analyst_a"]
    r = client.post("/api/matches", json=_body(
        player_a_new=_new("Orphan A", "AtomicTeamA"),
        player_b_new=_new("Orphan B", "AtomicTeamB"),  # analyst は他チーム選手を作れない
    ), headers=_h(tok))
    assert r.status_code == 403, r.text
    names = _names(client, world["admin"])
    assert "Orphan A" not in names and "Orphan B" not in names


def test_both_id_and_new_for_the_same_slot_is_refused(client, world):
    tok = world["analyst_a"]
    r = client.post("/api/matches", json=_body(
        player_a_id=1,
        player_a_new=_new("Both A", "AtomicTeamA"),
        player_b_new=_new("Both B", "AtomicTeamA"),
    ), headers=_h(tok))
    assert r.status_code == 422, r.text
    assert "Both A" not in _names(client, world["admin"])


def test_missing_player_slot_is_refused(client, world):
    tok = world["analyst_a"]
    r = client.post("/api/matches", json=_body(
        player_a_new=_new("Lonely A", "AtomicTeamA"),
    ), headers=_h(tok))
    assert r.status_code == 422, r.text
    assert "Lonely A" not in _names(client, world["admin"])


def test_coach_cannot_create_players_through_a_match(client, world):
    r = client.post("/api/matches", json=_body(
        player_a_new=_new("Coach A", "AtomicTeamA"),
        player_b_new=_new("Coach B", "AtomicTeamA"),
    ), headers=_h(world["coach_a"]))
    assert r.status_code == 403, r.text


def test_update_can_swap_in_a_new_player_and_rolls_back_on_failure(client, world):
    tok = world["analyst_a"]
    created = client.post("/api/matches", json=_body(
        player_a_new=_new("Upd A", "AtomicTeamA", is_target=True),
        player_b_new=_new("Upd B", "AtomicTeamA"),
    ), headers=_h(tok))
    assert created.status_code == 201, created.text
    mid = created.json()["data"]["id"]

    ok = client.put(f"/api/matches/{mid}", json={
        "player_b_new": _new("Upd B2", "AtomicTeamA"),
    }, headers=_h(tok))
    assert ok.status_code == 200, ok.text
    assert "Upd B2" in _names(client, world["admin"])

    bad = client.put(f"/api/matches/{mid}", json={
        "player_b_new": _new("Upd Orphan", "AtomicTeamB"),
    }, headers=_h(tok))
    assert bad.status_code == 403, bad.text
    assert "Upd Orphan" not in _names(client, world["admin"])
