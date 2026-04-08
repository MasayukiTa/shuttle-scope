"""SQLAlchemy データベース設定"""
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from backend.config import settings
import uuid as _uuid_mod


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


def create_tables(eng=None):
    """アプリ起動時にテーブルを作成"""
    from backend.db.models import Base as ModelsBase  # noqa: F401
    ModelsBase.metadata.create_all(bind=eng or engine)


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
        # 同期メタデータ（全主要テーブル）
        ("players",              "uuid",             "TEXT"),
        ("players",              "updated_at",       "TEXT"),
        ("players",              "deleted_at",       "TEXT"),
        ("players",              "revision",         "INTEGER DEFAULT 1"),
        ("players",              "source_device_id", "TEXT"),
        ("players",              "content_hash",     "TEXT"),
        ("matches",              "uuid",             "TEXT"),
        ("matches",              "deleted_at",       "TEXT"),
        ("matches",              "revision",         "INTEGER DEFAULT 1"),
        ("matches",              "source_device_id", "TEXT"),
        ("matches",              "content_hash",     "TEXT"),
        ("sets",                 "uuid",             "TEXT"),
        ("sets",                 "created_at",       "TEXT"),
        ("sets",                 "updated_at",       "TEXT"),
        ("sets",                 "deleted_at",       "TEXT"),
        ("sets",                 "revision",         "INTEGER DEFAULT 1"),
        ("sets",                 "source_device_id", "TEXT"),
        ("sets",                 "content_hash",     "TEXT"),
        ("rallies",              "uuid",             "TEXT"),
        ("rallies",              "created_at",       "TEXT"),
        ("rallies",              "updated_at",       "TEXT"),
        ("rallies",              "deleted_at",       "TEXT"),
        ("rallies",              "revision",         "INTEGER DEFAULT 1"),
        ("rallies",              "source_device_id", "TEXT"),
        ("rallies",              "content_hash",     "TEXT"),
        ("strokes",              "uuid",             "TEXT"),
        ("strokes",              "created_at",       "TEXT"),
        ("strokes",              "updated_at",       "TEXT"),
        ("strokes",              "deleted_at",       "TEXT"),
        ("strokes",              "revision",         "INTEGER DEFAULT 1"),
        ("strokes",              "source_device_id", "TEXT"),
        ("strokes",              "content_hash",     "TEXT"),
        ("pre_match_observations", "uuid",           "TEXT"),
        ("pre_match_observations", "updated_at",     "TEXT"),
        ("pre_match_observations", "deleted_at",     "TEXT"),
        ("pre_match_observations", "revision",       "INTEGER DEFAULT 1"),
        ("pre_match_observations", "source_device_id", "TEXT"),
        ("pre_match_observations", "content_hash",   "TEXT"),
        ("human_forecasts",      "uuid",             "TEXT"),
        ("human_forecasts",      "updated_at",       "TEXT"),
        ("human_forecasts",      "deleted_at",       "TEXT"),
        ("human_forecasts",      "revision",         "INTEGER DEFAULT 1"),
        ("human_forecasts",      "source_device_id", "TEXT"),
        ("human_forecasts",      "content_hash",     "TEXT"),
        ("comments",             "uuid",             "TEXT"),
        ("comments",             "updated_at",       "TEXT"),
        ("comments",             "deleted_at",       "TEXT"),
        ("comments",             "revision",         "INTEGER DEFAULT 1"),
        ("comments",             "source_device_id", "TEXT"),
        ("comments",             "content_hash",     "TEXT"),
        ("event_bookmarks",      "uuid",             "TEXT"),
        ("event_bookmarks",      "updated_at",       "TEXT"),
        ("event_bookmarks",      "deleted_at",       "TEXT"),
        ("event_bookmarks",      "revision",         "INTEGER DEFAULT 1"),
        ("event_bookmarks",      "source_device_id", "TEXT"),
        ("event_bookmarks",      "content_hash",     "TEXT"),
    ]
    with eng.connect() as conn:
        for table, col, col_type in new_cols:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_type}"))
                conn.commit()
            except Exception:
                pass  # カラム既存の場合は無視

    _backfill_sync_metadata(eng)


