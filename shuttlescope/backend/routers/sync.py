"""
sync.py — データ同期 API ルーター

エンドポイント:
  GET  /api/sync/export/match?match_ids=1,2,3   → .sspkg ダウンロード
  GET  /api/sync/export/player/{player_id}      → .sspkg ダウンロード
  POST /api/sync/preview                        → パッケージ内容プレビュー（DB 変更なし）
  POST /api/sync/import                         → パッケージインポート実行
  POST /api/sync/backup                         → ローカル DB をバックアップ
  GET  /api/sync/backups                        → バックアップ一覧
  GET  /api/sync/validate                       → パッケージ検証のみ
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.services.export_package import export_match, export_player, validate_package
from backend.services.import_package import import_package
from backend.services.backup_service import create_backup, list_backups

router = APIRouter(prefix="/sync", tags=["sync"])


# ─── エクスポート ──────────────────────────────────────────────────────────────

@router.get("/export/match")
def export_match_endpoint(
    match_ids: str = Query(..., description="カンマ区切りの試合ID"),
    device_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """
    指定試合群を .sspkg としてダウンロード。
    例: /api/sync/export/match?match_ids=1,2,3
    """
    try:
        ids = [int(x.strip()) for x in match_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="match_ids は整数のカンマ区切りで指定してください")

    if not ids:
        raise HTTPException(status_code=400, detail="match_ids が空です")

    try:
        pkg_bytes = export_match(db, ids, device_id=device_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"エクスポートエラー: {e}")

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"shuttlescope_match_{ts}.sspkg"
    return Response(
        content=pkg_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/player/{player_id}")
def export_player_endpoint(
    player_id: int,
    device_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """対象選手の全試合を .sspkg としてダウンロード"""
    try:
        pkg_bytes = export_player(db, player_id, device_id=device_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"エクスポートエラー: {e}")

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"shuttlescope_player{player_id}_{ts}.sspkg"
    return Response(
        content=pkg_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── インポート ────────────────────────────────────────────────────────────────

@router.post("/preview")
async def preview_package(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    パッケージの内容をプレビュー（DB 変更なし）。
    追加件数・更新件数・競合件数を返す。
    """
    raw = await file.read()

    # 基本検証
    validation = validate_package(raw)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail=validation["error"])

    # dry_run でマージシミュレーション
    summary = import_package(db, raw, dry_run=True)

    return {
        "success": True,
        "data": {
            "manifest": validation.get("manifest"),
            "record_counts": validation.get("record_counts"),
            "merge_preview": {
                "added": summary.added,
                "updated": summary.updated,
                "kept": summary.kept,
                "deleted": summary.deleted,
                "conflicts": summary.conflicts,
                "conflict_log": summary.conflict_log,
            },
            "errors": summary.errors,
        },
    }


@router.post("/import")
async def import_package_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    .sspkg パッケージをインポートして DB へマージ。
    """
    raw = await file.read()

    validation = validate_package(raw)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail=validation["error"])

    summary = import_package(db, raw, dry_run=False)

    return {
        "success": True,
        "data": {
            "added": summary.added,
            "updated": summary.updated,
            "kept": summary.kept,
            "deleted": summary.deleted,
            "conflicts": summary.conflicts,
            "conflict_log": summary.conflict_log,
            "errors": summary.errors,
        },
    }


# ─── バックアップ ──────────────────────────────────────────────────────────────

@router.post("/backup")
def backup_now(label: Optional[str] = Query(None)):
    """現行 DB をバックアップ ZIP として保存"""
    try:
        path = create_backup(label=label)
        return {
            "success": True,
            "data": {"path": str(path), "filename": path.name},
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"バックアップエラー: {e}")


@router.get("/backups")
def get_backups():
    """バックアップ一覧を返す"""
    return {"success": True, "data": list_backups()}


# ─── パッケージ検証のみ ────────────────────────────────────────────────────────

@router.post("/validate")
async def validate_only(file: UploadFile = File(...)):
    """DB を変更せずパッケージの整合性のみ検証"""
    raw = await file.read()
    result = validate_package(raw)
    return {"success": result["valid"], "data": result}
