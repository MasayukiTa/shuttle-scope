"""request_logs / product_events の月次パーティションを日次で維持するツール。

背景:
  0032 (request_logs) と 0031 (product_events) は migration 実行時点の
  「当月+翌月」パーティションを 1 回だけ作るだけで、以降パーティションを
  追加する仕組みが無かった。2026-07 分が一度も作られず、7/1 以降
  request_logs への INSERT が全て失敗し監査ログが 24 日間死んでいた事故の
  再発防止として、migration 0046 で `ensure_request_logs_partitions()` /
  `ensure_product_events_partitions()` という idempotent な DB 関数を追加
  した。本ツールはその関数を日次で CALL するだけの薄いラッパー。

権限:
  パーティション作成は DDL なので ss_user では実行できない
  (R47 pg_role_lockdown 後、ss_user から CREATE 権限が剥奪されている)。
  `nginx_log_shipper.py` が DATABASE_URL 経由で ss_user として動くのとは
  対照的に、本ツールは Alembic と同じ `SS_DB_MIGRATION_URL`
  (ss_migration ロール) を直接使う。未設定なら何もせず非ゼロ終了する
  (黙って no-op してパーティション欠落に気づけない、という今回の事故と
  同じ失敗モードを避けるため)。

実行方法:
  python -m backend.tools.ensure_partitions

想定運用:
  Windows Scheduled Task で 1 日 1 回 (例: 深夜 03:10) 起動する。
  months_ahead=2 (当月+2ヶ月先まで) を渡し、日次実行が多少止まっても
  ギャップが生まれない安全マージンを持たせる。
  Scheduled Task の作成自体は本ツールの範囲外 (運用者が prod で設定する)。
"""
from __future__ import annotations

import os
import sys

# backend パッケージを import できるようにルートを通す (nginx_log_shipper.py と同じ形)
from pathlib import Path

_THIS = Path(__file__).resolve()
_BACKEND_ROOT = _THIS.parent.parent.parent  # shuttlescope/
sys.path.insert(0, str(_BACKEND_ROOT))

# 日次で当月 + 何ヶ月先までバンクしておくか。環境変数で上書き可。
MONTHS_AHEAD = int(os.environ.get("SS_PARTITION_MONTHS_AHEAD", "2"))


def main() -> int:
    migration_url = (os.environ.get("SS_DB_MIGRATION_URL") or "").strip()
    if not migration_url:
        # 静かに諦めるとパーティション欠落に誰も気づけない (今回の事故の
        # 再発パターン) ので、必ず非ゼロ終了 + 明示メッセージにする。
        print(
            "[ensure_partitions] ERROR: SS_DB_MIGRATION_URL is not set. "
            "This tool must run as the ss_migration role (DDL rights), "
            "not ss_user. Refusing to silently no-op.",
            file=sys.stderr,
        )
        return 2

    if "postgresql" not in migration_url:
        # SQLite (dev) にはパーティション自体が無い。エラーにはせず、意図
        # 的に何もしていないことだけ明示する。
        print("[ensure_partitions] SS_DB_MIGRATION_URL is not PostgreSQL; nothing to do (dev/SQLite).")
        return 0

    from sqlalchemy import create_engine, text

    engine = create_engine(migration_url, pool_pre_ping=True)
    results: dict[str, str] = {}
    try:
        with engine.begin() as conn:
            has_request_logs = conn.execute(
                text("SELECT to_regclass('public.request_logs') IS NOT NULL")
            ).scalar()
            has_product_events = conn.execute(
                text("SELECT to_regclass('public.product_events') IS NOT NULL")
            ).scalar()

            if has_request_logs:
                conn.execute(
                    text("SELECT ensure_request_logs_partitions(:months_ahead)"),
                    {"months_ahead": MONTHS_AHEAD},
                )
                results["request_logs"] = "ok"
            else:
                results["request_logs"] = "skipped (table missing)"

            if has_product_events:
                conn.execute(
                    text("SELECT ensure_product_events_partitions(:months_ahead)"),
                    {"months_ahead": MONTHS_AHEAD},
                )
                results["product_events"] = "ok"
            else:
                results["product_events"] = "skipped (table missing)"
    except Exception as exc:
        print(f"[ensure_partitions] error: {exc}", file=sys.stderr)
        return 1
    finally:
        engine.dispose()

    print(
        f"[ensure_partitions] months_ahead={MONTHS_AHEAD} "
        f"request_logs={results.get('request_logs')} "
        f"product_events={results.get('product_events')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
