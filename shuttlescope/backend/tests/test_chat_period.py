"""Chat message period (date_from / date_to) wiring tests.

検証ポイント:
  - send_message に date_from / date_to を渡せる
  - 値が ChatMessage の user 行に永続化される
  - 不正な ISO 文字列 (2025-13-40 等) は 422 で拒否される
  - date_from/date_to が _build_analytics_context 経由で
    build_player_summary に同じ値で渡される
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db import database as _db_module
from backend.db.database import Base
from backend.db.models import ChatMessage
from backend.utils.auth import AuthCtx, get_auth
from backend.analysis.insights.safety import reset_for_test as reset_budget
from backend.routers import insights_chat as chat_router_mod


_CLIENT = TestClient(app, base_url="http://localhost")


def _ctx(role: str = "coach", user_id: int = 200) -> AuthCtx:
    return AuthCtx(role=role, player_id=None, user_id=user_id,
                   team_name=None, team_id=None)


def _override(role: str = "coach", user_id: int = 200):
    app.dependency_overrides[get_auth] = lambda: _ctx(role, user_id)


@pytest.fixture(autouse=True)
def _fresh_state():
    chat_router_mod._RATE_LIMIT.clear()
    reset_budget()
    Base.metadata.drop_all(_db_module.engine)
    Base.metadata.create_all(_db_module.engine)
    yield
    app.dependency_overrides.pop(get_auth, None)


def _new_session(user_id: int = 200) -> int:
    _override("coach", user_id=user_id)
    r = _CLIENT.post("/api/insights/chat/sessions", json={"lang": "ja"})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def test_send_message_accepts_period():
    sid = _new_session()
    r = _CLIENT.post(
        f"/api/insights/chat/sessions/{sid}/messages",
        json={
            "content": "直近3ヶ月の伸びしろは?",
            "date_from": "2026-02-24",
            "date_to": "2026-05-23",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user_message"]["date_from"] == "2026-02-24"
    assert body["user_message"]["date_to"] == "2026-05-23"


def test_period_persisted_on_chat_message_row():
    sid = _new_session(user_id=201)
    r = _CLIENT.post(
        f"/api/insights/chat/sessions/{sid}/messages",
        json={
            "content": "先月の試合",
            "date_from": "2026-04-01",
            "date_to": "2026-04-30",
        },
    )
    assert r.status_code == 200, r.text
    user_id_from_resp = r.json()["user_message"]["id"]
    with _db_module.SessionLocal() as db:
        user_row = db.query(ChatMessage).filter(ChatMessage.id == user_id_from_resp).first()
        assert user_row is not None
        assert user_row.date_from == "2026-04-01"
        assert user_row.date_to == "2026-04-30"


def test_period_omitted_is_null():
    sid = _new_session(user_id=202)
    r = _CLIENT.post(
        f"/api/insights/chat/sessions/{sid}/messages",
        json={"content": "普通の質問"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["user_message"]["date_from"] is None
    assert r.json()["user_message"]["date_to"] is None


def test_invalid_iso_date_rejected():
    sid = _new_session(user_id=203)
    r = _CLIENT.post(
        f"/api/insights/chat/sessions/{sid}/messages",
        json={
            "content": "x",
            "date_from": "2025-13-40",
        },
    )
    assert r.status_code == 422


def test_period_passed_to_player_summary():
    """build_player_summary が date_from/date_to をそのまま受け取ることを mock で確認."""
    sid = _new_session(user_id=204)
    # ctx.player_id を埋めて build_player_summary を実行パスに乗せる
    app.dependency_overrides[get_auth] = lambda: AuthCtx(
        role="coach", player_id=1, user_id=204,
        team_name=None, team_id=None,
    )
    captured = {}

    def fake_build_player_summary(db, player_id, df, dt, sections):
        captured["player_id"] = player_id
        captured["df"] = df
        captured["dt"] = dt
        captured["sections"] = sections
        return {"player_id": player_id, "sample": {"matches": 0, "rallies": 0, "strokes": 0}}

    with patch(
        "backend.analysis.insights.player_summary_service.build_player_summary",
        side_effect=fake_build_player_summary,
    ):
        r = _CLIENT.post(
            f"/api/insights/chat/sessions/{sid}/messages",
            json={
                "content": "直近3ヶ月の調子",
                "date_from": "2026-02-24",
                "date_to": "2026-05-23",
            },
        )
    assert r.status_code == 200, r.text
    assert captured.get("df") == "2026-02-24"
    assert captured.get("dt") == "2026-05-23"
    assert captured.get("player_id") == 1
