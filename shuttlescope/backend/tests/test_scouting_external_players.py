"""スカウティング用の外部選手 (0051) の権限境界。

背景:
  「一週間前に対戦相手が発表される → その相手の過去映像を取り込んで解析する」が、
  非 admin では一切成立していなかった。塞がりは 3 箇所:

    - matches.py     自チーム選手を含まない試合は 403
    - players.py     analyst は他チーム所属の選手を作成できない
    - GET /players   自チームのみを返し、解析対象セレクタを供給している

  所属 (team_id) ではなく「どのチームが登録したか」(scouting_owner_team_id) で
  可視性を決める形にして開けた。**開けた範囲が意図どおりかを確かめるのがこの
  ファイルの主目的**なので、許可より拒否のケースを厚くしてある。

  他チームの名簿と注釈データは一切見えないままであること、
  player と llm には外部選手が出ないことが、壊してはいけない不変則。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

ADMIN_USER = "admin_scout"
ADMIN_PASS = "ScoutAdmin1!"


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
    from backend.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


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


def _scouting_player(client, token: str, name: str):
    return client.post("/api/players", json={
        "name": name, "dominant_hand": "R", "is_scouting": True,
    }, headers=_h(token))


@pytest.fixture()
def world(client):
    """TeamA (analyst/coach/player) と TeamB を用意する。"""
    admin = _login(client, ADMIN_USER, ADMIN_PASS)
    a = _team(client, admin, "ScoutTeamA", "SA-001")
    b = _team(client, admin, "ScoutTeamB", "SB-001")
    # テスト用の固定パスワード。実在の資格情報ではない。
    _user(client, admin, username="an_a01", password="AnalystA-1234567!",  # nosec B106
          role="analyst", team_id=a)
    _user(client, admin, username="co_a01", password="CoachA-1234567!",  # nosec B106
          role="coach", team_id=a)
    _user(client, admin, username="an_b01", password="AnalystB-1234567!",  # nosec B106
          role="analyst", team_id=b)
    return {
        "admin": admin,
        "team_a": a,
        "team_b": b,
        "analyst_a": _login(client, "an_a01", "AnalystA-1234567!"),
        "coach_a": _login(client, "co_a01", "CoachA-1234567!"),
        "analyst_b": _login(client, "an_b01", "AnalystB-1234567!"),
    }


# ── 登録できること ──────────────────────────────────────────────────────────

def test_analyst_can_register_an_external_player(client, world):
    """これが通らないと相手選手のレコードを一件も作れない。"""
    r = _scouting_player(client, world["analyst_a"], "Opponent X")
    assert r.status_code in (200, 201), r.text
    data = r.json()["data"]
    assert data["is_scouting"] is True
    assert not data.get("team"), "外部選手に所属が付いている"


def test_coach_cannot_register_but_can_analyse(client, world):
    """coach に与えるのは「解析できること」であって登録権限ではない。

    `POST /players` は以前から `require_analyst` (analyst / admin) なので、
    coach は登録できない。ここを外部選手のために広げると、スカウティングと
    無関係な選手登録まで coach に開くことになる。
    coach に必要なのは、analyst が登録した外部選手を**見て解析できる**ことだけ。
    """
    denied = _scouting_player(client, world["coach_a"], "Opponent Y")
    assert denied.status_code == 403, denied.text

    _scouting_player(client, world["analyst_a"], "Opponent For Coach")
    listed = client.get("/api/players", headers=_h(world["coach_a"]))
    assert listed.status_code == 200, listed.text
    names = [p["name"] for p in listed.json()["data"]]
    assert "Opponent For Coach" in names, "coach が自チームの外部選手を見られない"


def test_external_player_cannot_carry_a_team(client, world):
    """所属と登録主体を混ぜさせない。混ざると可視範囲の判定が二重になる。"""
    r = client.post("/api/players", json={
        "name": "Opponent Z", "dominant_hand": "R",
        "is_scouting": True, "team": "ScoutTeamA",
    }, headers=_h(world["analyst_a"]))
    assert r.status_code == 422, r.text


def test_team_is_still_required_for_a_normal_player(client, world):
    """既存の不変則を壊していないこと。

    analyst は自チーム検査(403)のほうが先に効き、team 未指定の 422 までは
    到達しない。両方の枝が生きていることを、2 つのロールで確かめる。
    """
    as_analyst = client.post("/api/players", json={"name": "Normal", "dominant_hand": "R"},
                             headers=_h(world["analyst_a"]))
    assert as_analyst.status_code == 403, as_analyst.text

    # admin は自チーム検査を通るので、team 必須の 422 に到達する
    as_admin = client.post("/api/players", json={"name": "Normal2", "dominant_hand": "R"},
                           headers=_h(world["admin"]))
    assert as_admin.status_code == 422, as_admin.text


# ── 見える範囲 ──────────────────────────────────────────────────────────────

def test_the_registering_team_sees_its_external_player(client, world):
    _scouting_player(client, world["analyst_a"], "Opponent Visible")
    r = client.get("/api/players", headers=_h(world["analyst_a"]))
    assert r.status_code == 200, r.text
    names = [p["name"] for p in r.json()["data"]]
    assert "Opponent Visible" in names


def test_another_team_does_not_see_it(client, world):
    """**最重要**: 外部選手を足したことで他チームに漏れていないこと。"""
    _scouting_player(client, world["analyst_a"], "Opponent Secret")
    r = client.get("/api/players", headers=_h(world["analyst_b"]))
    assert r.status_code == 200, r.text
    names = [p["name"] for p in r.json()["data"]]
    assert "Opponent Secret" not in names, "他チームに外部選手が漏れている"


def test_roster_of_another_team_is_still_invisible(client, world):
    """従来のテナント境界が緩んでいないこと。"""
    admin = world["admin"]
    client.post("/api/players", json={
        "name": "B Roster", "dominant_hand": "R", "team": "ScoutTeamB",
    }, headers=_h(admin))
    r = client.get("/api/players", headers=_h(world["analyst_a"]))
    names = [p["name"] for p in r.json()["data"]]
    assert "B Roster" not in names


# ── 試合を作れること ────────────────────────────────────────────────────────

def _match_body(pa: int, pb: int) -> dict:
    return {
        "tournament": "Scouting", "tournament_level": "IC", "round": "1R",
        "date": "2026-01-01", "format": "singles",
        "player_a_id": pa, "player_b_id": pb, "result": "win",
    }


def test_a_match_between_two_external_players_can_be_created(client, world):
    """自チーム選手が1人も出ない試合＝スカウティング用の動画そのもの。

    これが 403 だと、相手の映像を取り込む経路が存在しない。
    """
    tok = world["analyst_a"]
    x = _scouting_player(client, tok, "Opp A").json()["data"]["id"]
    y = _scouting_player(client, tok, "Opp B").json()["data"]["id"]
    r = client.post("/api/matches", json=_match_body(x, y), headers=_h(tok))
    assert r.status_code in (200, 201), r.text


def test_that_match_is_owned_by_the_registering_team(client, world):
    """外部選手だけの試合でも所有チームが自チームに固定されること。

    ここが緩むと、可視性の根拠が無い試合ができてしまう。
    """
    tok = world["analyst_a"]
    x = _scouting_player(client, tok, "Opp C").json()["data"]["id"]
    y = _scouting_player(client, tok, "Opp D").json()["data"]["id"]
    m = client.post("/api/matches", json=_match_body(x, y), headers=_h(tok)).json()["data"]
    assert m.get("owner_team_id") == world["team_a"]


def test_another_team_cannot_use_someone_elses_external_players(client, world):
    """他チームが登録した外部選手で試合を作れないこと。"""
    x = _scouting_player(client, world["analyst_a"], "Opp E").json()["data"]["id"]
    y = _scouting_player(client, world["analyst_a"], "Opp F").json()["data"]["id"]
    r = client.post("/api/matches", json=_match_body(x, y),
                    headers=_h(world["analyst_b"]))
    assert r.status_code == 403, r.text


def test_a_match_with_no_own_player_and_no_own_external_player_is_still_refused(client, world):
    """穴を広げすぎていないこと。admin が作った無関係な選手同士は依然 403。"""
    admin = world["admin"]
    p1 = client.post("/api/players", json={
        "name": "Foreign 1", "dominant_hand": "R", "team": "ScoutTeamB",
    }, headers=_h(admin)).json()["data"]["id"]
    p2 = client.post("/api/players", json={
        "name": "Foreign 2", "dominant_hand": "R", "team": "ScoutTeamB",
    }, headers=_h(admin)).json()["data"]["id"]
    r = client.post("/api/matches", json=_match_body(p1, p2),
                    headers=_h(world["analyst_a"]))
    assert r.status_code == 403, r.text
