"""月次 product_events パーティション自動作成 + ss_user に GRANT。

実行方法:
  - 直接: python scripts\telemetry_ensure_partition.py
  - Windows Scheduled Task: 毎月 25 日 03:00 に実行 (翌月分が間に合うように)
  - 接続先: PGPASSWORD + postgres superuser で接続 (CREATE 権限が必要)

冪等: 既にパーティションが存在すれば CREATE TABLE IF NOT EXISTS で no-op。
失敗時 exit code != 0 を返し、Scheduled Task の history で気付けるようにする。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime


_SQL = """
DO $$
DECLARE
  nxt2 DATE := (date_trunc('month', now()) + interval '2 months')::date;
  nxt3 DATE := (date_trunc('month', now()) + interval '3 months')::date;
  pname TEXT := 'product_events_' || to_char(nxt2, 'YYYY_MM');
BEGIN
  EXECUTE format(
    'CREATE TABLE IF NOT EXISTS %I PARTITION OF product_events FOR VALUES FROM (%L) TO (%L)',
    pname, nxt2, nxt3
  );
  EXECUTE format(
    'GRANT SELECT, INSERT, UPDATE, DELETE ON %I TO ss_user',
    pname
  );
  RAISE NOTICE 'partition % ensured', pname;
END $$;
"""


def main() -> int:
    try:
        import psycopg
    except ImportError:
        print("psycopg not installed", file=sys.stderr)
        return 2

    # 接続情報。Scheduled Task では PGHOST/PGPORT/PGUSER/PGPASSWORD/PGDATABASE を
    # 環境変数で渡す前提。
    host = os.environ.get("PGHOST", "127.0.0.1")
    port = int(os.environ.get("PGPORT", "5432"))
    user = os.environ.get("PGUSER", "postgres")
    pwd = os.environ.get("PGPASSWORD", "")
    dbname = os.environ.get("PGDATABASE", "shuttlescope")

    conninfo = f"host={host} port={port} user={user} password={pwd} dbname={dbname}"
    try:
        with psycopg.connect(conninfo) as conn:
            with conn.cursor() as cur:
                cur.execute(_SQL)
            conn.commit()
        print(f"[{datetime.utcnow().isoformat()}Z] OK")
        return 0
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
