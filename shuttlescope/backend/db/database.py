"""SQLAlchemy データベース設定"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from backend.config import settings


class Base(DeclarativeBase):
    pass


# SQLite（POC）とPostgreSQL（本番）を環境変数で切替
engine = create_engine(
    settings.DATABASE_URL,
    # SQLiteの場合のみ check_same_thread=False が必要
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI依存性注入用DBセッション"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """アプリ起動時にテーブルを作成"""
    from backend.db.models import Base as ModelsBase  # noqa: F401
    ModelsBase.metadata.create_all(bind=engine)
