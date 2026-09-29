"""ベンチマークジョブ管理モジュール（インメモリ、DB 不要）。

BenchmarkJob はインメモリ dict で管理する。起動後リセットで問題なし。
create_job / get_job / run_job_async が公開 API。
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, Literal, Optional

logger = logging.getLogger(__name__)

# ジョブステータス型
JobStatus = Literal["pending", "running", "done", "failed"]

# インメモリジョブストア
_jobs: Dict[str, "BenchmarkJob"] = {}


@dataclass
class BenchmarkJob:
    """ベンチマーク実行ジョブ 1 件。"""

    job_id: str
    device_ids: list[str]
    targets: list[str]
    n_frames: int
    status: JobStatus = "pending"
    progress: float = 0.0           # 0.0〜1.0
    results: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    cancelled: bool = False


def create_job(device_ids: list[str], targets: list[str], n_frames: int) -> BenchmarkJob:
    """新しいジョブを生成してストアに登録し、返す。"""
    job_id = str(uuid.uuid4())
    job = BenchmarkJob(
        job_id=job_id,
        device_ids=device_ids,
        targets=targets,
        n_frames=n_frames,
    )
    _jobs[job_id] = job
    logger.info("[jobs] ジョブ作成: job_id=%s devices=%s targets=%s n_frames=%d",
                job_id, device_ids, targets, n_frames)
    return job


def get_job(job_id: str) -> Optional[BenchmarkJob]:
    """job_id に対応するジョブを返す。存在しない場合は None。"""
    return _jobs.get(job_id)


def cancel_job(job_id: str) -> bool:
    """ジョブにキャンセルフラグを立てる。ジョブが存在すれば True を返す。"""
    job = _jobs.get(job_id)
    if job is None:
        return False
    job.cancelled = True
    if job.status in ("pending", "running"):
        job.status = "failed"
        job.error = "キャンセルされました"
    logger.info("[jobs] ジョブキャンセル: job_id=%s", job_id)
    return True


def _sync_runner(job: BenchmarkJob, runner_fn: Callable[..., Dict[str, Any]]) -> None:
    """同期的にランナーを実行してジョブを更新する（スレッドプール用）。"""
    job.status = "running"
    try:
        results = runner_fn(job)
        job.results = results
        job.progress = 1.0
        job.status = "done"
        logger.info("[jobs] ジョブ完了: job_id=%s", job.job_id)
    except Exception as exc:
        job.error = str(exc)
        job.status = "failed"
        logger.exception("[jobs] ジョブ失敗: job_id=%s", job.job_id)


async def run_job_async(
    job: BenchmarkJob,
    runner_fn: Callable[..., Dict[str, Any]],
) -> None:
    """asyncio.create_task でジョブをバックグラウンド実行する。

    runner_fn は同期関数として扱い、run_in_executor でスレッドプールに委譲する。
    イベントループをブロックしない。
    """
    loop = asyncio.get_event_loop()

    async def _task() -> None:
        await loop.run_in_executor(None, _sync_runner, job, runner_fn)

    asyncio.create_task(_task())
    logger.info("[jobs] バックグラウンドタスク開始: job_id=%s", job.job_id)