def _backfill_sync_metadata(eng) -> None:
    """既存レコードに uuid / updated_at が未設定の場合にバックフィルする（冪等）"""
    # uuid が NULL のレコードへ発行
    uuid_tables = [
        "players", "matches", "sets", "rallies", "strokes",
        "pre_match_observations", "human_forecasts", "comments", "event_bookmarks",
    ]
    with eng.connect() as conn:
        for table in uuid_tables:
            try:
                rows = conn.execute(text(f"SELECT id FROM {table} WHERE uuid IS NULL")).fetchall()
                for (row_id,) in rows:
                    new_uuid = str(_uuid_mod.uuid4())
                    conn.execute(text(f"UPDATE {table} SET uuid = :u WHERE id = :id"), {"u": new_uuid, "id": row_id})
                if rows:
                    conn.commit()
            except Exception:
                pass

        # updated_at / created_at が NULL のテーブルを現在時刻で埋める
        ts_tables = [
            ("sets",    "created_at"), ("sets",    "updated_at"),
            ("rallies", "created_at"), ("rallies", "updated_at"),
            ("strokes", "created_at"), ("strokes", "updated_at"),
            ("players", "updated_at"),
            ("pre_match_observations", "updated_at"),
            ("human_forecasts",  "updated_at"),
            ("comments",         "updated_at"),
            ("event_bookmarks",  "updated_at"),
        ]
        now_iso = "2026-01-01T00:00:00"  # 既存データへの固定マーカー
        for table, col in ts_tables:
            try:
                conn.execute(text(f"UPDATE {table} SET {col} = :ts WHERE {col} IS NULL"), {"ts": now_iso})
                conn.commit()
            except Exception:
                pass


def _ensure_unique_indexes(eng) -> None:
    """既存 SQLite DB の uuid カラムに UNIQUE INDEX を追加する（冪等）。
    重複 uuid があるテーブルはスキップして警告を出す。
    """
    uuid_tables = [
        "players", "matches", "sets", "rallies", "strokes",
        "pre_match_observations", "human_forecasts", "comments", "event_bookmarks",
    ]
    with eng.connect() as conn:
        for table in uuid_tables:
            # 重複チェック
            try:
                dup = conn.execute(
                    text(f"SELECT uuid, COUNT(*) AS c FROM {table} WHERE uuid IS NOT NULL GROUP BY uuid HAVING c > 1")
                ).fetchall()
                if dup:
                    print(f"[sync] WARNING: {table}.uuid に重複あり — unique index をスキップ ({len(dup)} 件)")
                    continue
            except Exception:
                continue
            # UNIQUE INDEX 作成（既存の場合は無視）
            idx_name = f"uix_{table}_uuid"
            try:
                conn.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS {idx_name} ON {table}(uuid)"))
                conn.commit()
            except Exception:
                pass


