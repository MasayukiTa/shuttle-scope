"""PostgreSQL の古いログファイルを削除する (保持日数を過ぎたもののみ)。

SSD 配慮: 削除のみ。圧縮・移動・再書き込みは一切しない。
安全策:
  - 保持日数内のファイルは触らない
  - 現在書き込み中 (最新 mtime) のファイルは日数に関わらず必ず除外
  - 削除できなかったもの (ロック等) はスキップして続行

日次のスケジュールタスクから呼ぶことを想定 (引数不要)。
"""
import datetime
import os
import sys
from pathlib import Path

LOG_DIR = Path(r"C:\Program Files\PostgreSQL\16\data\log")
KEEP_DAYS = int(os.environ.get("SS_PG_LOG_KEEP_DAYS", "14"))


def main() -> int:
    if not LOG_DIR.is_dir():
        print(f"[pg_log_cleanup] log dir not found: {LOG_DIR}")
        return 0

    files = list(LOG_DIR.glob("*.log"))
    if not files:
        print("[pg_log_cleanup] no log files")
        return 0

    cutoff = datetime.datetime.now() - datetime.timedelta(days=KEEP_DAYS)
    # 現在書き込み中のファイルは絶対に消さない
    newest = max(files, key=lambda p: p.stat().st_mtime)

    deleted = failed = 0
    freed = 0
    for p in files:
        if p == newest:
            continue
        try:
            st = p.stat()
            if datetime.datetime.fromtimestamp(st.st_mtime) >= cutoff:
                continue
            size = st.st_size
            p.unlink()
            deleted += 1
            freed += size
        except Exception as exc:  # noqa: BLE001 - ロック中等はスキップ
            failed += 1
            if failed <= 3:
                print(f"[pg_log_cleanup] skip {p.name}: {type(exc).__name__}")

    print(f"[pg_log_cleanup] keep_days={KEEP_DAYS} deleted={deleted} "
          f"failed={failed} freed={freed / 1024 / 1024 / 1024:.2f} GB "
          f"current={newest.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
