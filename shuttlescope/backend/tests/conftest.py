"""Shared pytest fixtures for backend tests."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import database as db_module
from backend.db import models as _models  # noqa: F401  # ensure metadata registration
from backend.db.database import Base
from backend.utils import response_cache


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
