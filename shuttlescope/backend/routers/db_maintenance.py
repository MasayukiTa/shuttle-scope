"""DB メンテナンス API (/api/db/*)

エンドポイント:
  GET  /api/db/status            — DB ファイルサイズ・freelist・auto_vacuum 状態
  POST /api/db/maintenance       — WAL checkpoint + incremental vacuum（軽量メンテ）
  POST /api/db/set_auto_vacuum   — auto_vacuum モード変更（VACUUM も実行）
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from backend.db.database import get_db_stats, run_maintenance, set_auto_vacuum_mode
from backend.utils.auth import require_admin

router = APIRouter(prefix="/db", tags=["db-maintenance"])


@router.get("/status")
def db_status(request: Request):
    """SQLite DB の状態を返す (admin のみ)。"""
    require_admin(request)
    return get_db_stats()


@router.post("/maintenance")
def db_maintenance(request: Request):
    """WAL チェックポイントと incremental vacuum を実行する (admin のみ)。"""
    require_admin(request)
    return run_maintenance()


class SetAutoVacuumBody(BaseModel):
    mode: str  # "incremental" | "full" | "off"


@router.post("/set_auto_vacuum")
def db_set_auto_vacuum(body: SetAutoVacuumBody, request: Request):
    require_admin(request)
    """auto_vacuum モードを変更する。変更後に VACUUM を実行するため数秒かかる場合がある。"""
    mode_map = {"incremental": 2, "full": 1, "off": 0}
    if body.mode not in mode_map:
        raise HTTPException(status_code=400, detail=f"mode は incremental / full / off のいずれかを指定してください")
    result = set_auto_vacuum_mode(mode_map[body.mode])
    if not result.get("supported"):
        raise HTTPException(status_code=400, detail="SQLite 以外は対象外です")
    # Stack-trace-exposure 防止: 内部例外文字列を除去
    if isinstance(result, dict):
        for _k in ("error", "exception", "traceback"):
            result.pop(_k, None)
    return result
