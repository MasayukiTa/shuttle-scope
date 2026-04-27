"""Alembic 環境設定

このファイルは `alembic upgrade head` 実行時、または
`database.run_db_migrations()` 経由でアプリ起動時に使用される。

SQLite の場合は render_as_batch=True で batch モードを有効にする。
これにより ALTER COLUMN 非対応の SQLite でもテーブル再構成ができる。
"""
import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# shuttlescope/ を sys.path に追加して backend パッケージを import できるようにする
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.config import settings
import backend.db.models  # noqa: F401 — モデルを import して metadata に登録
from backend.db.database import Base

config = context.config

# URL 優先順位:
#   1. stamp_db_head / run_db_migrations が set_main_option で明示設定した URL
#      （alembic.ini のデフォルト値と異なる場合）
#   2. settings.DATABASE_URL (.env で SQLite ↔ PostgreSQL を切替)
#   3. alembic.ini の sqlalchemy.url（フォールバック）
# alembic.ini のデフォルト値を直接使うと本番 DB と一致しないため、
# Python コードで明示設定された URL のみ settings より優先する。
_ini_default = "sqlite:///./backend/db/shuttlescope.db"
_config_url = config.get_main_option("sqlalchemy.url") or ""
if _config_url and _config_url != _ini_default:
    configured_url = _config_url  # 明示的に set_main_option で上書きされた値を使う
else:
    configured_url = settings.DATABASE_URL or _config_url
config.set_main_option("sqlalchemy.url", configured_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# SQLite の場合は batch モードで ALTER TABLE を擬似サポート
_use_batch = "sqlite" in configured_url


def run_migrations_offline() -> None:
    """URL のみで migration を実行（DB 接続なし）"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=_use_batch,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """実際の DB 接続で migration を実行"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        connect_args={"timeout": 10} if "sqlite" in configured_url else {},
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_use_batch,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
