"""ベンチマーク API ルーター。

エンドポイント:
  GET  /v1/benchmark/devices   — 利用可能デバイス一覧
  POST /v1/benchmark/run       — ベンチマーク実行（非同期ジョブ）
  GET  /v1/benchmark/jobs/{job_id} — ジョブ状態照会

app への登録は backend/main.py で prefix="/api" として行う。
最終 URL: /api/v1/benchmark/...
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from backend.benchmark.devices import probe_all, ComputeDevice
from backend.benchmark.jobs import BenchmarkJob, create_job, get_job, run_job_async, cancel_job

logger = logging.getLogger(__name__)

# router prefix は /v1/benchmark とし、app 側で /api を付与する
router = APIRouter(prefix="/v1/benchmark", tags=["benchmark"])


# ─── スキーマ定義 ──────────────────────────────────────────────────────────────

class DeviceSpecsSchema(BaseModel):
    """デバイス仕様の詳細情報"""
    name: str
    cores: Optional[int] = None
    vram_mb: Optional[int] = None
    driver: Optional[str] = None
    compute_capability: Optional[str] = None


class DeviceSchema(BaseModel):
    """デバイス情報レスポンス"""
    device_id: str
    label: str
    device_type: str
    backend: str
    available: bool
    specs: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_compute_device(cls, d: ComputeDevice) -> "DeviceSchema":
        return cls(
            device_id=d.device_id,
            label=d.label,
            device_type=d.device_type,
            backend=d.backend,
            available=d.available,
            specs=d.specs,
        )


class RunRequest(BaseModel):
    """POST /v1/benchmark/run のリクエストボディ"""
    device_ids: List[str] = Field(..., min_length=1, description="計測対象デバイス ID リスト")
    targets: List[str] = Field(..., min_length=1, description="計測対象ターゲット名リスト")
    n_frames: int = Field(default=30, ge=1, le=500, description="1 ターゲットあたりのフレーム数")


class RunResponse(BaseModel):
    """POST /v1/benchmark/run のレスポンス"""
    job_id: str


class JobResponse(BaseModel):
    """GET /v1/benchmark/jobs/{job_id} のレスポンス"""
    job_id: str
    status: str
    progress: float
    results: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None

    @classmethod
    def from_job(cls, job: BenchmarkJob) -> "JobResponse":
        return cls(
            job_id=job.job_id,
            status=job.status,
            progress=job.progress,
            results=job.results,
            error=job.error,
        )


# ─── エンドポイント ────────────────────────────────────────────────────────────

@router.get("/devices", response_model=List[DeviceSchema])
async def get_devices(request: Request) -> List[DeviceSchema]:
    """利用可能な計算デバイス一覧を返す（TTL 60秒キャッシュ）。
    GPU/CPU モデル名・ドライババージョン・VRAM を含むため admin 限定。
    """
    from backend.utils.auth import require_admin
    require_admin(request)
    devices = probe_all()
    return [DeviceSchema.from_compute_device(d) for d in devices]


@router.post("/run", response_model=RunResponse, status_code=202)
async def run_benchmark(req: RunRequest) -> RunResponse:
    """ベンチマークジョブを作成してバックグラウンド実行を開始する。
    job_id を即座に返すため UI はブロックされない。
    """
    job = create_job(
        device_ids=req.device_ids,
        targets=req.targets,
        n_frames=req.n_frames,
    )

    # ランナー関数を定義（ジョブ情報を使って BenchmarkRunner.run_all を呼ぶ）
    def runner_fn(j: BenchmarkJob) -> Dict[str, Any]:
        from backend.benchmark.runner import BenchmarkRunner
        from backend.benchmark.devices import probe_all as _probe

        all_devices = _probe()
        bench = BenchmarkRunner()
        results = bench.run_all(
            job_id=j.job_id,
            device_ids=j.device_ids,
            targets=j.targets,
            n_frames=j.n_frames,
            devices=all_devices,
            job=j,
        )
        # runner の進捗をジョブに同期する
        j.progress = bench.get_progress(j.job_id)
        return results

    await run_job_async(job, runner_fn)

    logger.info("[benchmark] ジョブ開始: job_id=%s", job.job_id)
    return RunResponse(job_id=job.job_id)


@router.get("/jobs/{job_id}", response_model=JobResponse)
async def get_job_status(job_id: str) -> JobResponse:
    """ジョブの現在状態（status / progress / results）を返す。"""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"job_id={job_id} が見つかりません")
    return JobResponse.from_job(job)


@router.delete("/jobs/{job_id}", status_code=200)
async def cancel_benchmark(job_id: str) -> dict:
    """実行中のベンチマークジョブをキャンセルする。"""
    ok = cancel_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"job_id={job_id} が見つかりません")
    return {"success": True, "job_id": job_id}
