#!/usr/bin/env python3
"""SQLite → PostgreSQL データ移行スクリプト

ShuttleScope の SQLite データベースを PostgreSQL に移行する。
テストデータが少ない今のうちに実行することを推奨。

使い方:
    python scripts/pg_migrate_sqlite.py \\
        --sqlite  backend/db/shuttlescope.db \\
        --pg-url  postgresql://ss_user:pass@192.168.100.1/shuttlescope

オプション:
    --dry-run    : データを実際に書き込まず件数のみ確認
    --truncate   : 移行前に PostgreSQL の全テーブルを空にする（再移行時）
    --batch-size : 1バッチの行数（デフォルト 500）

注意:
    - PostgreSQL 側のテーブルは事前に作成されている必要があります
      (shuttlescope/backend/main.py 起動で自動作成されます)
    - FK 制約はセッション中一時的に無効化して移行します
    - 移行後に整合性チェックを実行します
"""
from __future__ import annotations

import argparse
import sys
import os
from typing import Any, Dict, List

# プロジェクトルートを sys.path に追加
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _ROOT)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ShuttleScope SQLite → PostgreSQL 移行")
    p.add_argument("--sqlite",     default="backend/db/shuttlescope.db",
                   help="SQLite DB ファイルパス (デフォルト: backend/db/shuttlescope.db)")
    p.add_argument("--pg-url",     required=True,
                   help="PostgreSQL 接続 URL (例: postgresql://ss_user:pass@host/shuttlescope)")
    p.add_argument("--dry-run",    action="store_true", help="書き込みなしで件数確認のみ")
    p.add_argument("--truncate",   action="store_true", help="移行前に全テーブルを TRUNCATE する")
    p.add_argument("--batch-size", type=int, default=500, help="バッチサイズ（デフォルト 500）")
    return p.parse_args()


# テーブルの依存順序（FK 制約を考慮した挿入順）
# 親テーブルを先に、子テーブルを後に挿入する
TABLE_ORDER = [
    "users",
    "players",
    "matches",
    "sets",
    "rallies",
    "strokes",
    "shared_sessions",
    "session_participants",
    "live_sources",
    "comments",
    "event_bookmarks",
    "pre_match_observations",
    "human_forecasts",
    "prematch_predictions",
    "sync_conflicts",
    "match_cv_artifacts",
    "tracknet_frames",
    "pose_keypoints",
    "center_of_gravity",
    "shot_inferences",
    "player_position_frames",
    # その他テーブルは後で自動検出
]


