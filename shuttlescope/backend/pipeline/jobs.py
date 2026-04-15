"""解析ジョブランナー。

AnalysisJob を 1 件ずつ asyncio タスクで処理する（GPU 競合回避）。
start_job_runner() は冪等（多重起動防止）。
"""
from __future__ import annotations

import asyncio
import logging
import os
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
    """queued 状態の最古ジョブを 1 件取得する。"""
    return (
        db.query(AnalysisJob)
        .filter(AnalysisJob.status == "queued")
        .order_by(AnalysisJob.enqueued_at.asc(), AnalysisJob.id.asc())
        .first()
    )


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
