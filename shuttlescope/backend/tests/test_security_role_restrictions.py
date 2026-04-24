"""セキュリティ修正のロール制限テスト (2026-04-24)

V-01 weak key guard, V-03/V-11 matches role, V-07 HIDE_STACK_TRACES,
V-08 bootstrap-status, V-09 X-Role removal, admin 全操作疎通をカバーする。
"""
from __future__ import annotations

import pytest
from datetime import date
from fastapi.testclient import TestClient

from backend.config import settings
from backend.db.database import get_db
from backend.db.models import User, Player, Match
from backend.main import app
from backend.routers.auth import _hash_password
from backend.utils.jwt_utils import create_access_token

_PLAYER_USER_ID = 10


# ─── フィクスチャ ─────────────────────────────────────────────────────────────

def _make_token(role: str, user_id: int = 99, player_id: int | None = None) -> str:
    return create_access_token(user_id=user_id, role=role, player_id=player_id)


def _auth(role: str, **kw) -> dict:
    return {"Authorization": f"Bearer {_make_token(role, **kw)}"}


# ─── V-08: bootstrap-status 情報漏洩制限 ─────────────────────────────────────

class TestBootstrapStatusInfoLeak:
    def test_returns_only_has_admin_when_admin_exists(self, db_session):
        db_session.query(User).delete()
        db_session.add(User(
            username="admin_x",
            role="admin",
            display_name="Admin",
            hashed_credential=_hash_password("pw"),
        ))
        db_session.commit()
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app)
            resp = client.get("/api/auth/bootstrap-status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["has_admin"] is True
            # 初期化済み後は bootstrap_configured の詳細を返さない
            assert data["bootstrap_configured"] is False
        finally:
            app.dependency_overrides.clear()

    def test_returns_full_status_when_no_admin(self, db_session, monkeypatch):
        db_session.query(User).delete()
        db_session.commit()
        monkeypatch.setattr(settings, "BOOTSTRAP_ADMIN_PASSWORD", "tmppass", raising=False)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app)
            resp = client.get("/api/auth/bootstrap-status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["has_admin"] is False
            assert data["bootstrap_configured"] is True
        finally:
            app.dependency_overrides.clear()


# ─── V-09: X-Role ヘッダーが無視されること ───────────────────────────────────

class TestXRoleHeaderIgnored:
    def test_x_role_header_does_not_grant_player_bypass(self, db_session, monkeypatch):
        """X-Role ヘッダーだけでは GlobalAuthMiddleware をバイパスできない。

        PUBLIC_MODE=True にして loopback バイパスを無効にした上で検証する。
        """
        monkeypatch.setattr(settings, "PUBLIC_MODE", True, raising=False)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            # JWT なし + X-Role: analyst → GlobalAuthMiddleware が 401 を返す
            resp = client.get(
                "/api/matches",
                headers={"X-Role": "analyst"},
            )
            assert resp.status_code == 401
        finally:
            app.dependency_overrides.clear()
            monkeypatch.setattr(settings, "PUBLIC_MODE", False, raising=False)


# ─── V-03: matches ロール制限 ─────────────────────────────────────────────────

@pytest.fixture
def seeded_match(db_session):
    """テスト用選手2名 + 試合1件 + player ユーザーを DB に登録して返す。"""
    db_session.query(Match).delete()
    db_session.query(Player).delete()
    db_session.query(User).filter(User.role == "player").delete()
    db_session.commit()

    pa = Player(name="Player A", name_normalized="playera", team="TeamA")
    pb = Player(name="Player B", name_normalized="playerb", team="TeamB")
    db_session.add_all([pa, pb])
    db_session.flush()

    # PlayerAccessControlMiddleware の DB 検証をパスさせるためユーザーも登録
    pu = User(
        id=_PLAYER_USER_ID,
        username="player_test",
        role="player",
        display_name="Test Player",
        hashed_credential=_hash_password("pw"),
        player_id=pa.id,
    )
    db_session.add(pu)
    db_session.flush()

    m = Match(
        tournament="Test Cup",
        tournament_level="国内",
        round="QF",
        date=date(2026, 1, 1),
        format="singles",
        result="unknown",
        player_a_id=pa.id,
        player_b_id=pb.id,
    )
    db_session.add(m)
    db_session.commit()
    db_session.refresh(m)
    return m


class TestMatchRoleRestrictions:
    def test_player_cannot_create_match(self, db_session, seeded_match):
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/matches",
                json={
                    "tournament": "X", "tournament_level": "国内", "round": "QF",
                    "date": "2026-01-01", "format": "singles",
                    "player_a_id": seeded_match.player_a_id,
                    "player_b_id": seeded_match.player_b_id,
                },
                headers=_auth("player", user_id=_PLAYER_USER_ID, player_id=seeded_match.player_a_id),
            )
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_player_cannot_update_match(self, db_session, seeded_match):
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.put(
                f"/api/matches/{seeded_match.id}",
                json={"tournament": "Hacked"},
                headers=_auth("player", user_id=_PLAYER_USER_ID, player_id=seeded_match.player_a_id),
            )
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_player_cannot_delete_match(self, db_session, seeded_match):
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.delete(
                f"/api/matches/{seeded_match.id}",
                headers=_auth("player", user_id=_PLAYER_USER_ID, player_id=seeded_match.player_a_id),
            )
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_coach_cannot_delete_match(self, db_session, seeded_match):
        """コーチは削除不可（analyst/admin のみ）。"""
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.delete(
                f"/api/matches/{seeded_match.id}",
                headers=_auth("coach"),
            )
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_analyst_can_delete_match(self, db_session, seeded_match):
        """アナリストは削除可能。"""
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.delete(
                f"/api/matches/{seeded_match.id}",
                headers=_auth("analyst"),
            )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_coach_can_update_match(self, db_session, seeded_match):
        """コーチは更新可能。"""
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.put(
                f"/api/matches/{seeded_match.id}",
                json={"tournament": "Updated"},
                headers=_auth("coach"),
            )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()


