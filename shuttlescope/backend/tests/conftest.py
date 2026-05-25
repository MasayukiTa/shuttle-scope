"""Shared pytest fixtures for backend tests."""

# Disable the admin-MFA gate BEFORE any backend module is imported.
# Production behaviour (Round 281+): an admin role must have totp_enabled=True
# in the User row for AuthCtx.is_admin to return True. Tests bootstrap an
# admin via BOOTSTRAP_ADMIN_USERNAME/PASSWORD with no TOTP enrolment, so
# every admin-gated endpoint returns 403 in CI. The gate has a designed
# escape hatch — `SS_REQUIRE_ADMIN_MFA=0` — that must be in os.environ
# BEFORE Settings() is instantiated for the first time, since pydantic
# BaseSettings reads env vars on construction only.
import os  # noqa: E402
os.environ.setdefault("SS_REQUIRE_ADMIN_MFA", "0")

import pytest  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from backend.db import database as db_module  # noqa: E402
from backend.db import models as _models  # noqa: F401,E402  # ensure metadata registration
from backend.db.database import Base  # noqa: E402
from backend.utils import response_cache  # noqa: E402


@pytest.fixture(autouse=True, scope="session")
def _disable_admin_mfa_gate():
    """Belt-and-braces: also override the runtime attribute in case some test
    overwrites it. Env-var path above is the primary defence — this fixture
    catches the case where a test directly mutates settings.ss_require_admin_mfa.
    """
    from backend.config import settings as _ss
    original = getattr(_ss, "ss_require_admin_mfa", True)
    try:
        _ss.ss_require_admin_mfa = False
    except Exception:
        pass
    yield
    try:
        _ss.ss_require_admin_mfa = original
    except Exception:
        pass


@pytest.fixture(autouse=True)
def _reset_jwt_caches():
    """各テストで JWT 関連のグローバル cache をクリアする。
    test_database_bootstrap 等で同一プロセス内 DB 切替が起きると、
    `_MASS_REVOKE_CACHE` に過去 DB のスナップショットが残って
    後続テストの token を `mass-revoked` 扱いで 401 にする事故が観測されたため。
    """
    try:
        from backend.utils.jwt_utils import _MASS_REVOKE_CACHE
        _MASS_REVOKE_CACHE["ts"] = 0.0
        _MASS_REVOKE_CACHE["value"] = None
    except Exception:
        pass
    yield


@pytest.fixture(scope="session")
def test_engine():
    """Create one shared in-memory SQLite engine for the backend test session."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    # Force the app/database module to use the same in-memory DB everywhere,
    # including websocket helpers and short-lived SessionLocal lookups.
    original_engine = db_module.engine
    original_session_local = db_module.SessionLocal
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db_module.engine = engine
    db_module.SessionLocal = TestingSessionLocal
    yield engine
    db_module.engine = original_engine
    db_module.SessionLocal = original_session_local
    engine.dispose()


@pytest.fixture()
def db_session(test_engine):
    """Provide a rollback-isolated DB session for each test."""
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSession()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(autouse=True)
def reset_response_cache(db_session, monkeypatch, request):
    """Clear response cache state for every test to avoid order-dependent failures."""
    response_cache.MEMORY_CACHE.clear()
    response_cache.PLAYER_VERSION.clear()
    response_cache.DATA_VERSION = 0

    # Most integration tests seed data with flush() only. Disable the cache's DB
    # persistence layer there so a short-lived SessionLocal does not interfere with
    # the uncommitted test transaction. Keep the real DB behavior for dedicated
    # response_cache unit tests.
    if request.node.fspath.basename != "test_response_cache.py":
        monkeypatch.setattr(response_cache, "_db_lookup", lambda *a, **k: None)
        monkeypatch.setattr(response_cache, "_db_upsert", lambda *a, **k: None)
        monkeypatch.setattr(response_cache, "_db_delete_all", lambda *a, **k: None)
        monkeypatch.setattr(response_cache, "_db_delete_players", lambda *a, **k: None)
    else:
        try:
            from backend.db.models import AnalysisCache

            db_session.query(AnalysisCache).delete()
            db_session.commit()
        except Exception:
            db_session.rollback()

    yield

    response_cache.MEMORY_CACHE.clear()
    response_cache.PLAYER_VERSION.clear()
    response_cache.DATA_VERSION = 0
