"""セッション応答の password_set フラグ (fix/session-pw-set-flag)。

症状: サーバはパスワードのハッシュだけを保存し、平文は再読み込み後の応答に含めない。
そのため UI が「設定済み」を判定できるよう、真偽の password_set を返す。
また生成文字集合から紛らわしい文字 (0 O o 1 l I) を除く。
"""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import get_db
from backend.db.models import Player, Match
from backend.routers.sessions import _generate_password


def _make_match(db):
    pa = Player(name="Aさん")
    pb = Player(name="Bさん")
    db.add(pa)
    db.add(pb)
    db.flush()
    m = Match(
        tournament="テスト大会",
        tournament_level="IC",
        round="1回戦",
        date=date(2025, 1, 1),
        format="singles",
        player_a_id=pa.id,
        player_b_id=pb.id,
        result="win",
    )
    db.add(m)
    db.flush()
    return m


@pytest.fixture
def client_and_match(db_session):
    match = _make_match(db_session)
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app, headers={"X-Role": "admin"})
    yield client, match.id
    app.dependency_overrides.clear()


def _create(client, match_id):
    resp = client.post(
        "/api/sessions",
        json={"match_id": match_id, "created_by_role": "analyst"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["data"]


class TestGeneratePasswordCharset:
    """生成パスワードに紛らわしい文字を含まない。"""

    AMBIGUOUS = set("0Oo1lI")

    def test_no_ambiguous_characters(self):
        for _ in range(200):
            pw = _generate_password()
            assert not (set(pw) & self.AMBIGUOUS), pw

    def test_length_default(self):
        assert len(_generate_password()) == 8


class TestPasswordSetFlag:
    """作成時は平文と password_set 両方、再取得時は password_set のみ。"""

    def test_create_returns_plaintext_and_flag(self, client_and_match):
        client, match_id = client_and_match
        data = _create(client, match_id)
        assert data.get("password_set") is True
        assert data.get("session_password"), "作成時は平文を返す"

    def test_reload_has_flag_but_no_plaintext(self, client_and_match):
        client, match_id = client_and_match
        created = _create(client, match_id)
        code = created["session_code"]
        resp = client.get(f"/api/sessions/{code}")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        # 再読み込み後も password_set は True
        assert data.get("password_set") is True
        # しかし平文自体は含まない
        assert "session_password" not in data
