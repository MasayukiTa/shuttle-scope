"""pytest 共通フィクスチャ"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import database as db_module
from backend.db.database import Base
from backend.db import models as _models  # noqa: F401  # Base.metadata 登録を確実化


@pytest.fixture(scope="session")
def test_engine():
    """インメモリ SQLite エンジン（テストセッション全体で共有）

    StaticPool を使用: インメモリ SQLite では接続ごとに別 DB になるため、
    全接続が同一の DB を共有するよう強制する。これにより POST → commit 後も
    同じテーブルが見える。
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    # CI のクリーン環境でも全モデルのテーブルが必ず作られるようにする。
    Base.metadata.create_all(engine)

    # テスト中に backend.db.database.SessionLocal を直接参照するコード
    # （WebSocket / background task / helper など）も同じ in-memory DB を使うように差し替える。
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
    """各テストごとにロールバックするデータベースセッション"""
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSession()
    yield session
    session.rollback()
    session.close()
