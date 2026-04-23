"""SQLAlchemy データベース設定"""
import logging
import os
from sqlalchemy import create_engine, event, text, inspect
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from backend.config import settings
import uuid as _uuid_mod

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


# SQLite（POC）とPostgreSQL（本番）を環境変数で切替
engine = create_engine(
    settings.DATABASE_URL,
    # SQLiteの場合のみ check_same_thread=False が必要
    # timeout=15: ロック競合時に最大15秒待機してからエラー（デフォルトは無限待ち）
    connect_args={"check_same_thread": False, "timeout": 15} if "sqlite" in settings.DATABASE_URL else {},
)


# SQLite PRAGMA 最適化（ファイルDBのみ、:memory: は対象外）
# - journal_mode=WAL: 書き込みと読み込みの並列性を向上、読み込み遅延の主因を緩和
# - synchronous=NORMAL: WAL と組み合わせて安全性を大きく損なわず書き込み高速化
# - temp_store=MEMORY: 一時テーブル/インデックスをメモリ配置で集計クエリ高速化
# - cache_size=-20000: ページキャッシュ ≒ 20MB
# - mmap_size=268435456: 256MB を memory-map して read 負荷を軽減
# 失敗時は無視して通常動作を継続（信頼性に影響しない）
if "sqlite" in settings.DATABASE_URL and ":memory:" not in settings.DATABASE_URL:
    @event.listens_for(engine, "connect")
    def _sqlite_pragma_on_connect(dbapi_connection, _connection_record):
        try:
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA temp_store=MEMORY")
            cur.execute("PRAGMA cache_size=-20000")
            cur.execute("PRAGMA mmap_size=268435456")
            # auto_vacuum=INCREMENTAL: 削除後の空きページを定期的に回収できるようにする
            cur.execute("PRAGMA auto_vacuum=INCREMENTAL")
            cur.close()
        except Exception:
            pass


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
        # Phase A: 認証カラム（users テーブル）
        ("users", "hashed_credential", "VARCHAR(128)"),
        ("users", "display_name",      "VARCHAR(100)"),
        ("users", "team_name",         "VARCHAR(100)"),
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
        # アノテーション記録方式 / レビューステータス
        ("rallies", "annotation_mode",           "TEXT"),
        ("rallies", "review_status",             "TEXT"),
        # 入力ソース
        ("strokes", "source_method",             "TEXT"),
        # LAN セッション認証・デバイス制御 (migration 0003)
        ("shared_sessions",    "password_hash",           "TEXT"),
        ("session_participants", "device_type",           "TEXT"),
        ("session_participants", "connection_role",       "TEXT DEFAULT 'viewer'"),
        ("session_participants", "source_capability",     "TEXT"),
        ("session_participants", "video_receive_enabled", "INTEGER DEFAULT 0"),
        ("session_participants", "authenticated_at",      "TEXT"),
        ("session_participants", "connection_state",      "TEXT DEFAULT 'idle'"),
        # デバイスライフサイクル (migration 0004)
        ("session_participants", "device_uid",            "TEXT"),
        ("session_participants", "approval_status",       "TEXT DEFAULT 'pending'"),
        ("session_participants", "last_heartbeat",        "TEXT"),
        ("session_participants", "viewer_permission",     "TEXT DEFAULT 'default'"),
        ("session_participants", "device_class",          "TEXT"),
        ("session_participants", "display_size_class",    "TEXT DEFAULT 'standard'"),
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
        # コートキャリブレーション（court_calibration artifact type が使用）
        ("match_cv_artifacts",   "summary",          "TEXT"),
        ("match_cv_artifacts",   "backend_used",     "TEXT"),
        # セキュリティ強化: アカウントロックアウト・MFA
        ("users", "failed_attempts", "INTEGER DEFAULT 0"),
        ("users", "locked_until",    "TEXT"),
        ("users", "totp_secret",     "VARCHAR(64)"),
        ("users", "totp_enabled",    "INTEGER DEFAULT 0"),
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
        # prematch_predictions
        ("ix_pp_match_player",              "prematch_predictions",  "match_id, player_id"),
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