def _ensure_analytics_indexes(eng) -> None:
    """解析・予測クエリ向け複合インデックスを追加する（冪等）。"""
    indexes = [
        # matches
        ("ix_matches_player_a_id",          "matches",               "player_a_id"),
        ("ix_matches_player_b_id",          "matches",               "player_b_id"),
        ("ix_matches_date",                 "matches",               "date"),
        ("ix_matches_tournament_level",     "matches",               "tournament_level"),
        # sets
        ("ix_sets_match_id_set_num",        "sets",                  "match_id, set_num"),
        # rallies
        ("ix_rallies_set_id_rally_num",     "rallies",               "set_id, rally_num"),
        # strokes
        ("ix_strokes_rally_id_stroke_num",  "strokes",               "rally_id, stroke_num"),
        ("ix_strokes_player",               "strokes",               "player"),
        ("ix_strokes_shot_type",            "strokes",               "shot_type"),
        ("ix_strokes_hit_zone",             "strokes",               "hit_zone"),
        ("ix_strokes_land_zone",            "strokes",               "land_zone"),
        # pre_match_observations
        ("ix_pmo_match_player_type",        "pre_match_observations","match_id, player_id, observation_type"),
        # human_forecasts
        ("ix_hf_match_player",              "human_forecasts",       "match_id, player_id"),
        # sync_conflicts
        ("ix_sc_record_uuid",               "sync_conflicts",        "record_uuid"),
        ("ix_sc_resolution",                "sync_conflicts",        "resolution"),
    ]
    with eng.connect() as conn:
        for idx_name, table, cols in indexes:
            try:
                conn.execute(text(f"CREATE INDEX IF NOT EXISTS {idx_name} ON {table}({cols})"))
                conn.commit()
            except Exception:
                pass


def run_db_migrations() -> None:
    """Alembic migration を実行する（upgrade head）。

    - インメモリ DB（テスト用）はスキップする
    - migration ファイルは backend/db/migrations/versions/ に配置
    - 失敗しても WARNING のみ（起動を止めない）
    """
    if ":memory:" in settings.DATABASE_URL:
        return
    try:
        import pathlib
        from alembic.config import Config
        from alembic import command

        alembic_ini = pathlib.Path(__file__).parent / "alembic.ini"
        alembic_cfg = Config(str(alembic_ini))
        command.upgrade(alembic_cfg, "head")
    except Exception as e:
        print(f"[migration] WARNING: Alembic migration failed: {e}")


def _table_names(eng) -> set[str]:
    """Return the current table names in the bound database."""
    return set(inspect(eng).get_table_names())


def stamp_db_head(db_url: str | None = None) -> None:
    """Mark the current schema as Alembic head without replaying revisions."""
    url = db_url or settings.DATABASE_URL
    if ":memory:" in url:
        return
    try:
        import pathlib
        from alembic.config import Config
        from alembic import command

        alembic_ini = pathlib.Path(__file__).parent / "alembic.ini"
        alembic_cfg = Config(str(alembic_ini))
        alembic_cfg.set_main_option("sqlalchemy.url", url)
        command.stamp(alembic_cfg, "head")
    except Exception as e:
        print(f"[migration] WARNING: Alembic stamp failed: {e}")


def run_db_migrations(db_url: str | None = None) -> None:
    """Apply Alembic revisions up to head for file-backed databases."""
    url = db_url or settings.DATABASE_URL
    if ":memory:" in url:
        return
    try:
        import pathlib
        from alembic.config import Config
        from alembic import command

        alembic_ini = pathlib.Path(__file__).parent / "alembic.ini"
        alembic_cfg = Config(str(alembic_ini))
        alembic_cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(alembic_cfg, "head")
    except Exception as e:
        print(f"[migration] WARNING: Alembic migration failed: {e}")


def bootstrap_database(eng=None, db_url: str | None = None) -> None:
    """Initialize the database safely across fresh, legacy, and versioned states."""
    bind = eng or engine
    url = db_url or settings.DATABASE_URL

    if ":memory:" in url:
        create_tables(bind)
        return

    before_tables = _table_names(bind)
    has_version_table = "alembic_version" in before_tables
    has_app_tables = bool(before_tables - {"alembic_version"})

    if not has_app_tables and not has_version_table:
        create_tables(bind)
        _ensure_unique_indexes(bind)
        _ensure_analytics_indexes(bind)
        stamp_db_head(url)
        return

    if has_version_table:
        run_db_migrations(url)
        _ensure_unique_indexes(bind)
        _ensure_analytics_indexes(bind)
        return

    create_tables(bind)
    add_columns_if_missing(bind)
    run_db_migrations(url)
    _ensure_unique_indexes(bind)
    _ensure_analytics_indexes(bind)
