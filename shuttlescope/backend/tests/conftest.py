"""pytest 共通フィクスチャ"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.db.database import Base


@pytest.fixture(scope="session")
def test_engine():
    """インメモリ SQLite エンジン（テストセッション全体で共有）"""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(test_engine):
    """各テストごとにロールバックするデータベースセッション"""
    TestingSession = sessionmaker(bind=test_engine)
    session = TestingSession()
    yield session
    session.rollback()
    session.close()
