"""SQLAlchemy データベース設定"""
from sqlalchemy import create_engine, text
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


def add_columns_if_missing(eng) -> None:
    """既存 SQLite DB に不足カラムを後付けする（冪等・N-001/N-002）"""
    new_cols = [
        ("strokes", "opponent_contact_x", "REAL"),
        ("strokes", "opponent_contact_y", "REAL"),
        ("strokes", "player_contact_x",   "REAL"),
        ("strokes", "player_contact_y",   "REAL"),
        ("strokes", "return_target_x",    "REAL"),
        ("strokes", "return_target_y",    "REAL"),
    ]
    with eng.connect() as conn:
        for table, col, col_type in new_cols:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                conn.commit()
            except Exception:
                pass  # カラム既存の場合は無視