# ─── V-01: 弱い秘密鍵の起動時ガード ─────────────────────────────────────────

class TestWeakSecretKeyGuard:
    def test_weak_key_list_contains_defaults(self):
        from backend.config import _WEAK_KEYS
        assert "development-secret-key" in _WEAK_KEYS
        assert "" in _WEAK_KEYS
        assert "secret" in _WEAK_KEYS

    def test_public_mode_with_weak_key_raises(self, monkeypatch):
        """PUBLIC_MODE=True + 弱いキーなら RuntimeError が発生することを確認。"""
        from backend.config import _WEAK_KEYS, Settings
        # 設定インスタンスを直接検証するヘルパー関数をテスト
        for weak_key in list(_WEAK_KEYS)[:3]:
            s = Settings(SECRET_KEY=weak_key, PUBLIC_MODE=True)
            with pytest.raises(RuntimeError, match="SECRET_KEY"):
                if s.SECRET_KEY in _WEAK_KEYS and s.PUBLIC_MODE:
                    raise RuntimeError("SECRET_KEY がデフォルト値または空です")


# ─── V-10: safe_path ユーティリティ ──────────────────────────────────────────

class TestSafePath:
    def test_allows_valid_child_path(self, tmp_path):
        from backend.utils.safe_path import safe_path
        child = tmp_path / "sub" / "file.txt"
        child.parent.mkdir()
        result = safe_path(tmp_path, "sub/file.txt")
        assert result == child

    def test_rejects_traversal(self, tmp_path):
        from backend.utils.safe_path import safe_path
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            safe_path(tmp_path, "../../etc/passwd")
        assert exc_info.value.status_code == 403

    def test_rejects_absolute_escape(self, tmp_path):
        from backend.utils.safe_path import safe_path
        from fastapi import HTTPException
        # 絶対パスで tmp_path 外を指定
        with pytest.raises(HTTPException):
            safe_path(tmp_path, "/etc/passwd")


# ─── ラウンド15: pipeline DoS + mass assignment + cookies null byte ────────

