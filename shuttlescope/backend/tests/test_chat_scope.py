"""Conversational scope full-flow tests.

ターン跨ぎでスコープが持続する／個別追加できる／明示クリアで消える、を検証。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db import database as _db_module
from backend.db.database import Base
from backend.utils.auth import AuthCtx, get_auth
from backend.analysis.insights.safety import reset_for_test as reset_budget
from backend.routers import insights_chat as chat_router_mod


_CLIENT = TestClient(app, base_url="http://localhost")


def _ctx(user_id: int = 300) -> AuthCtx:
    return AuthCtx(role="coach", player_id=None, user_id=user_id,
                   team_name=None, team_id=None)


@pytest.fixture(autouse=True)
def _fresh_state():
    chat_router_mod._RATE_LIMIT.clear()
    reset_budget()
    Base.metadata.drop_all(_db_module.engine)
    Base.metadata.create_all(_db_module.engine)
    app.dependency_overrides[get_auth] = lambda: _ctx()
    yield
    app.dependency_overrides.pop(get_auth, None)


def _new_session() -> int:
    r = _CLIENT.post("/api/insights/chat/sessions", json={"lang": "ja"})
    assert r.status_code == 200, r.text
    return r.json()["session_id"]


def _send(sid: int, content: str, **extra) -> dict:
    import time
    # 2 秒 rate-limit 回避のためテーブルを毎回 clear
    chat_router_mod._RATE_LIMIT.clear()
    r = _CLIENT.post(
        f"/api/insights/chat/sessions/{sid}/messages",
        json={"content": content, **extra},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_scope_persists_across_turns():
    sid = _new_session()

    # Turn 1: 先月のスマッシュ
    r1 = _send(sid, "先月のスマッシュは?")
    sc1 = r1["applied_scope"]
    assert sc1["period"] is not None
    assert sc1["period"]["date_from"] == "2026-04-01"
    assert sc1["shot_type"]["code"] == "smash"
    assert sc1["zone"] is None

    # Turn 2: zone のみ追加 → period/shot_type は維持
    r2 = _send(sid, "バック奥では?")
    sc2 = r2["applied_scope"]
    assert sc2["period"]["date_from"] == "2026-04-01"  # 維持
    assert sc2["shot_type"]["code"] == "smash"          # 維持
    assert sc2["zone"]["code"] == "BR"                   # 追加


def test_scope_full_reset():
    sid = _new_session()
    _send(sid, "先月のスマッシュ、バック奥について")
    r2 = _send(sid, "全部リセットして")
    sc = r2["applied_scope"]
    assert sc["period"] is None
    assert sc["shot_type"] is None
    assert sc["zone"] is None


def test_scope_individual_clear():
    sid = _new_session()
    _send(sid, "先月のスマッシュ、バック奥")
    # period のみ明示クリア
    r2 = _send(sid, "じゃあ全期間で見て", clear_slots=["period"])
    sc = r2["applied_scope"]
    assert sc["period"] is None
    assert sc["shot_type"]["code"] == "smash"
    assert sc["zone"]["code"] == "BR"


def test_client_period_beats_extractor():
    """body の date_from/date_to は extracted period より優先される (確定値)。"""
    sid = _new_session()
    r = _send(
        sid,
        "先月のスマッシュ",
        date_from="2026-01-01",
        date_to="2026-01-31",
    )
    sc = r["applied_scope"]
    # client 指定が勝つ
    assert sc["period"]["date_from"] == "2026-01-01"
    assert sc["period"]["date_to"] == "2026-01-31"


def test_list_messages_returns_scope():
    sid = _new_session()
    _send(sid, "先月のスマッシュ")
    r = _CLIENT.get(f"/api/insights/chat/sessions/{sid}/messages")
    assert r.status_code == 200
    body = r.json()
    assert body["applied_scope"] is not None
    assert body["applied_scope"]["shot_type"]["code"] == "smash"
