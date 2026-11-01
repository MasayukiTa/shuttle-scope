"""POST /api/matches が登録フォームの送る format / result 値を受理することを固定する。

背景:
    _MATCH_FORMAT_ALLOWED は {singles, doubles, mixed} だったが、登録フォーム
    (MatchListPage.tsx) と解析コード・既存テストは singles / mens_doubles /
    womens_doubles / mixed_doubles を使う。_MATCH_RESULT_ALLOWED はフォーム既定の
    "unfinished" (quick-start が保存する値) と フォーム選択肢の "walkover" を欠いて
    いた。両集合を拡張し、フォームが送る値と既に DB に保存済みの値を全て受理する。

値はすべて架空。実在の資格情報・従業員 ID は含まない。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import Player, Team
from backend.main import app
from backend.utils.jwt_utils import create_access_token

_TEAM_ID = 9101


def _headers() -> dict:
    tok = create_access_token(
        user_id=99, role="admin", player_id=None, team_name="T", team_id=_TEAM_ID
    )
    return {"Authorization": f"Bearer {tok}"}


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture()
def players(db_session):
    """owner_team_id 解決に使う Team と、試合に必要な 2 選手を用意する。

    create_match は admin の team_id (=9101) を owner に解決するため Team 9101 が
    実在している必要がある。選手は referential integrity 検証を通すため実在させる。
    NOT NULL 列 (name) を明示して IntegrityError を避ける。
    """
    team = Team(id=_TEAM_ID, name="T", display_id="T-1")
    db_session.add(team)
    db_session.flush()
    a = Player(name="フォーム値A", team_id=_TEAM_ID, dominant_hand="R")
    b = Player(name="フォーム値B", team_id=_TEAM_ID, dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    db_session.commit()
    return a, b


def _body(players, **extra) -> dict:
    a, b = players
    body = {
        "tournament": "FormValues",
        "tournament_level": "IC",
        "round": "1R",
        "date": "2026-01-01",
        "format": "singles",
        "result": "win",
        "player_a_id": a.id,
        "player_b_id": b.id,
    }
    body.update(extra)
    return body


# 登録フォーム (MatchListPage.tsx) と解析コードが使う format 値。
_FORM_FORMATS = ["singles", "mens_doubles", "womens_doubles", "mixed_doubles"]
# 既存コードが保持してきた旧 format 値 (互換のため受理し続ける)。
_LEGACY_FORMATS = ["doubles", "mixed"]

# 登録フォームが送る result 値 (既定は "unfinished"、選択肢に "walkover")。
_FORM_RESULTS = ["win", "loss", "draw", "unknown", "retired", "unfinished", "walkover"]


@pytest.mark.parametrize("fmt", _FORM_FORMATS + _LEGACY_FORMATS)
def test_create_accepts_every_form_format(client, players, fmt):
    r = client.post("/api/matches", json=_body(players, format=fmt), headers=_headers())
    assert r.status_code in (200, 201), r.text
    assert r.json()["data"]["format"] == fmt


@pytest.mark.parametrize("result", _FORM_RESULTS)
def test_create_accepts_every_form_result(client, players, result):
    r = client.post("/api/matches", json=_body(players, result=result), headers=_headers())
    assert r.status_code in (200, 201), r.text
    assert r.json()["data"]["result"] == result


def test_create_rejects_bogus_format(client, players):
    r = client.post("/api/matches", json=_body(players, format="bogus"), headers=_headers())
    assert r.status_code == 422, r.text


def test_create_rejects_bogus_result(client, players):
    r = client.post("/api/matches", json=_body(players, result="bogus"), headers=_headers())
    assert r.status_code == 422, r.text
