"""解析ジョブランナー。

AnalysisJob を 1 件ずつ asyncio タスクで処理する（GPU 競合回避）。
start_job_runner() は冪等（多重起動防止）。
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import AnalysisJob

logger = logging.getLogger(__name__)


# 多重起動防止フラグ（プロセス内）
_RUNNER_TASK: Optional[asyncio.Task] = None
_RUNNER_LOCK = asyncio.Lock() if False else None  # 参照保持用。実体は start で生成
_POLL_INTERVAL_SEC = 2.0


def enqueue(db: Session, match_id: int, job_type: str = "full_pipeline") -> AnalysisJob:
    """新しいジョブをキューに投入する。"""
    job = AnalysisJob(match_id=match_id, job_type=job_type, status="queued", progress=0.0)
    db.add(job)
    db.flush()
    db.commit()
    logger.info("enqueued job id=%d match_id=%d type=%s", job.id, match_id, job_type)
    return job


def _claim_next(db: Session) -> Optional[AnalysisJob]:
    """queued 状態の最古ジョブを 1 件アトミックにクレームする。

    対策:
      - PostgreSQL: SELECT ... FOR UPDATE SKIP LOCKED で行ロック取得後 UPDATE
      - SQLite: SELECT → conditional UPDATE (rowcount 0 ならレース敗北)

    rereview NEW-B fix: 旧実装は SQLite 想定の SELECT → conditional UPDATE のみ
    で、PostgreSQL READ COMMITTED では SELECT 時点ではロックが取られないため
    複数 worker が同じ candidate を SELECT し、最初の UPDATE 成功者以外は
    rowcount=0 で None を返す → 結果 OK だが「next 候補がスキップされる」副作用が
    出ていた (FIFO 順序が崩れる)。`with_for_update(skip_locked=True)` で行ロックを
    取れば PostgreSQL でも他 worker は次の候補を見にいく。
    """
    import socket
    dialect_name = ""
    try:
        dialect_name = (db.bind.dialect.name if db.bind else "").lower()
    except Exception:
        dialect_name = ""

    if dialect_name == "postgresql":
        # PG: 行ロック付き SELECT で claim を取る
        row = (
            db.query(AnalysisJob)
            .filter(AnalysisJob.status == "queued")
            .order_by(AnalysisJob.enqueued_at.asc(), AnalysisJob.id.asc())
            .with_for_update(skip_locked=True)
            .first()
        )
        if row is None:
            return None
        row.status = "running"
        row.started_at = datetime.utcnow()
        row.worker_host = socket.gethostname()[:120]
        db.commit()
        return row

    # SQLite / その他: conditional UPDATE 方式 (READ COMMITTED 相当の扱い)
    candidate = (
        db.query(AnalysisJob.id)
        .filter(AnalysisJob.status == "queued")
        .order_by(AnalysisJob.enqueued_at.asc(), AnalysisJob.id.asc())
        .first()
    )
    if candidate is None:
        return None
    job_id = candidate[0]
    affected = (
        db.query(AnalysisJob)
        .filter(AnalysisJob.id == job_id, AnalysisJob.status == "queued")
        .update(
            {
                AnalysisJob.status: "running",
                AnalysisJob.started_at: datetime.utcnow(),
                AnalysisJob.worker_host: socket.gethostname()[:120],
            },
            synchronize_session=False,
        )
    )
    db.commit()
    if affected == 0:
        return None
    return db.get(AnalysisJob, job_id)


# stale reaper 用閾値: started_at から N 秒経過したまま running の job は
# プロセス Kill 等で取り残された可能性が高いので failed に戻す。
# 通常の動画解析でも 30 分以上かかる事例があるため余裕を見て 2h。
_STALE_JOB_TIMEOUT_SEC = 7200


def reap_stale_jobs(db: Session) -> int:
    """started_at が _STALE_JOB_TIMEOUT_SEC を超えて running の job を failed に戻す。

    プロセス Kill/SIGTERM 黙殺で `running` 行が永久残留すると per-match dedup
    (routers/pipeline.py) が 409 で永久ブロックする。worker / API 起動時に呼ぶ。
    """
    threshold = datetime.utcnow() - timedelta(seconds=_STALE_JOB_TIMEOUT_SEC)
    affected = (
        db.query(AnalysisJob)
        .filter(
            AnalysisJob.status == "running",
            AnalysisJob.started_at != None,  # noqa: E711
            AnalysisJob.started_at < threshold,
        )
        .update(
            {
                AnalysisJob.status: "failed",
                AnalysisJob.finished_at: datetime.utcnow(),
            },
            synchronize_session=False,
        )
    )
    db.commit()
    if affected:
        logger.warning("reaped %d stale running jobs (threshold=%ds)", affected, _STALE_JOB_TIMEOUT_SEC)
    return affected


async def _run_once() -> bool:
    """キューから 1 件処理する。処理したら True。"""
    # インポートはランナー起動後に遅延（テスト環境での DB 差し替えに追従）
    from backend.db.database import SessionLocal
    from backend.pipeline.video_pipeline import execute_job

    loop = asyncio.get_running_loop()

    def _work() -> bool:
        db = SessionLocal()
        try:
            job = _claim_next(db)
            if job is None:
                return False
            execute_job(db, job)
            db.commit()
            return True
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    return await loop.run_in_executor(None, _work)


async def _runner_loop() -> None:
    logger.info("analysis job runner started")
    try:
        while True:
            try:
                did = await _run_once()
            except Exception as exc:  # pragma: no cover
                logger.exception("job runner error: %s", exc)
                did = False
            if not did:
                await asyncio.sleep(_POLL_INTERVAL_SEC)
    except asyncio.CancelledError:
        logger.info("analysis job runner cancelled")
        raise


def start_job_runner() -> Optional[asyncio.Task]:
    """ジョブランナーを起動する（冪等）。

    event loop が無い環境では何もしない（テストや CLI 呼び出しを想定）。
    """
    # SS_WORKER_STANDALONE=1 の場合、ワーカーは別プロセス (backend.pipeline.worker) で
    # 実行されるため、FastAPI プロセス内での in-process runner は起動しない。
    if os.getenv("SS_WORKER_STANDALONE") == "1":
        logger.info("standalone mode → in-process runner skip")
        return None
    # worker.lock が存在する = 別プロセスの standalone worker が走っている。
    # rereview NEW-C fix: 旧コードは Path.exists() のみ確認し、kill -9 された worker
    # の stale lock が残っていると in-process runner も拒否する dual-deadlock に
    # 陥っていた。`_FileLock.is_pid_alive` で記録 PID を生存確認し、死んでいたら
    # lock ファイル自体を削除して in-process runner 起動を継続する。
    try:
        from pathlib import Path
        from backend.pipeline.worker import _FileLock
        lock_path = Path(__file__).resolve().parent.parent / "data" / "worker.lock"
        if lock_path.exists():
            if _FileLock.is_pid_alive(str(lock_path)):
                logger.warning(
                    "in-process runner skip: %s held by live PID (standalone worker)",
                    lock_path,
                )
                return None
            else:
                logger.warning(
                    "in-process runner: %s is stale (no live PID) - removing and continuing",
                    lock_path,
                )
                try:
                    lock_path.unlink()
                except Exception:
                    pass
    except Exception:  # pragma: no cover
        pass
    global _RUNNER_TASK
    if _RUNNER_TASK is not None and not _RUNNER_TASK.done():
        return _RUNNER_TASK
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        return None
    if not loop.is_running():
        # ループ未稼働（CLI 等）: 呼び出し側で明示的に await 可能
        return None
    _RUNNER_TASK = loop.create_task(_runner_loop())
    return _RUNNER_TASK


async def drain_for_tests(max_iterations: int = 20) -> int:
    """テスト用: キューが空になるまで同期的に処理する。"""
    processed = 0
    for _ in range(max_iterations):
        did = await _run_once()
        if not did:
            break
        processed += 1
    return processed
