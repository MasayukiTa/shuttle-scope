"""公開登録は「player の仮登録」であって、行き止まりではない (2026-09-23)。

これまでの挙動:
  - `POST /api/auth/register` は role="player" / awaiting_admin_approval=True の
    user を作るが **player_id を付けない**。
  - `PlayerAccessControlMiddleware` は player_id を持たない player トークンを
    全 /api/ で 401 にする。
  - `GlobalAuthMiddleware` は承認待ちユーザを /api/auth/(me|logout|
    email/resend_verification) 以外で 403 にする。

つまり登録してもログイン後に何も開けず、admin が承認しても player_id は
付かないままなので **承認後も全 API が 401** だった。

ここで固定する仕様:
  1. player ロールの user を作る経路は必ず Player を 1 行作って紐付ける
  2. 承認待ちでも player として通る (実データが見えないのは player スコープの
     担保であって、承認フラグの担保ではない)
  3. 承認待ちで player 以外のロールを持つ状態は従来どおり閉じる (fail-closed)
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import Player, User
from backend.main import app, _pending_approval_allows
from backend.routers.auth import (
    _hash_password,
    ensure_player_record,
    release_provisional_player,
)
from backend.utils.jwt_utils import create_access_token


def _register(client, username: str, monkeypatch) -> dict:
    monkeypatch.setenv("SS_REGISTRATION_ENABLED", "1")
    from backend.config import settings
    monkeypatch.setattr(settings, "ss_registration_enabled", 1, raising=False)
    return client.post("/api/auth/register", json={
        "username": username,
        "email": f"{username}@example.com",
        "password": "Str0ng-Passw0rd-Here",
        "display_name": "仮登録の人",
        "turnstile_token": None,
    })


class TestRegisterCreatesAPlayer:
    def test_register_links_a_player_record(self, db_session, monkeypatch):
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = _register(client, "provisional_one", monkeypatch)
            assert resp.status_code == 201, resp.text
            uid = resp.json()["data"]["user_id"]
        finally:
            app.dependency_overrides.clear()

        user = db_session.get(User, uid)
        assert user is not None
        assert user.role == "player"
        assert user.awaiting_admin_approval is True
        # これが本題: player_id が付いていないと以後 401 しか返らない
        assert user.player_id is not None
        player = db_session.get(Player, user.player_id)
        assert player is not None
        assert player.name == "仮登録の人"
        # 所属は承認時に決まるので、この時点では無所属
        assert player.team_id is None


class TestEnsurePlayerRecord:
    def test_is_a_no_op_for_non_player_roles(self, db_session):
        u = User(username="an_analyst", role="analyst", display_name="A",
                 hashed_credential=_hash_password("pw"))
        db_session.add(u)
        db_session.flush()
        assert ensure_player_record(db_session, u) is None
        assert u.player_id is None

    def test_does_not_steal_an_existing_link(self, db_session):
        p = Player(name="既存選手")
        db_session.add(p)
        db_session.flush()
        u = User(username="linked_player", role="player", display_name="L",
                 hashed_credential=_hash_password("pw"), player_id=p.id)
        db_session.add(u)
        db_session.flush()
        assert ensure_player_record(db_session, u) == p.id
        assert db_session.query(Player).count() == 1

    def test_falls_back_to_the_username_when_there_is_no_display_name(self, db_session):
        u = User(username="no_display", role="player", display_name=None,
                 hashed_credential=_hash_password("pw"))
        db_session.add(u)
        db_session.flush()
        pid = ensure_player_record(db_session, u)
        assert db_session.get(Player, pid).name == "no_display"


class TestReleaseProvisionalPlayer:
    def test_deletes_a_player_nothing_points_at(self, db_session):
        u = User(username="became_coach", role="player", display_name="C",
                 hashed_credential=_hash_password("pw"))
        db_session.add(u)
        db_session.flush()
        pid = ensure_player_record(db_session, u)
        u.role = "coach"
        release_provisional_player(db_session, u)
        assert u.player_id is None
        assert db_session.get(Player, pid) is None

    def test_keeps_a_player_that_is_referenced(self, db_session):
        from backend.db.models import Match

        u = User(username="real_player", role="player", display_name="R",
                 hashed_credential=_hash_password("pw"))
        db_session.add(u)
        db_session.flush()
        pid = ensure_player_record(db_session, u)
        other = Player(name="相手")
        db_session.add(other)
        db_session.flush()
        db_session.add(Match(tournament="テスト大会", tournament_level="practice",
                             round="R1", date=date(2026, 9, 23), venue="体育館",
                             format="singles", result="win", final_score="21-10",
                             player_a_id=pid, player_b_id=other.id))
        db_session.flush()

        release_provisional_player(db_session, u)
        # 実体のある選手なので行も紐付けも残す
        assert db_session.get(Player, pid) is not None
        assert u.player_id == pid


class TestPendingApprovalPolicy:
    """`_pending_approval_allows` が承認待ちの可否を決める唯一の場所。"""

    @pytest.mark.parametrize("path", [
        "/api/auth/me",
        "/api/matches",
        "/api/analysis/heatmap",
        "/api/players/1",
    ])
    def test_a_pending_player_is_let_through(self, path):
        assert _pending_approval_allows("player", path) is True

    @pytest.mark.parametrize("path", [
        "/api/auth/me",
        "/api/auth/logout",
        "/api/auth/email/resend_verification",
    ])
    def test_a_pending_non_player_keeps_the_old_narrow_allowlist(self, path):
        assert _pending_approval_allows("analyst", path) is True

    @pytest.mark.parametrize("role", ["analyst", "coach", "admin", "llm", ""])
    @pytest.mark.parametrize("path", [
        "/api/matches",
        "/api/players",
        "/api/auth/users",
        "/api/auth/mel",          # 許可パターンの部分一致で開かないこと
        "/api/auth/me/extra",
    ])
    def test_a_pending_non_player_is_still_blocked(self, role, path):
        assert _pending_approval_allows(role, path) is False


class TestAPendingPlayerCanActuallyUseTheApi:
    def test_auth_me_and_a_player_scoped_read_both_work(self, db_session):
        p = Player(name="仮登録の人")
        db_session.add(p)
        db_session.flush()
        u = User(username="pending_usable", role="player", display_name="仮登録の人",
                 hashed_credential=_hash_password("pw"), player_id=p.id,
                 awaiting_admin_approval=True, consent_required=False)
        db_session.add(u)
        db_session.commit()

        token = create_access_token(user_id=u.id, role="player", player_id=p.id)
        headers = {"Authorization": f"Bearer {token}"}

        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            me = client.get("/api/auth/me", headers=headers)
            assert me.status_code == 200, me.text
            assert me.json()["awaiting_admin_approval"] is True

            # 承認待ちを理由にした 403 は返らない。自分の選手なので 200。
            own = client.get(f"/api/players/{p.id}", headers=headers)
            assert own.status_code != 403, own.text

            # 他人の選手は従来どおり閉じている (承認とは無関係に player スコープ)
            other = Player(name="他人")
            db_session.add(other)
            db_session.commit()
            resp = client.get(f"/api/players/{other.id}", headers=headers)
            assert resp.status_code in (403, 404), resp.text
        finally:
            app.dependency_overrides.clear()