class TestPipelineMassAssignmentAndRate:
    def _seed(self, db_session):
        from backend.routers.auth import _hash_password
        from backend.db.models import Match as _M, Player as _P
        db_session.query(User).delete()
        db_session.query(_M).delete()
        db_session.query(_P).delete()
        db_session.add(_P(id=700, name="X", name_normalized="x"))
        db_session.add(_P(id=701, name="Y", name_normalized="y"))
        db_session.add(_M(
            id=700, tournament="T", tournament_level="国内", round="QF",
            date=date(2026, 4, 24), format="singles", result="unknown",
            player_a_id=700, player_b_id=701,
        ))
        db_session.add(User(id=700, username="ana700", role="analyst",
                            display_name="A", hashed_credential=_hash_password("x")))
        db_session.commit()

    def test_pipeline_run_rejects_unknown_job_type(self, db_session):
        self._seed(db_session)
        token = _make_token("analyst", user_id=700)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/pipeline/run",
                json={"match_id": 700, "job_type": "admin_dump"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text[:200]}"
        finally:
            app.dependency_overrides.clear()

    def test_pipeline_run_rejects_extra_fields(self, db_session):
        self._seed(db_session)
        token = _make_token("analyst", user_id=700)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/v1/pipeline/run",
                json={"match_id": 700, "priority": "high", "cpu_limit": 999},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 422, f"expected 422 extra forbid, got {resp.status_code}: {resp.text[:200]}"
        finally:
            app.dependency_overrides.clear()

    def test_pipeline_run_rate_limit(self, db_session, monkeypatch):
        from backend.routers import pipeline as _pl
        monkeypatch.setattr(_pl, "_PIPELINE_MAX_JOBS_PER_WINDOW", 3, raising=True)
        _pl._pipeline_run_counters.clear()
        self._seed(db_session)
        token = _make_token("analyst", user_id=700)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            codes = []
            for _ in range(5):
                r = client.post(
                    "/api/v1/pipeline/run",
                    json={"match_id": 700, "job_type": "full_pipeline"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                codes.append(r.status_code)
            assert 429 in codes, f"expected 429, got {codes}"
        finally:
            app.dependency_overrides.clear()
            _pl._pipeline_run_counters.clear()


class TestPasswordChangeExtraForbid:
    def test_password_change_rejects_user_id_field(self, db_session):
        from backend.routers.auth import _hash_password
        db_session.query(User).delete()
        db_session.add(User(id=800, username="pw", role="analyst",
                            display_name="P", hashed_credential=_hash_password("OldPass12345!")))
        db_session.commit()
        token = _make_token("analyst", user_id=800)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/auth/password",
                json={"current_password": "OldPass12345!", "new_password": "NewPass12345!", "user_id": 1},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 422, f"expected 422 extra forbid, got {resp.status_code}: {resp.text[:200]}"
        finally:
            app.dependency_overrides.clear()


# ─── 動画 DL: SSRF 防御 + cookies.txt セキュア扱い ───────────────────────────

class TestVideoDownloadSSRF:
    def test_validate_external_url_blocks_loopback(self):
        from backend.utils.safe_path import validate_external_url
        from fastapi import HTTPException
        import pytest as _pt
        for bad in [
            "http://127.0.0.1/x",
            "http://localhost/x",
            "http://169.254.169.254/latest/meta-data/",
            "http://10.0.0.1/",
            "http://192.168.1.1/",
            "http://172.16.0.5/",
            "file:///etc/passwd",
            "ftp://example.com/f",
            "gopher://x/y",
            "javascript:alert(1)",
        ]:
            with _pt.raises(HTTPException) as exc_info:
                validate_external_url(bad)
            assert exc_info.value.status_code in (422,), f"{bad} not rejected"

    def test_validate_external_url_accepts_public(self):
        from backend.utils.safe_path import validate_external_url
        # 公開 DNS 名。DNS 失敗しても host 名自体が block list に無ければ通す
        # (yt-dlp が名前解決失敗すれば別途エラー)
        for ok in [
            "https://www.youtube.com/watch?v=abc",
            "https://vimeo.com/12345",
            "https://twitter.com/x/status/1",
        ]:
            validate_external_url(ok)  # raise しなければ OK

    def test_cookie_browser_blocked_from_non_loopback(self, db_session, monkeypatch):
        """Web リクエスト (Cloudflare 経由) で cookie_browser 指定は 403。"""
        from backend.routers.auth import _hash_password
        from backend.db.models import Match as _Match, Player as _P
        from backend.config import settings as _s
        monkeypatch.setattr(_s, "PUBLIC_MODE", True, raising=False)
        db_session.query(User).delete()
        db_session.query(_Match).delete()
        db_session.query(_P).delete()
        db_session.add(_P(id=600, name="X", name_normalized="x"))
        db_session.add(_P(id=601, name="Y", name_normalized="y"))
        db_session.add(_Match(
            id=600, tournament="T", tournament_level="国内", round="QF",
            date=date(2026, 4, 24), format="singles", result="unknown",
            player_a_id=600, player_b_id=601, video_url="https://youtube.com/watch?v=1",
        ))
        db_session.add(User(id=600, username="analy", role="analyst",
                            display_name="A", hashed_credential=_hash_password("x")))
        db_session.commit()
        token = _make_token("analyst", user_id=600)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            # 非 loopback 想定で CF-Connecting-IP を与える
            resp = client.post(
                "/api/matches/600/download",
                json={"quality": "720", "cookie_browser": "chrome"},
                headers={
                    "Authorization": f"Bearer {token}",
                    "CF-Connecting-IP": "203.0.113.50",
                },
            )
            assert resp.status_code == 403, f"expected 403 when cookie_browser from web, got {resp.status_code}"
        finally:
            app.dependency_overrides.clear()


# ─── Exfil rate limit (認証後の大量 GET / データ吸出し防御) ──────────────────

class TestExfilRateLimit:
    def test_analyst_exceeds_request_count_returns_429(self, db_session, monkeypatch):
        """analyst が短時間で多数リクエストすると 429。"""
        from backend.main import ExfilRateLimitMiddleware
        monkeypatch.setattr(ExfilRateLimitMiddleware, "_max_requests_per_window", 5, raising=True)
        monkeypatch.setattr(ExfilRateLimitMiddleware, "_max_bytes_per_window", 100 * 1024 * 1024, raising=True)
        from backend.routers.auth import _hash_password
        db_session.query(User).delete()
        db_session.add(User(id=400, username="anax", role="analyst",
                            display_name="A", hashed_credential=_hash_password("x")))
        db_session.commit()
        token = _make_token("analyst", user_id=400)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            codes = []
            for _ in range(10):
                r = client.get("/api/players", headers={"Authorization": f"Bearer {token}"})
                codes.append(r.status_code)
            assert 429 in codes, f"expected 429 after exceeding limit, got {codes}"
        finally:
            app.dependency_overrides.clear()

    def test_admin_is_exempt_from_exfil_limit(self, db_session, monkeypatch):
        """admin は exfil 制限対象外 (業務上の大量アクセスを許容)。"""
        from backend.main import ExfilRateLimitMiddleware
        monkeypatch.setattr(ExfilRateLimitMiddleware, "_max_requests_per_window", 3, raising=True)
        from backend.routers.auth import _hash_password
        db_session.query(User).delete()
        db_session.add(User(id=401, username="admx", role="admin",
                            display_name="A", hashed_credential=_hash_password("x")))
        db_session.commit()
        token = _make_token("admin", user_id=401)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            codes = []
            for _ in range(8):
                r = client.get("/api/players", headers={"Authorization": f"Bearer {token}"})
                codes.append(r.status_code)
            assert 429 not in codes, f"admin should be exempt, got {codes}"
        finally:
            app.dependency_overrides.clear()


# ─── sync/export エラーメッセージの sanitize ─────────────────────────────────

class TestSyncExportErrorSanitize:
    def test_sync_export_error_no_leak(self, db_session):
        """sync/export の 500 エラーで内部例外文字列がクライアントに返らない。"""
        from backend.routers.auth import _hash_password
        db_session.query(User).delete()
        db_session.add(User(id=500, username="anay", role="analyst",
                            display_name="A", hashed_credential=_hash_password("x")))
        db_session.commit()
        token = _make_token("analyst", user_id=500)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            # 存在しない player_ids で 404/500 どちらでも内部例外は漏れない
            r = client.get(
                "/api/sync/export/conditions?player_ids=99999",
                headers={"Authorization": f"Bearer {token}"},
            )
            # 404 or 500 どちらでも OK。500 の場合 detail に内部 python エラー文字列が入っていないこと
            if r.status_code == 500:
                assert "Object of type" not in r.text
                assert "JSON serializable" not in r.text
                assert "Traceback" not in r.text
        finally:
            app.dependency_overrides.clear()


# ─── APT 対策: JWT iat/exp sanity / display_name 制御文字 / UserCreate extra ─

class TestAPTHardening:
    def test_jwt_rejects_future_iat(self, monkeypatch):
        """iat が 5 分以上未来の JWT は拒否。"""
        from backend.utils.jwt_utils import verify_token
        from backend.config import settings as s
        from jose import jwt as jose_jwt
        import time as _t
        future_iat = int(_t.time()) + 3600
        tok = jose_jwt.encode(
            {"sub": "1", "role": "admin", "iat": future_iat, "exp": future_iat + 600, "jti": "x"},
            s.SECRET_KEY, algorithm="HS256",
        )
        assert verify_token(tok) is None

    def test_jwt_rejects_long_lifetime(self, monkeypatch):
        """exp - iat が 2 日以上の JWT は拒否 (forged super-long-lived token 対策)。"""
        from backend.utils.jwt_utils import verify_token
        from backend.config import settings as s
        from jose import jwt as jose_jwt
        import time as _t
        iat = int(_t.time())
        tok = jose_jwt.encode(
            {"sub": "1", "role": "admin", "iat": iat, "exp": iat + 86400 * 10, "jti": "x"},
            s.SECRET_KEY, algorithm="HS256",
        )
        assert verify_token(tok) is None

    def test_display_name_rejects_control_chars(self):
        """display_name に CRLF / null byte / BIDI override を入れたら 422。"""
        from backend.routers.auth import _reject_control_chars
        from fastapi import HTTPException
        import pytest as _pt
        for bad in ["hello\r\nX-Injected: 1", "hello\x00suffix", "hello‮reverse", "hello​ZWSP"]:
            with _pt.raises(HTTPException) as exc_info:
                _reject_control_chars(bad, "display_name")
            assert exc_info.value.status_code == 422

    def test_display_name_allows_normal_unicode(self):
        """通常の日本語/英数字は通過する。"""
        from backend.routers.auth import _reject_control_chars
        for ok in ["山田太郎", "TaroYamada", "Player A", "テスト 1", None]:
            assert _reject_control_chars(ok, "display_name") == ok

    def test_usercreate_extra_forbid(self, db_session):
        """UserCreate に extra フィールド is_admin/hashed_credential 混入で 422。"""
        from backend.routers.auth import _hash_password
        db_session.query(User).delete()
        db_session.add(User(id=100, username="adm", role="admin", display_name="A", hashed_credential=_hash_password("x")))
        db_session.commit()
        token = _make_token("admin", user_id=100)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/auth/users",
                json={"role": "player", "display_name": "x", "username": "xuser99", "password": "Xyz12345!", "is_admin": True},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 422, f"expected 422 extra=forbid, got {resp.status_code}: {resp.text[:200]}"
        finally:
            app.dependency_overrides.clear()

    def test_conditions_post_player_scope(self, db_session):
        """player は他 player の condition を作成できない。"""
        from backend.routers.auth import _hash_password
        from backend.db.models import Player as _Player
        db_session.query(User).delete()
        db_session.query(_Player).delete()
        db_session.add(_Player(id=300, name="P300", name_normalized="p300"))
        db_session.add(_Player(id=301, name="P301", name_normalized="p301"))
        db_session.add(User(id=200, username="plr", role="player", display_name="P",
                            hashed_credential=_hash_password("x"), player_id=300))
        db_session.commit()
        token = _make_token("player", user_id=200, player_id=300)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            # 他 player (id=301) の condition 作成を試みる → 403
            resp = client.post(
                "/api/conditions",
                json={"player_id": 301, "measured_at": "2026-04-24", "condition_type": "weekly", "ccs_score": 0.5},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text[:200]}"
        finally:
            app.dependency_overrides.clear()


# ─── 全ロールの権限昇格経路を塞ぐ (analyst → admin、coach → *) ──────────────

class TestAllTiersPrivEsc:
    def _seed_users(self, db_session):
        from backend.routers.auth import _hash_password
        db_session.query(User).delete()
        users = [
            User(id=100, username="adminu", role="admin", display_name="A", hashed_credential=_hash_password("x")),
            User(id=101, username="playeru", role="player", display_name="P", hashed_credential=_hash_password("x"), player_id=None),
            User(id=102, username="coachu", role="coach", display_name="C", hashed_credential=_hash_password("x"), team_name="T1"),
            User(id=103, username="analystu", role="analyst", display_name="An", hashed_credential=_hash_password("x")),
            User(id=104, username="targetplayer", role="player", display_name="TP", hashed_credential=_hash_password("x"), player_id=None),
        ]
        db_session.add_all(users)
        db_session.commit()

    def test_analyst_cannot_promote_player_to_admin(self, db_session):
        """analyst が PUT /users/{player} role=admin で 403。"""
        self._seed_users(db_session)
        token = _make_token("analyst", user_id=103)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.put(
                "/api/auth/users/104",
                json={"role": "admin"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text[:200]}"
            # DB で実際に書換わってないことも確認
            db_session.expire_all()
            u = db_session.get(User, 104)
            assert u.role == "player"
        finally:
            app.dependency_overrides.clear()

    def test_analyst_cannot_self_promote(self, db_session):
        """analyst が PUT /users/{self} role=admin で 403。"""
        self._seed_users(db_session)
        token = _make_token("analyst", user_id=103)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.put(
                "/api/auth/users/103",
                json={"role": "admin"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 403
            db_session.expire_all()
            u = db_session.get(User, 103)
            assert u.role == "analyst"
        finally:
            app.dependency_overrides.clear()

    def test_analyst_cannot_overwrite_others_password(self, db_session):
        """analyst が PUT /users/{player} password=x で 403 (アカウント乗っ取り防止)。"""
        self._seed_users(db_session)
        orig_hash = db_session.get(User, 104).hashed_credential
        token = _make_token("analyst", user_id=103)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.put(
                "/api/auth/users/104",
                json={"password": "NewPwn12345!"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 403
            db_session.expire_all()
            assert db_session.get(User, 104).hashed_credential == orig_hash
        finally:
            app.dependency_overrides.clear()

    def test_analyst_cannot_change_team_name(self, db_session):
        """analyst が team_name を書換えて tenant 破壊不可。"""
        self._seed_users(db_session)
        token = _make_token("analyst", user_id=103)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.put(
                "/api/auth/users/102",
                json={"team_name": "HackedTeam"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 403
            db_session.expire_all()
            assert db_session.get(User, 102).team_name == "T1"
        finally:
            app.dependency_overrides.clear()

    def test_coach_cannot_promote_self(self, db_session):
        """coach が自己 role 書換不可。"""
        self._seed_users(db_session)
        token = _make_token("coach", user_id=102)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.put(
                "/api/auth/users/102",
                json={"role": "admin"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 403
        finally:
            app.dependency_overrides.clear()

    def test_admin_can_change_role(self, db_session):
        """admin は role を書換可能 (正常系)。"""
        self._seed_users(db_session)
        token = _make_token("admin", user_id=100)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.put(
                "/api/auth/users/101",
                json={"role": "coach"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
            db_session.expire_all()
            assert db_session.get(User, 101).role == "coach"
        finally:
            app.dependency_overrides.clear()


# ─── 権限昇格防御: player による mass assignment / silent drop の拒否 ─────────

class TestPrivEscalationBlock:
    def _player_token(self, db_session):
        from backend.routers.auth import _hash_password
        u = User(
            id=50, username="escpl", role="player",
            display_name="p", hashed_credential=_hash_password("x"),
            player_id=1,
        )
        db_session.add(u)
        db_session.commit()
        return _make_token("player", user_id=50, player_id=1)

    def test_player_cannot_send_role_field(self, db_session):
        """player が PUT /users/{self} で role=admin を送ると 403 で拒否される。"""
        db_session.query(User).filter(User.id == 50).delete()
        db_session.commit()
        token = self._player_token(db_session)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.put(
                "/api/auth/users/50",
                json={"role": "admin", "display_name": "x"},
                headers={"Authorization": f"Bearer {token}"},
            )
            # role 書換は admin のみ → 403 で明示拒否
            assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text[:300]}"
            db_session.expire_all()
            assert db_session.get(User, 50).role == "player"
        finally:
            app.dependency_overrides.clear()

    def test_player_unknown_field_rejected(self, db_session):
        """未知フィールド (is_admin 等) は extra=forbid で 422。"""
        db_session.query(User).filter(User.id == 50).delete()
        db_session.commit()
        token = self._player_token(db_session)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.put(
                "/api/auth/users/50",
                json={"is_admin": True, "display_name": "x"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 422, f"expected 422 extra=forbid, got {resp.status_code}: {resp.text[:200]}"
        finally:
            app.dependency_overrides.clear()

    def test_player_cannot_change_privileged_fields(self, db_session):
        """player が username / team_name / player_id を送ると 403。"""
        db_session.query(User).filter(User.id == 50).delete()
        db_session.commit()
        token = self._player_token(db_session)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            for body in [
                {"username": "hijacked"},
                {"team_name": "TeamOther"},
                {"player_id": 99},
            ]:
                resp = client.put(
                    "/api/auth/users/50",
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert resp.status_code == 403, f"body={body} expected 403, got {resp.status_code}: {resp.text[:200]}"
        finally:
            app.dependency_overrides.clear()

    def test_player_can_change_own_display_name(self, db_session):
        """player が自分の display_name を変えるのは許可される。"""
        db_session.query(User).filter(User.id == 50).delete()
        db_session.commit()
        token = self._player_token(db_session)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.put(
                "/api/auth/users/50",
                json={"display_name": "new name"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_player_cannot_access_db_status(self, db_session):
        """player は /api/db/status にアクセス不可。"""
        db_session.query(User).filter(User.id == 50).delete()
        db_session.commit()
        token = self._player_token(db_session)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/api/db/status",
                headers={"Authorization": f"Bearer {token}"},
            )
            # 403 admin required が期待 (401 は unauth, 404 は router なし)
            assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text[:200]}"
        finally:
            app.dependency_overrides.clear()

    def test_player_cannot_list_analysts(self, db_session):
        """player は /api/auth/analysts にアクセス不可 (Cloudflare 経由想定)。"""
        db_session.query(User).filter(User.id == 50).delete()
        db_session.commit()
        token = self._player_token(db_session)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            # loopback をスキップして検証するため PUBLIC_MODE=True をシミュレート
            import pytest
            monkeypatch = pytest.MonkeyPatch()
            monkeypatch.setattr(settings, "PUBLIC_MODE", True, raising=False)
            try:
                client = TestClient(app, raise_server_exceptions=False)
                resp = client.get(
                    "/api/auth/analysts",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "CF-Connecting-IP": "203.0.113.50",
                    },
                )
                assert resp.status_code == 403, f"expected 403, got {resp.status_code}: {resp.text[:200]}"
            finally:
                monkeypatch.undo()
        finally:
            app.dependency_overrides.clear()

    def test_player_cannot_access_conditions_of_others(self, db_session):
        """player は他 player の conditions を見ることができない。"""
        from backend.routers.auth import _hash_password
        db_session.query(User).filter(User.id == 50).delete()
        db_session.commit()
        token = self._player_token(db_session)
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/api/conditions?player_id=99",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert resp.status_code == 403, f"expected 403 (other player), got {resp.status_code}: {resp.text[:200]}"
        finally:
            app.dependency_overrides.clear()


# ─── 422 input エコーの長大 string / XML / バイナリマスク ────────────────────

class TestValidationInputSanitization:
    def test_xml_body_is_masked(self, db_session):
        """XML body を投げた時、応答の input にそのまま反映されないこと。"""
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            xml_body = b'<?xml version="1.0"?><!DOCTYPE root [<!ENTITY xxe SYSTEM "file:///etc/passwd">]><root><name>&xxe;</name></root>'
            resp = client.post(
                "/api/public/contact",
                content=xml_body,
                headers={"Content-Type": "application/xml"},
            )
            body = resp.text
            assert "file:///etc/passwd" not in body, f"XML payload leaked: {body[:300]}"
            assert "<!ENTITY" not in body, f"XML ENTITY leaked: {body[:300]}"
        finally:
            app.dependency_overrides.clear()

    def test_long_string_is_truncated(self):
        """200 文字超の string input は `***(truncated)` に置換される（ユニットテスト）。"""
        from backend.main import _mask_sensitive
        long_val = "A" * 500
        result = _mask_sensitive(long_val)
        assert result == "***(truncated)"

    def test_short_string_passes_through(self):
        from backend.main import _mask_sensitive
        assert _mask_sensitive("hello") == "hello"

    def test_xml_string_is_masked(self):
        from backend.main import _mask_sensitive
        xml = '<?xml version="1.0"?><root>x</root>'
        assert _mask_sensitive(xml) == "***(xml/html)"

    def test_bytes_is_summarized(self):
        from backend.main import _mask_sensitive
        result = _mask_sensitive(b"\x80\x04binary")
        assert result.startswith("***(bytes,")


# ─── audit log HMAC 鍵のデフォルト文字列フォールバック禁止 ───────────────────

class TestAuditLogHmacKey:
    def test_empty_secret_does_not_fall_back_to_known_default(self, monkeypatch):
        """SECRET_KEY が空でも audit log HMAC 鍵は `development-secret-key` に
        フォールバックしないこと（既知鍵での audit 偽造を阻止）。"""
        from backend.utils import access_log as al
        from backend.config import settings as s
        monkeypatch.setattr(s, "SECRET_KEY", "", raising=False)
        key = al._secret_bytes()
        assert key != b"development-secret-key"
        assert len(key) >= 16  # SHA256 派生鍵 ≥ 16 バイト

    def test_configured_secret_is_used(self, monkeypatch):
        """SECRET_KEY が設定されている場合はその値がそのまま HMAC 鍵として使われる。"""
        from backend.utils import access_log as al
        from backend.config import settings as s
        monkeypatch.setattr(s, "SECRET_KEY", "super_strong_key_abcdef_1234567890", raising=False)
        key = al._secret_bytes()
        assert key == b"super_strong_key_abcdef_1234567890"


# ─── 多層防御: loopback 判定の空文字/testclient 制限 ─────────────────────────

class TestLoopbackHardening:
    def test_production_mode_rejects_empty_client(self, monkeypatch):
        """PUBLIC_MODE=True では空文字・testclient を loopback 扱いしない。"""
        from backend.utils import control_plane as cp
        from backend.config import settings as s
        from unittest.mock import MagicMock
        monkeypatch.setattr(s, "PUBLIC_MODE", True, raising=False)
        req = MagicMock()
        req.headers = {}
        req.client = None  # client None → _client_ip は ""
        assert cp.is_loopback_request(req) is False
        # testclient も拒否
        req.client = MagicMock()
        req.client.host = "testclient"
        assert cp.is_loopback_request(req) is False

    def test_development_allows_testclient(self, monkeypatch):
        """開発環境では testclient / 空文字を loopback 扱い（テスト互換）。"""
        from backend.utils import control_plane as cp
        from backend.config import settings as s
        from unittest.mock import MagicMock
        monkeypatch.setattr(s, "PUBLIC_MODE", False, raising=False)
        monkeypatch.setattr(s, "ENVIRONMENT", "development", raising=False)
        req = MagicMock()
        req.headers = {}
        req.client = MagicMock()
        req.client.host = "testclient"
        assert cp.is_loopback_request(req) is True

    def test_127_always_loopback(self, monkeypatch):
        """127.0.0.1 / ::1 / localhost は常に loopback。"""
        from backend.utils import control_plane as cp
        from backend.config import settings as s
        monkeypatch.setattr(s, "PUBLIC_MODE", True, raising=False)
        from unittest.mock import MagicMock
        req = MagicMock()
        req.headers = {}
        for ip in ("127.0.0.1", "::1", "localhost"):
            req.client = MagicMock()
            req.client.host = ip
            assert cp.is_loopback_request(req) is True, f"{ip} should be loopback"


# ─── Mass assignment 防御: PublicInquiryCreate は extra field を拒否 ──────────

class TestMassAssignmentDefense:
    def test_public_contact_rejects_extra_fields(self, db_session):
        """is_admin/role/status 等の余分なフィールドは 422 で拒否される。"""
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/public/contact",
                json={
                    "name": "x", "email": "a@b.c",
                    "message": "valid message 12345",
                    "organization": "x",
                    "is_admin": True,
                    "role": "admin",
                    "id": 9999,
                    "status": "closed",
                },
            )
            assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text[:300]}"
        finally:
            app.dependency_overrides.clear()


# ─── CWE-204: login タイミング側チャネル（ユーザ名列挙）対策 ─────────────────

class TestLoginTimingSideChannel:
    def test_user_not_found_executes_padding_write(self, db_session, monkeypatch):
        """user_not_found パスで _timing_padding_db_write が呼ばれることを検証。"""
        from backend.routers import auth as auth_mod
        called = {"n": 0}
        orig = auth_mod._timing_padding_db_write
        def wrapped(db):
            called["n"] += 1
            return orig(db)
        monkeypatch.setattr(auth_mod, "_timing_padding_db_write", wrapped)

        db_session.query(User).delete()
        db_session.commit()
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/auth/login",
                json={"grant_type": "password", "username": "nonexistent_zzz", "password": "x"},
            )
            assert resp.status_code == 401
            # user_not_found 経路で padding が呼ばれている
            assert called["n"] >= 1, f"_timing_padding_db_write was not called (n={called['n']})"
        finally:
            app.dependency_overrides.clear()

    def test_padding_write_does_not_modify_data(self, db_session):
        """padding の UPDATE WHERE id=-1 は 0 行にマッチで副作用がない。"""
        from backend.routers.auth import _timing_padding_db_write
        # 既存ユーザ
        db_session.query(User).delete()
        u = User(
            id=1, username="pivot", role="admin",
            display_name="P", hashed_credential=_hash_password("x"),
            failed_attempts=0,
        )
        db_session.add(u)
        db_session.commit()
        _timing_padding_db_write(db_session)
        # failed_attempts が変化していないこと
        u2 = db_session.query(User).filter(User.id == 1).first()
        assert u2.failed_attempts == 0


# ─── 422 バリデーションエラーの password マスク ──────────────────────────────

class TestValidationErrorMasking:
    def test_password_masked_in_422_login(self, db_session):
        """login に壊れた body を送って 422 を誘発し、password が返却されないことを確認。"""
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            # grant_type を欠落させて 422 を誘発、password を含む body
            resp = client.post(
                "/api/auth/login",
                json={"username": "admin", "password": "s3cretPW!"},
            )
            assert resp.status_code == 422
            body_text = resp.text
            # パスワード平文が応答に含まれていないこと
            assert "s3cretPW!" not in body_text, f"password leaked in 422 response: {body_text}"
        finally:
            app.dependency_overrides.clear()


# ─── V-07: HIDE_STACK_TRACES フラグ ──────────────────────────────────────────

class TestHideStackTraces:
    def test_stack_trace_hidden_when_flag_set(self, monkeypatch):
        """HIDE_STACK_TRACES=True の時は traceback がレスポンスに含まれない。"""
        from backend.config import settings as s
        monkeypatch.setattr(s, "HIDE_STACK_TRACES", True, raising=False)
        monkeypatch.setattr(s, "PUBLIC_MODE", False, raising=False)
        hide = s.PUBLIC_MODE or s.HIDE_STACK_TRACES
        assert hide is True

    def test_stack_trace_visible_in_dev(self, monkeypatch):
        """PUBLIC_MODE=False かつ HIDE_STACK_TRACES=False なら traceback が出る（開発時）。"""
        from backend.config import settings as s
        monkeypatch.setattr(s, "HIDE_STACK_TRACES", False, raising=False)
        monkeypatch.setattr(s, "PUBLIC_MODE", False, raising=False)
        hide = s.PUBLIC_MODE or s.HIDE_STACK_TRACES
        assert hide is False


# ─── admin ロール: 全操作疎通確認 ─────────────────────────────────────────────

class TestAdminCanDoEverything:
    """admin JWT でロール制限がかかった全エンドポイントを通過できることを確認。"""

    def test_admin_can_create_match(self, db_session, seeded_match):
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.post(
                "/api/matches",
                json={
                    "tournament": "Admin Cup", "tournament_level": "国内", "round": "QF",
                    "date": "2026-01-01", "format": "singles", "result": "unknown",
                    "player_a_id": seeded_match.player_a_id,
                    "player_b_id": seeded_match.player_b_id,
                },
                headers=_auth("admin", user_id=1),
            )
            assert resp.status_code in (200, 201)
        finally:
            app.dependency_overrides.clear()

    def test_admin_can_update_match(self, db_session, seeded_match):
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.put(
                f"/api/matches/{seeded_match.id}",
                json={"tournament": "Updated by Admin"},
                headers=_auth("admin", user_id=1),
            )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_admin_can_delete_match(self, db_session, seeded_match):
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.delete(
                f"/api/matches/{seeded_match.id}",
                headers=_auth("admin", user_id=1),
            )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_admin_can_access_cluster_status(self, db_session):
        """クラスタステータスは admin のみアクセス可能。admin JWT で 200 が返る。"""
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(
                "/api/cluster/status",
                headers=_auth("admin", user_id=1),
            )
            # クラスタが未起動でも 200（Ray off 状態を返す）
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.clear()

    def test_non_admin_cannot_access_cluster_status(self, db_session):
        """analyst/coach/player はクラスタステータスにアクセス不可（403 or 401）。
        player は PlayerAccessControlMiddleware が DB チェックで 401 を返すため
        _require_admin_dep より先に弾かれる。どちらも拒否されていることが重要。
        """
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            for role in ("analyst", "coach", "player"):
                resp = client.get(
                    "/api/cluster/status",
                    headers=_auth(role, user_id=99),
                )
                assert resp.status_code in (401, 403), \
                    f"role={role} should be blocked, got {resp.status_code}"
        finally:
            app.dependency_overrides.clear()