def get_db_stats(eng=None) -> dict:
    """DB ファイルの状態を返す（SQLite のみ）。

    返却フィールド:
      file_size_mb  : DBファイルのサイズ（MB）。ファイルが存在しない場合は 0。
      page_count    : 総ページ数
      freelist_count: 未使用（削除済み）ページ数
      auto_vacuum   : 0=OFF / 1=FULL / 2=INCREMENTAL
      wal_frames    : WAL ファイルの未チェックポイントフレーム数（概算）
    """
    bind = eng or engine
    if "sqlite" not in str(bind.url):
        return {"supported": False}

    # DB ファイルパスの取得（:memory: でなければ URL から）
    url_str = str(bind.url)
    db_path = url_str.replace("sqlite:///", "").replace("sqlite://", "")
    file_size_mb = round(os.path.getsize(db_path) / 1_048_576, 2) if os.path.isfile(db_path) else 0.0
    wal_path = db_path + "-wal"
    wal_size_mb = round(os.path.getsize(wal_path) / 1_048_576, 2) if os.path.isfile(wal_path) else 0.0

    with bind.connect() as conn:
        page_count    = conn.execute(text("PRAGMA page_count")).scalar() or 0
        freelist_count = conn.execute(text("PRAGMA freelist_count")).scalar() or 0
        auto_vacuum   = conn.execute(text("PRAGMA auto_vacuum")).scalar() or 0
        page_size     = conn.execute(text("PRAGMA page_size")).scalar() or 4096

    return {
        "supported": True,
        "file_size_mb": file_size_mb,
        "wal_size_mb": wal_size_mb,
        "page_count": page_count,
        "freelist_count": freelist_count,
        "freelist_ratio": round(freelist_count / max(page_count, 1), 4),
        "auto_vacuum": int(auto_vacuum),
        "page_size": int(page_size),
    }


def run_maintenance(eng=None) -> dict:
    """WAL チェックポイント + incremental_vacuum を実行する（軽量メンテ）。

    - wal_checkpoint(TRUNCATE): WAL フレームをメイン DB に書き込み WAL を切り詰める
    - incremental_vacuum: auto_vacuum=INCREMENTAL 設定時に空きページを回収する
    - auto_vacuum が OFF (0) の場合は incremental_vacuum をスキップし WARN のみ

    戻り値: 実行前後の freelist_count 等の統計情報
    """
    bind = eng or engine
    if "sqlite" not in str(bind.url):
        return {"supported": False, "message": "SQLite 以外は対象外"}

    before = get_db_stats(bind)

    with bind.connect() as conn:
        # WAL チェックポイント（未コミットフレームをメイン DB に書き込む）
        conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))

        av_mode = conn.execute(text("PRAGMA auto_vacuum")).scalar() or 0
        if int(av_mode) == 0:
            logger.warning(
                "run_maintenance: auto_vacuum=OFF のため incremental_vacuum をスキップします。"
                " bootstrap_database() を再実行して INCREMENTAL に切り替えてください。"
            )
        else:
            conn.execute(text("PRAGMA incremental_vacuum"))

        conn.commit()

    after = get_db_stats(bind)

    freed_pages = before.get("freelist_count", 0) - after.get("freelist_count", 0)
    page_size = after.get("page_size", 4096)
    freed_mb = round(freed_pages * page_size / 1_048_576, 3)

    return {
        "supported": True,
        "auto_vacuum_mode": int(av_mode),
        "freed_pages": freed_pages,
        "freed_mb": freed_mb,
        "before": before,
        "after": after,
    }