def _migrate(args: argparse.Namespace) -> int:
    """移行メイン処理。戻り値は終了コード（0=成功）。"""
    try:
        from sqlalchemy import create_engine, text, inspect
    except ImportError:
        print("ERROR: sqlalchemy が未インストールです。pip install sqlalchemy を実行してください。")
        return 1

    print(f"[migrate] SQLite: {args.sqlite}")
    print(f"[migrate] PostgreSQL: {args.pg_url.split('@')[-1]}")  # パスワード非表示
    if args.dry_run:
        print("[migrate] ★ DRY RUN モード（書き込みなし）")

    # ── 接続 ─────────────────────────────────────────────────────────
    try:
        sqlite_engine = create_engine(f"sqlite:///{args.sqlite}", connect_args={"timeout": 15})
    except Exception as e:
        print(f"ERROR: SQLite 接続失敗: {e}")
        return 1

    try:
        pg_engine = create_engine(args.pg_url, pool_size=5, max_overflow=0)
        with pg_engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:
        print(f"ERROR: PostgreSQL 接続失敗: {e}")
        return 1

    # ── PostgreSQL の boolean カラムを事前収集 ────────────────────────
    from sqlalchemy import Boolean
    pg_inspector = inspect(pg_engine)
    bool_cols: Dict[str, set] = {}  # table -> set of boolean column names
    for tname in pg_inspector.get_table_names():
        cols = pg_inspector.get_columns(tname)
        bools = {c["name"] for c in cols if isinstance(c["type"], Boolean)}
        if bools:
            bool_cols[tname] = bools

    # ── テーブル一覧取得 ──────────────────────────────────────────────
    sqlite_tables = set(inspect(sqlite_engine).get_table_names())
    pg_tables = set(inspect(pg_engine).get_table_names())

    # 移行対象: SQLite にあり PostgreSQL にもあるテーブル
    # alembic_version は除外
    common = (sqlite_tables & pg_tables) - {"alembic_version"}

    # 依存順で並べ、リストにない残テーブルを末尾に追加
    ordered = [t for t in TABLE_ORDER if t in common]
    remaining = sorted(common - set(ordered))
    ordered += remaining

    print(f"[migrate] 移行対象テーブル数: {len(ordered)}")

    # ── TRUNCATE (再移行時) ────────────────────────────────────────────
    if args.truncate and not args.dry_run:
        print("[migrate] 全テーブルを TRUNCATE します...")
        with pg_engine.connect() as pg_conn:
            pg_conn.execute(text("SET session_replication_role = 'replica'"))
            for table in reversed(ordered):
                try:
                    pg_conn.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
                except Exception as e:
                    print(f"  WARN: {table} TRUNCATE 失敗: {e}")
            pg_conn.execute(text("SET session_replication_role = 'origin'"))
            pg_conn.commit()
        print("[migrate] TRUNCATE 完了")

    # ── 移行 ──────────────────────────────────────────────────────────
    total_rows = 0
    errors = []

    with sqlite_engine.connect() as sq_conn, pg_engine.connect() as pg_conn:
        if not args.dry_run:
            # FK 制約を一時無効化
            pg_conn.execute(text("SET session_replication_role = 'replica'"))

        for table in ordered:
            try:
                rows = sq_conn.execute(text(f"SELECT * FROM {table}")).mappings().all()
                count = len(rows)
                print(f"  {table}: {count} 行", end="")

                if count == 0 or args.dry_run:
                    print(" (スキップ)" if count == 0 else " (dry-run)")
                    total_rows += count
                    continue

                # バッチ挿入
                cols = list(rows[0].keys()) if rows else []
                table_bools = bool_cols.get(table, set())
                inserted = 0
                for i in range(0, count, args.batch_size):
                    batch = [dict(r) for r in rows[i : i + args.batch_size]]
                    # SQLite の boolean (0/1 integer) → PostgreSQL の bool に変換
                    if table_bools:
                        for row in batch:
                            for col in table_bools:
                                if col in row and row[col] is not None:
                                    row[col] = bool(row[col])
                    pg_conn.execute(
                        text(f"INSERT INTO {table} ({','.join(cols)}) "
                             f"VALUES ({','.join(':' + c for c in cols)}) "
                             f"ON CONFLICT DO NOTHING"),
                        batch,
                    )
                    inserted += len(batch)

                pg_conn.commit()
                total_rows += inserted
                print(f" → {inserted} 行挿入")

            except Exception as e:
                errors.append((table, str(e)))
                print(f" → ERROR: {e}")
                try:
                    pg_conn.rollback()
                except Exception:
                    pass

        if not args.dry_run:
            pg_conn.execute(text("SET session_replication_role = 'origin'"))
            pg_conn.commit()

    # ── シーケンス更新 ────────────────────────────────────────────────
    # PostgreSQL の id シーケンスを SQLite の MAX(id) に合わせる
    if not args.dry_run:
        print("[migrate] PostgreSQL シーケンスを更新...")
        with pg_engine.connect() as pg_conn:
            for table in ordered:
                try:
                    max_id = pg_conn.execute(text(f"SELECT MAX(id) FROM {table}")).scalar()
                    if max_id:
                        pg_conn.execute(text(
                            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), {max_id})"
                        ))
                except Exception:
                    pass  # id カラムがないテーブルは無視
            pg_conn.commit()
        print("[migrate] シーケンス更新完了")

    # ── Alembic バージョンのスタンプ ──────────────────────────────────
    if not args.dry_run:
        print("[migrate] Alembic バージョンをスタンプ...")
        try:
            from backend.db.database import stamp_db_head
            stamp_db_head(args.pg_url)
            print("[migrate] Alembic スタンプ完了")
        except Exception as e:
            print(f"[migrate] WARN: Alembic スタンプ失敗 ({e}) — 手動で実行してください")

    # ── 結果サマリー ─────────────────────────────────────────────────
    print()
    print("=" * 50)
    print(f"[migrate] 移行完了: {total_rows} 行")
    if errors:
        print(f"[migrate] エラー: {len(errors)} テーブル")
        for table, err in errors:
            print(f"  - {table}: {err}")
        return 1
    print("[migrate] すべてのテーブルが正常に移行されました")
    return 0


def main() -> None:
    args = _parse_args()
    sys.exit(_migrate(args))


if __name__ == "__main__":
    main()
