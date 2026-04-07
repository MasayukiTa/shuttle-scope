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
    """既存 SQLite DB に不足カラムを後付けする（冪等・N-001/N-002/V4）"""
    new_cols = [
        # N-001/N-002: 空間座標拡張
        ("strokes", "opponent_contact_x", "REAL"),
        ("strokes", "opponent_contact_y", "REAL"),
        ("strokes", "player_contact_x",   "REAL"),
        ("strokes", "player_contact_y",   "REAL"),
        ("strokes", "return_target_x",    "REAL"),
        ("strokes", "return_target_y",    "REAL"),
        # V4: Player プロフィール確定度・暫定作成管理
        ("players", "profile_status",          "TEXT DEFAULT 'verified'"),
        ("players", "needs_review",             "INTEGER DEFAULT 0"),
        ("players", "created_via_quick_start",  "INTEGER DEFAULT 0"),
        ("players", "organization",             "TEXT"),
        ("players", "aliases",                  "TEXT"),
        ("players", "name_normalized",          "TEXT"),
        ("players", "scouting_notes",           "TEXT"),
        # V4: dominant_hand を nullable に（SQLite では型変更不要、null を許容するだけ）
        # V4: Match メタデータ
        ("matches", "initial_server",           "TEXT"),
        ("matches", "competition_type",         "TEXT DEFAULT 'unknown'"),
        ("matches", "created_via_quick_start",  "INTEGER DEFAULT 0"),
        ("matches", "metadata_status",          "TEXT DEFAULT 'minimal'"),
        # 途中終了理由（retired_a / retired_b / abandoned）
        ("matches", "exception_reason",         "TEXT"),
        # 見逃しラリー（ストロークなしで得点だけ記録）
        ("rallies", "is_skipped",               "INTEGER DEFAULT 0"),
        # R-001: 共有セッション
        ("shared_sessions", "last_broadcast_at", "TEXT"),
        # G2: 返球品質・打点高さ（ストローク確定後オプション入力）
        ("strokes", "return_quality",            "TEXT"),
        ("strokes", "contact_height",            "TEXT"),
        # 移動系コンテキスト（4.1 Movement Features）
        ("strokes", "contact_zone",              "TEXT"),
        ("strokes", "movement_burden",           "TEXT"),
        ("strokes", "movement_direction",        "TEXT"),
        # score_before/after 分離（局面判定精度向上）
        ("rallies", "score_a_before",            "INTEGER DEFAULT 0"),
        ("rallies", "score_b_before",            "INTEGER DEFAULT 0"),
    ]
    with eng.connect() as conn:
        for table, col, col_type in new_cols:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                conn.commit()
            except Exception:
                pass  # カラム既存の場合は無視
