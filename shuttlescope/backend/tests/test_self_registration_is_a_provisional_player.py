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
import json

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import AccessLog, Player, User
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
    def test_register_persists_admin_notification_failure_for_pending_admin_ui(
        self, db_session, monkeypatch,
    ):
        import backend.routers.auth_email as auth_email

        admin = User(
            username="notify_admin",
            role="admin",
            display_name="Notify Admin",
            hashed_credential=_hash_password("pw"),
            awaiting_admin_approval=False,
            consent_required=False,
        )
        db_session.add(admin)
        db_session.commit()

        monkeypatch.setattr(auth_email, "_notify_admin_webhook", lambda _content: "failed")
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = _register(client, "notify_failed_user", monkeypatch)
            assert resp.status_code == 201, resp.text
            uid = resp.json()["data"]["user_id"]

            token = create_access_token(user_id=admin.id, role="admin")
            pending = client.get(
                "/api/auth/users/pending",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert pending.status_code == 200, pending.text
        finally:
            app.dependency_overrides.clear()

        audit = (
            db_session.query(AccessLog)
            .filter(AccessLog.action == "register", AccessLog.user_id == uid)
            .order_by(AccessLog.id.desc())
            .first()
        )
        assert audit is not None
        detail = json.loads(audit.details or "{}")
        assert detail["admin_notify_status"] == "failed"

        row = next(item for item in pending.json()["data"] if item["id"] == uid)
        assert row["admin_notify_status"] == "failed"
        assert row["admin_notify_at"]

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
    """承認と拒否は登録とは**別のリクエスト**なので、`users.player_id` は
    既に DB に入っている。セッションは autoflush=False なので、ここで
    commit しないと「まだ書かれていない」状態を試すことになり、
    `users` 自身の外部キーを数え落とす欠陥を見逃す (本番で実際に起きた)。"""

    def test_deletes_a_player_nothing_points_at(self, db_session):
        u = User(username="became_coach", role="player", display_name="C",
                 hashed_credential=_hash_password("pw"))
        db_session.add(u)
        db_session.flush()
        pid = ensure_player_record(db_session, u)
        db_session.commit()
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
        db_session.commit()
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


class TestAdminNotificationDeliveryStatus:
    def test_unconfigured_webhook_is_explicit(self, monkeypatch):
        import backend.routers.auth_email as auth_email

        monkeypatch.delenv("SS_ADMIN_NOTIFY_WEBHOOK_URL", raising=False)
        assert auth_email._notify_admin_webhook("test") == "unconfigured"

    def test_non_https_webhook_is_explicit(self, monkeypatch):
        import backend.routers.auth_email as auth_email

        monkeypatch.setenv("SS_ADMIN_NOTIFY_WEBHOOK_URL", "http://127.0.0.1/hook")
        assert auth_email._notify_admin_webhook("test") == "invalid_url"


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_admin(db_session, username: str) -> User:
    admin = User(username=username, role="admin", display_name=username,
                 hashed_credential=_hash_password("pw"),
                 awaiting_admin_approval=False, consent_required=False)
    db_session.add(admin)
    db_session.commit()
    return admin


class TestPendingRegistrantIsNotACandidate:
    """承認前の登録者の Player は、選手の選択肢 (/players・予測の候補) に出ない。

    承認 (player ロールのまま) で正常な状態に戻り、候補に現れる。
    """

    def _register_pending(self, db_session, monkeypatch, username: str) -> tuple[int, int]:
        app.dependency_overrides[get_db] = lambda: db_session
        client = TestClient(app, raise_server_exceptions=False)
        resp = _register(client, username, monkeypatch)
        assert resp.status_code == 201, resp.text
        uid = resp.json()["data"]["user_id"]
        db_session.expire_all()
        return uid, db_session.get(User, uid).player_id

    def test_registration_marks_the_player_like_a_quick_start_provisional(
        self, db_session, monkeypatch,
    ):
        try:
            _uid, pid = self._register_pending(db_session, monkeypatch, "mark_prov")
        finally:
            app.dependency_overrides.clear()
        player = db_session.get(Player, pid)
        assert player.profile_status == "provisional"
        assert player.needs_review is True

    def test_other_roles_are_listed_without_the_pending_player(
        self, db_session, monkeypatch,
    ):
        from backend.db.models import Team

        team = Team(name="候補チーム")
        db_session.add(team)
        db_session.flush()
        real = Player(name="既存の選手", team_id=team.id)
        db_session.add(real)
        analyst = User(username="cand_analyst", role="analyst", display_name="A",
                       hashed_credential=_hash_password("pw"), team_id=team.id,
                       team_name=team.name, awaiting_admin_approval=False,
                       consent_required=False)
        db_session.add(analyst)
        admin = _make_admin(db_session, "cand_admin")
        try:
            _uid, pid = self._register_pending(db_session, monkeypatch, "hidden_one")
            # 同じチームの候補に混ざりうる状況にしておく (二重の防御の確認)
            db_session.get(Player, pid).team_id = team.id
            db_session.commit()

            client = TestClient(app, raise_server_exceptions=False)
            a_tok = create_access_token(user_id=analyst.id, role="analyst",
                                        team_name=team.name, team_id=team.id)
            adm_tok = create_access_token(user_id=admin.id, role="admin")

            for tok in (a_tok, adm_tok):
                r = client.get("/api/players", headers=_bearer(tok))
                assert r.status_code == 200, r.text
                ids = {p["id"] for p in r.json()["data"]}
                assert real.id in ids
                assert pid not in ids

            # 予測の候補の元 (ペア候補) からも外れる
            anchor = real.id
            rk = client.get(f"/api/prediction/pair_ranking?anchor_player_id={anchor}",
                            headers=_bearer(adm_tok))
            assert rk.status_code == 200, rk.text
            cand = {x["partner_id"] for x in rk.json()["data"]["ranked_partners"]}
            assert pid not in cand
        finally:
            app.dependency_overrides.clear()

    def test_the_registrant_still_sees_their_own_player(self, db_session, monkeypatch):
        try:
            uid, pid = self._register_pending(db_session, monkeypatch, "sees_self")
            client = TestClient(app, raise_server_exceptions=False)
            tok = create_access_token(user_id=uid, role="player", player_id=pid)
            r = client.get("/api/players", headers=_bearer(tok))
            assert r.status_code == 200, r.text
            assert [p["id"] for p in r.json()["data"]] == [pid]
        finally:
            app.dependency_overrides.clear()

    def test_approval_as_player_makes_the_player_a_normal_candidate(
        self, db_session, monkeypatch,
    ):
        admin = _make_admin(db_session, "approve_admin")
        try:
            uid, pid = self._register_pending(db_session, monkeypatch, "to_approve")
            client = TestClient(app, raise_server_exceptions=False)
            adm_tok = create_access_token(user_id=admin.id, role="admin")
            r = client.post(f"/api/auth/users/{uid}/approve",
                            json={"role": "player", "team_name": "承認先チーム"},
                            headers=_bearer(adm_tok))
            assert r.status_code == 200, r.text
            db_session.expire_all()
            player = db_session.get(Player, pid)
            assert player.profile_status == "verified"
            assert player.needs_review is False
            assert db_session.get(User, uid).player_id == pid

            lst = client.get("/api/players", headers=_bearer(adm_tok))
            assert pid in {p["id"] for p in lst.json()["data"]}
        finally:
            app.dependency_overrides.clear()

    def test_confirm_leaves_a_quick_start_provisional_player_alone(self, db_session):
        from backend.routers.auth import confirm_provisional_player

        opp = Player(name="クイックスタート相手", profile_status="provisional",
                     needs_review=True, created_via_quick_start=True)
        db_session.add(opp)
        db_session.flush()
        u = User(username="odd_link", role="player", display_name="O",
                 hashed_credential=_hash_password("pw"), player_id=opp.id)
        db_session.add(u)
        db_session.flush()
        confirm_provisional_player(db_session, u)
        assert opp.profile_status == "provisional"
        assert opp.needs_review is True

    def test_rejection_still_removes_the_player(self, db_session, monkeypatch):
        admin = _make_admin(db_session, "reject_admin")
        try:
            uid, pid = self._register_pending(db_session, monkeypatch, "to_reject")
            client = TestClient(app, raise_server_exceptions=False)
            adm_tok = create_access_token(user_id=admin.id, role="admin")
            r = client.post(f"/api/auth/users/{uid}/reject", headers=_bearer(adm_tok))
            assert r.status_code == 200, r.text
            db_session.expire_all()
            assert db_session.get(Player, pid) is None
        finally:
            app.dependency_overrides.clear()

    def test_ensure_player_record_for_an_approved_user_is_not_provisional(self, db_session):
        u = User(username="direct_player", role="player", display_name="D",
                 hashed_credential=_hash_password("pw"),
                 awaiting_admin_approval=False)
        db_session.add(u)
        db_session.flush()
        pid = ensure_player_record(db_session, u)
        player = db_session.get(Player, pid)
        assert player.profile_status == "verified"
        assert player.needs_review is False