def set_auto_vacuum_mode(target_mode: int, eng=None) -> dict:
    """auto_vacuum モードを変更して VACUUM を実行する。

    target_mode: 0=OFF / 1=FULL / 2=INCREMENTAL

    SQLite の auto_vacuum 変更は VACUUM 後に有効になる。
    SQLAlchemy のプールを一時解放してから sqlite3 直接接続で VACUUM を実行する。
    """
    bind = eng or engine
    if "sqlite" not in str(bind.url):
        return {"supported": False, "message": "SQLite 以外は対象外"}

    url_str = str(bind.url)
    if ":memory:" in url_str:
        # インメモリ DB は VACUUM/dispose するとテーブルが消えるため no-op
        return {"supported": False, "message": "in-memory DB は対象外"}

    db_path = url_str.replace("sqlite:///", "").replace("sqlite://", "")

    mode_labels = {0: "OFF", 1: "FULL", 2: "INCREMENTAL"}
    before = get_db_stats(bind)
    current_mode = before.get("auto_vacuum", -1)

    if current_mode == target_mode:
        return {
            "supported": True,
            "changed": False,
            "auto_vacuum": target_mode,
            "message": f"既に {mode_labels.get(target_mode, target_mode)} です",
            "stats": before,
        }

    try:
        # 1. WAL を先にチェックポイントして全コミット済みデータをメインファイルへ
        with bind.connect() as conn:
            conn.execute(text("PRAGMA wal_checkpoint(TRUNCATE)"))
            conn.commit()

        # 2. SQLAlchemy プールを完全解放（VACUUM が排他ロックを取れるようにする）
        bind.dispose()

        # 3. sqlite3 直接接続で auto_vacuum を設定してから VACUUM
        #    PRAGMA auto_vacuum の変更は VACUUM 実行時に有効になる
        import sqlite3 as _sqlite3
        con = _sqlite3.connect(db_path, timeout=60)
        con.execute(f"PRAGMA auto_vacuum={target_mode}")
        con.commit()
        con.execute("VACUUM")
        con.commit()
        con.close()

        logger.info("set_auto_vacuum_mode: %s → %s (VACUUM 完了)", mode_labels.get(current_mode), mode_labels.get(target_mode))
        after = get_db_stats(bind)
        return {
            "supported": True,
            "changed": True,
            "auto_vacuum": target_mode,
            "message": f"{mode_labels.get(current_mode, current_mode)} → {mode_labels.get(target_mode, target_mode)} に変更しました",
            "stats": after,
        }
    except Exception as exc:
        logger.warning("set_auto_vacuum_mode: 失敗: %s", exc)
        return {
            "supported": True,
            "changed": False,
            "error": str(exc),
            "stats": before,
        }


def _ensure_auto_vacuum_incremental(eng) -> None:
    """auto_vacuum を INCREMENTAL に設定する（既に設定済みなら no-op）。

    SQLite の auto_vacuum モード変更は VACUUM 実行後にしか有効にならないため、
    モードが 0 (OFF) のときのみ PRAGMA + VACUUM を実行する。
    FULL (1) → INCREMENTAL (2) の切替は VACUUM なしでは不可のため同様に実行。
    """
    if ":memory:" in str(eng.url):
        return
    try:
        with eng.connect() as conn:
            current = conn.execute(text("PRAGMA auto_vacuum")).scalar()
            if int(current or 0) == 2:
                return  # 既に INCREMENTAL
            logger.info("_ensure_auto_vacuum_incremental: auto_vacuum=%s → INCREMENTAL に変更します（VACUUM 実行）", current)
            conn.execute(text("PRAGMA auto_vacuum=INCREMENTAL"))
            conn.commit()
        # VACUUM はトランザクション外で実行する必要がある
        import sqlite3
        url_str = str(eng.url)
        db_path = url_str.replace("sqlite:///", "").replace("sqlite://", "")
        con = sqlite3.connect(db_path)
        con.execute("VACUUM")
        con.close()
        logger.info("_ensure_auto_vacuum_incremental: 完了")
    except Exception as exc:
        logger.warning("_ensure_auto_vacuum_incremental: 失敗（無視）: %s", exc)


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
        _ensure_auto_vacuum_incremental(bind)
        return

    if has_version_table:
        create_tables(bind)
        run_db_migrations(url)
        _ensure_unique_indexes(bind)
        _ensure_analytics_indexes(bind)
        _ensure_auto_vacuum_incremental(bind)
        return

    create_tables(bind)
    add_columns_if_missing(bind)
    run_db_migrations(url)
    _ensure_unique_indexes(bind)
    _ensure_analytics_indexes(bind)
    _ensure_auto_vacuum_incremental(bind)
