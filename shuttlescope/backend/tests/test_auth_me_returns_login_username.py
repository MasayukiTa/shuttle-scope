"""/api/auth/me はログイン ID (username) を返す。

設定画面のアカウント欄は /auth/me の username を「ログインID」として表示する。
以前は応答に username が無く、画面は常に「-」だった。表示名とログイン ID は
別の値なので、display_name とは別のキーで返す。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import Player, User
from backend.main import app
from backend.routers.auth import _hash_password
from backend.utils.jwt_utils import create_access_token


def test_me_returns_username_separately_from_display_name(db_session):
    p = Player(name="ログイン確認")
    db_session.add(p)
    db_session.flush()
    u = User(username="login_id_check", role="player", display_name="表示名とは別",
             hashed_credential=_hash_password("pw"), player_id=p.id,
             consent_required=False)
    db_session.add(u)
    db_session.commit()

    token = create_access_token(user_id=u.id, role="player", player_id=p.id)
    headers = {"Authorization": f"Bearer {token}"}

    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = TestClient(app, raise_server_exceptions=False)
        me = client.get("/api/auth/me", headers=headers)
        assert me.status_code == 200, me.text
        body = me.json()
        assert body["username"] == "login_id_check"
        assert body["display_name"] == "表示名とは別"
    finally:
        app.dependency_overrides.clear()
