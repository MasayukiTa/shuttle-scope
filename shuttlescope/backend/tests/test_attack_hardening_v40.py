"""Attack #40+ ハードニングテスト群 (round 2)。

W1: bcrypt 72-byte truncation (CWE-521)              auth._validate_password_strength
W2: audit log details size cap (CWE-770)             utils.access_log.log_access
W3: 動画ストリームの match scope 厳格化               uploads.stream_video_for_match
W4: sync /conflicts に require_analyst を追加          sync.list_conflicts / resolve_conflict
W5: /mfa/disable の TOTP brute force 防御             auth.mfa_disable
"""
from __future__ import annotations

import pytest


# ─── W1: bcrypt 72-byte truncation 対策 ───────────────────────────────────────


class TestPasswordMaxBytes:
    def test_short_password_passes(self):
        from backend.routers import auth as a

        # 12 文字以上の英大小数字記号を含む 32 byte 程度の password
        a._validate_password_strength("Abcdef12!ghijk")

    def test_password_exactly_72_bytes_passes(self):
        from backend.routers import auth as a

        # ASCII で 72 byte 未満なら通る
        # 12+ chars, lower/upper/digit/symbol を含むパターン
        pw = "Aa1!" + ("x" * 65) + "Z"
        # 4 + 65 + 1 = 70 byte < 72
        assert len(pw.encode("utf-8")) <= 72
        a._validate_password_strength(pw)

    def test_password_over_72_bytes_rejected(self):
        from backend.routers import auth as a
        from fastapi import HTTPException

        pw = "Aa1!" + ("x" * 100) + "Z"
        assert len(pw.encode("utf-8")) > 72
        with pytest.raises(HTTPException) as ei:
            a._validate_password_strength(pw)
        assert ei.value.status_code == 422

    def test_japanese_password_byte_limit(self):
        from backend.routers import auth as a
        from fastapi import HTTPException

        # 日本語 1 文字 = 3 byte。30 文字で 90 byte > 72
        pw = "Aa1!" + ("ぱ" * 30)
        with pytest.raises(HTTPException):
            a._validate_password_strength(pw)


# ─── W2: audit log details size cap ───────────────────────────────────────────


class TestAuditLogDetailsCap:
    def test_normal_details_passes_through(self, db_session):
        from backend.utils import access_log
        from backend.db.models import AccessLog

        access_log.log_access(db_session, "test_action", details={"key": "value"})
        row = db_session.query(AccessLog).order_by(AccessLog.id.desc()).first()
        assert row is not None
        assert "value" in (row.details or "")
        assert "(truncated)" not in (row.details or "")

    def test_oversized_details_truncated(self, db_session):
        from backend.utils import access_log
        from backend.db.models import AccessLog

        big = {"junk": "x" * (access_log._MAX_DETAILS_BYTES * 2)}
        access_log.log_access(db_session, "oversize_test", details=big)
        row = db_session.query(AccessLog).order_by(AccessLog.id.desc()).first()
        assert row is not None
        # 切り詰めマーカーが付き、サイズが上限近辺になる
        assert (row.details or "").endswith("...(truncated)")
        assert len(row.details.encode("utf-8")) <= access_log._MAX_DETAILS_BYTES + len("...(truncated)") + 10


# ─── W4: sync conflicts auth ──────────────────────────────────────────────────


class TestSyncConflictsAuth:
    def test_list_conflicts_has_require_analyst_dep(self):
        """OpenAPI / signature 上に require_analyst が依存として注入されているか確認。

        ここでは関数オブジェクトの依存を表す Depends 値を直接覗く。
        """
        from backend.routers import sync as s
        import inspect

        sig = inspect.signature(s.list_conflicts)
        # require_analyst を import して Depends されたパラメータが
        # sig 内に含まれていることを確認する
        from backend.utils.auth import require_analyst
        deps = []
        for p in sig.parameters.values():
            default = p.default
            # FastAPI Depends() を直接呼び出して default に格納している
            if hasattr(default, "dependency"):
                deps.append(default.dependency)
        assert require_analyst in deps, "list_conflicts must require_analyst"

    def test_resolve_conflict_has_require_analyst_dep(self):
        from backend.routers import sync as s
        import inspect

        sig = inspect.signature(s.resolve_conflict)
        from backend.utils.auth import require_analyst
        deps = [p.default.dependency for p in sig.parameters.values()
                if hasattr(p.default, "dependency")]
        assert require_analyst in deps


# ─── W5: mfa/disable brute force 防御 ─────────────────────────────────────────


class TestMfaDisableBruteForce:
    def test_disable_calls_brute_limit(self, monkeypatch):
        """mfa_disable が _check_mfa_brute_limit を経由することを確認する。"""
        from backend.routers import auth as a

        called = {"count": 0}
        original = a._check_mfa_brute_limit

        def spy(uid):
            called["count"] += 1
            original(uid)

        monkeypatch.setattr(a, "_check_mfa_brute_limit", spy)

        # mfa_disable の本体には _check_mfa_brute_limit 呼び出しが必要
        import inspect
        src = inspect.getsource(a.mfa_disable)
        assert "_check_mfa_brute_limit" in src, "mfa_disable must call _check_mfa_brute_limit"

    def test_disable_records_failure_on_bad_code(self):
        """無効コード時に _record_mfa_failure が呼ばれていることをソースから確認する。"""
        from backend.routers import auth as a
        import inspect
        src = inspect.getsource(a.mfa_disable)
        assert "_record_mfa_failure" in src, "mfa_disable must record failures for brute-force throttling"


# ─── W3: 動画ストリームの match scope 厳格化 ──────────────────────────────────


class TestVideoStreamScope:
    def test_stream_uses_require_match_scope(self):
        from backend.routers import uploads as up
        import inspect

        src = inspect.getsource(up.stream_video_for_match)
        # 厳格 scope ヘルパに切り替わっている
        assert "require_match_scope" in src
        # 旧簡易 helper は本体コードから消えている
        # (コメント中に表示する `user_can_access_match` の文言は許容するため、
        #  関数呼び出し / from import パターンが残っていないことを確認する)
        assert "user_can_access_match(" not in src
        assert "import user_can_access_match" not in src
        assert "from backend.utils.auth import user_can_access_match" not in src
