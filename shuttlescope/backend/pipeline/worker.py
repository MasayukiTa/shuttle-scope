"""スタンドアロン解析ワーカー。

FastAPI プロセスとは別プロセスで AnalysisJob を処理する。
pm2 から `python -m backend.pipeline.worker` で起動されることを想定。

特徴:
- ファイルロック (`backend/data/worker.lock`) により多重起動を防止
- SIGTERM / SIGINT によるグレースフルシャットダウン
- GPU 競合回避のため 1 ジョブずつ逐次実行
- FastAPI 側 `start_job_runner()` とは `SS_WORKER_STANDALONE=1` 環境変数経由で排他
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ポーリング間隔（秒）
_POLL_INTERVAL_SEC = 2.0

# ロックファイルのパス（backend/data/worker.lock）
_LOCK_PATH = Path(__file__).resolve().parent.parent / "data" / "worker.lock"

# グレースフルシャットダウン用フラグ
_SHUTDOWN = False


def _install_signal_handlers() -> None:
    """SIGTERM / SIGINT でシャットダウンフラグを立てる。"""

    def _handler(signum, frame):  # noqa: ARG001
        global _SHUTDOWN
        logger.info("signal received signum=%s → graceful shutdown", signum)
        _SHUTDOWN = True

    # Windows では SIGTERM の扱いが限定的だが、SIGINT は動作する
    try:
        signal.signal(signal.SIGINT, _handler)
    except (ValueError, OSError):  # pragma: no cover
        pass
    try:
        signal.signal(signal.SIGTERM, _handler)
    except (ValueError, OSError, AttributeError):  # pragma: no cover
        pass


class _FileLock:
    """プラットフォーム非依存のファイル排他ロック。

    Windows では msvcrt、POSIX では fcntl を利用する。多重起動検知用。
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fp = None

    def acquire(self) -> bool:
        """ロック取得に成功したら True、失敗 (既に他プロセスが保持) なら False。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        # ロック対象の 1 バイトを確保するため、必要なら空ファイルを作成しておく
        if not self._path.exists() or self._path.stat().st_size == 0:
            with open(self._path, "wb") as _f:
                _f.write(b"\0")
        # 読み書き可能モードで開く（内容は保持）
        self._fp = open(self._path, "r+b")
        try:
            if os.name == "nt":
                import msvcrt

                # 1 バイトを非ブロッキングで排他ロック（先頭バイトを対象にする）
                try:
                    self._fp.seek(0)
                    msvcrt.locking(self._fp.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError:
                    self._fp.close()
                    self._fp = None
                    return False
            else:
                import fcntl

                try:
                    fcntl.flock(self._fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError:
                    self._fp.close()
                    self._fp = None
                    return False
        except Exception:
            if self._fp is not None:
                self._fp.close()
                self._fp = None
            raise
        # PID を記録（参考情報）。ロック領域である先頭 1 バイト自体は残しておく。
        try:
            self._fp.seek(1)
            self._fp.truncate(1)
            self._fp.write(str(os.getpid()).encode("ascii"))
            self._fp.flush()
        except Exception:  # pragma: no cover
            pass
        return True

    @staticmethod
    def is_pid_alive(path: str) -> bool:
        """rereview pipeline #11 fix: lock file の PID を読み出して os.kill(pid,0)
        で生存確認する。`kill -9` された worker の lock が残っているケースで、
        新規起動時に「lock は取れないがプロセスは死んでいる」と判定して reaper
        ロジックの一部として活用する。
        """
        try:
            from pathlib import Path as _P
            p = _P(path)
            if not p.exists():
                return False
            data = p.read_bytes()
            if len(data) < 2:
                return False
            pid_str = data[1:].decode("ascii", errors="replace").strip()
            if not pid_str.isdigit():
                return False
            pid = int(pid_str)
            if os.name == "nt":
                # Windows: subprocess で tasklist を呼ぶより、psutil があれば優先
                try:
                    import psutil  # type: ignore
                    return psutil.pid_exists(pid)
                except ImportError:
                    # OpenProcess 経由 fallback
                    import ctypes
                    PROCESS_QUERY = 0x0400 | 0x1000  # QUERY_INFORMATION + LIMITED
                    h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY, False, pid)
                    if h:
                        ctypes.windll.kernel32.CloseHandle(h)
                        return True
                    return False
            else:
                try:
                    os.kill(pid, 0)
                    return True
                except ProcessLookupError:
                    return False
                except PermissionError:
                    return True  # 存在はする
        except Exception:
            return False

    def release(self) -> None:
        if self._fp is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                try:
                    self._fp.seek(0)
                    msvcrt.locking(self._fp.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(self._fp.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            try:
                self._fp.close()
            except Exception:  # pragma: no cover
                pass
            self._fp = None


def process_one() -> bool:
    """キューから 1 件だけ処理する（同期）。処理したら True を返す。

    DB セッションを独立して取得し、1 ジョブを完結させる。GPU 競合を避けるため
    逐次実行する。
    """
    # 遅延 import: テスト時の DB 差し替え (SessionLocal 上書き) に追従する
    from backend.db.database import SessionLocal
    from backend.pipeline.jobs import _claim_next
    from backend.pipeline.video_pipeline import execute_job

    db = SessionLocal()
    try:
        job = _claim_next(db)
        if job is None:
            return False
        logger.info("worker picked job id=%d match_id=%d", job.id, job.match_id)
        execute_job(db, job)
        db.commit()
        return True
    except Exception:
        db.rollback()
        logger.exception("worker process_one error")
        # 例外が起きてもループは継続させたいので True 扱いにはしない
        return False
    finally:
        db.close()


def run_loop(poll_interval: float = _POLL_INTERVAL_SEC) -> int:
    """無限ループでジョブを処理する。SIGTERM/SIGINT で終了。"""
    logger.info("standalone worker loop started pid=%d", os.getpid())
    while not _SHUTDOWN:
        did = process_one()
        if not did:
            # アイドル時はポーリング間隔だけ待機
            for _ in range(max(1, int(poll_interval * 10))):
                if _SHUTDOWN:
                    break
                time.sleep(0.1)
    logger.info("standalone worker loop stopped")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    """エントリポイント。"""
    parser = argparse.ArgumentParser(description="ShuttleScope standalone analysis worker")
    parser.add_argument(
        "--once",
        action="store_true",
        help="キューから最大 1 件だけ処理して終了（テスト用）",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=_POLL_INTERVAL_SEC,
        help="ポーリング間隔（秒）",
    )
    parser.add_argument(
        "--no-lock",
        action="store_true",
        help="ファイルロックを取得しない（テスト用）",
    )
    args = parser.parse_args(argv)

    # backend 標準の logger 設定（未設定なら INFO）
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s - %(message)s",
        )

    _install_signal_handlers()

    lock: Optional[_FileLock] = None
    if not args.no_lock:
        lock = _FileLock(_LOCK_PATH)
        if not lock.acquire():
            logger.error("worker lock already held by another process: %s", _LOCK_PATH)
            return 2

    # 起動時 stale reaper: 前回プロセス Kill で running のまま残った job を failed に戻す。
    # routers/pipeline.py の per-match dedup が永久ブロックされるのを防ぐ。
    try:
        from backend.db.database import SessionLocal
        from backend.pipeline.jobs import reap_stale_jobs
        with SessionLocal() as _reap_db:
            reap_stale_jobs(_reap_db)
    except Exception:  # pragma: no cover
        logger.exception("stale job reaper failed at startup")

    try:
        if args.once:
            # 1 件だけ（キューが空なら即終了）
            process_one()
            return 0
        return run_loop(poll_interval=args.poll_interval)
    finally:
        if lock is not None:
            lock.release()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
