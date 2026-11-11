"""パスワード未設定 (password_hash NULL) の既存セッションを
共有モーダルが開いたときの自動生成フローが依拠する
サーバ側の契約を固定する:

  1. 未設定セッションは has_password=false であり、join できない (403)。
  2. regenerate-password を呼ぶと平文が返り、has_password=true になる。
  3. その平文で join できる。

フロント (SessionShareModal) は hasPassword=false のとき regenerate を 1 回だけ
呼んでこの契約に乗る。
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import get_db
from backend.db.models import Player, Match, SharedSession


def _make_match(db) -> Match:
    pa = Player(name="選手A")
    pb = Player(name="選手B")
    db.add_all([pa, pb])
    db.flush()
    m = Match(
        tournament="テスト大会",
        tournament_level="IC",
        round="1回戦",
        date=date(2026, 4, 8),
        format="singles",
        player_a_id=pa.id,
        player_b_id=pb.id,
        result="win",
    )
    db.add(m)
    db.flush()
    return m


@pytest.fixture
def lan_client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app, headers={"X-Role": "analyst"})
    yield client
    app.dependency_overrides.clear()


def _make_passwordless_session(db, code="NOPASS1") -> Match:
    match = _make_match(db)
    db.commit()
    session = SharedSession(
        match_id=match.id,
        session_code=code,
        created_by_role="analyst",
    )
    db.add(session)
    db.commit()
    return match


class TestAutoPasswordBackfill:
    def test_passwordless_session_reports_no_password_and_refuses_join(self, lan_client, db_session):
        _make_passwordless_session(db_session)

        info = lan_client.get("/api/sessions/NOPASS1")
        assert info.status_code == 200
        assert info.json()["data"]["has_password"] is False

        refused = lan_client.post("/api/sessions/NOPASS1/join", json={"role": "viewer"})
        assert refused.status_code == 403

    def test_regenerate_backfills_password_then_join_succeeds(self, lan_client, db_session):
        _make_passwordless_session(db_session)

        gen = lan_client.post("/api/sessions/NOPASS1/regenerate-password")
        assert gen.status_code == 200
        new_password = gen.json()["data"]["session_password"]
        assert len(new_password) >= 8

        info = lan_client.get("/api/sessions/NOPASS1")
        assert info.json()["data"]["has_password"] is True

        joined = lan_client.post("/api/sessions/NOPASS1/join", json={
            "role": "viewer",
            "device_name": "テスト端末",
            "device_type": "iphone",
            "session_password": new_password,
        })
        assert joined.status_code == 200
        assert joined.json()["data"]["participant_id"] is not None
