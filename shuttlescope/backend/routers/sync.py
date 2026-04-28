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

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.services.export_package import (
    export_match, export_player, export_change_set, validate_package,
    export_conditions_only,
)
from backend.services.import_package import import_package
from backend.services.backup_service import create_backup, list_backups
from backend.routers.settings import _load_all as _load_settings
import shutil
from pathlib import Path

import logging
logger = logging.getLogger(__name__)

def _sanitize_errors(errors):
    """Stack-trace-exposure 防止: summary.errors 内の例外文字列を除去し、件数のみ返す。"""
    if not errors:
        return []
    for e in errors:
        logger.warning("import error (sanitized): %s", e)
    return [f"{len(errors)} 件の内部エラーが発生しました"]


from backend.db.models import SyncConflict, Match
from backend.utils.auth import (
    get_auth,
    require_analyst,
    check_export_match_scope,
    check_export_player_scope,
)
from pydantic import BaseModel as _BaseModel

router = APIRouter(prefix="/sync", tags=["sync"])


# ─── エクスポート ──────────────────────────────────────────────────────────────

def _get_device_id(db: Session, override: Optional[str]) -> str:
    """設定から device_id を取得。override が渡された場合はそちらを優先。"""
    if override:
        return override
    settings = _load_settings(db)
    return settings.get("sync_device_id") or "unknown"


@router.get("/export/match")
def export_match_endpoint(
    request: Request,
    match_ids: str = Query(..., description="カンマ区切りの試合ID"),
    device_id: Optional[str] = Query(None),
    since: Optional[str] = Query(None, description="YYYY-MM-DD コンディション開始日"),
    until: Optional[str] = Query(None, description="YYYY-MM-DD コンディション終了日"),
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

    ctx = get_auth(request)
    matches = db.query(Match).filter(Match.id.in_(ids)).all()
    if len(matches) != len(ids):
        found = {m.id for m in matches}
        missing = [i for i in ids if i not in found]
        raise HTTPException(status_code=404, detail=f"試合が見つかりません: {missing}")
    check_export_match_scope(ctx, matches, db)

    try:
        pkg_bytes = export_match(
            db, ids, device_id=_get_device_id(db, device_id), since=since, until=until,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.warning("sync export failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="エクスポート処理に失敗しました")

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
    request: Request,
    device_id: Optional[str] = Query(None),
    since: Optional[str] = Query(None, description="YYYY-MM-DD 試合/コンディション開始日"),
    until: Optional[str] = Query(None, description="YYYY-MM-DD 試合/コンディション終了日"),
    db: Session = Depends(get_db),
):
    """対象選手の全試合 + 期間内コンディションを .sspkg としてダウンロード"""
    ctx = get_auth(request)
    check_export_player_scope(ctx, player_id, db)
    try:
        pkg_bytes = export_player(
            db, player_id, device_id=_get_device_id(db, device_id),
            since=since, until=until,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.warning("sync export failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="エクスポート処理に失敗しました")

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"shuttlescope_player{player_id}_{ts}.sspkg"
    return Response(
        content=pkg_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/conditions")
def export_conditions_endpoint(
    request: Request,
    player_ids: str = Query(..., description="カンマ区切りの選手ID"),
    since: Optional[str] = Query(None),
    until: Optional[str] = Query(None),
    device_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """選手 × 期間の Condition/ConditionTag のみをパッケージ化。
    権限: player=自分のみ / coach=自チーム所属のみ / analyst=無制限。
    """
    try:
        ids = [int(x.strip()) for x in player_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="player_ids は整数のカンマ区切り")
    if not ids:
        raise HTTPException(status_code=400, detail="player_ids が空です")

    ctx = get_auth(request)
    for pid in ids:
        check_export_player_scope(ctx, pid, db)

    try:
        pkg_bytes = export_conditions_only(
            db, ids, device_id=_get_device_id(db, device_id),
            since=since, until=until,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.warning("sync export failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="エクスポート処理に失敗しました")

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"shuttlescope_conditions_{ts}.sspkg"
    return Response(
        content=pkg_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export/change_set")
def export_change_set_endpoint(
    since: str = Query(..., description="ISO 8601 日時文字列 (例: 2026-04-01T00:00:00)"),
    device_id: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _ctx=Depends(require_analyst),
):
    """since 以降に更新されたレコードをまとめて .sspkg としてダウンロード (analyst 限定)"""
    try:
        pkg_bytes = export_change_set(db, since, device_id=_get_device_id(db, device_id))
    except Exception as e:
        logger.warning("sync export failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="エクスポート処理に失敗しました")

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"shuttlescope_changeset_{ts}.sspkg"
    return Response(
        content=pkg_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── インポート ────────────────────────────────────────────────────────────────

_MAX_IMPORT_BYTES = 50 * 1024 * 1024   # 50 MB — ZIP 爆弾 / メモリ枯渇防止


@router.post("/preview")
async def preview_package(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _ctx=Depends(require_analyst),
):
    """
    パッケージの内容をプレビュー（DB 変更なし）。
    追加件数・更新件数・競合件数を返す。
    """
    raw = await file.read(_MAX_IMPORT_BYTES + 1)
    if len(raw) > _MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail=f"ファイルサイズが上限（{_MAX_IMPORT_BYTES // 1024 // 1024} MB）を超えています")

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
            "errors": _sanitize_errors(summary.errors),
        },
    }


@router.post("/import")
async def import_package_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _ctx=Depends(require_analyst),
):
    """
    .sspkg パッケージをインポートして DB へマージ。
    """
    raw = await file.read(_MAX_IMPORT_BYTES + 1)
    if len(raw) > _MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail=f"ファイルサイズが上限（{_MAX_IMPORT_BYTES // 1024 // 1024} MB）を超えています")

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
            "errors": _sanitize_errors(summary.errors),
        },
    }


# ─── バックアップ ──────────────────────────────────────────────────────────────

@router.post("/backup")
def backup_now(
    label: Optional[str] = Query(None),
    _ctx=Depends(require_analyst),
):
    """現行 DB をバックアップ ZIP として保存 (analyst 限定)"""
    try:
        path = create_backup(label=label)
        return {
            "success": True,
            "data": {"path": str(path), "filename": path.name},
        }
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except NotImplementedError as e:
        # PostgreSQL 環境では SQLite ベースのバックアップは不可
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"バックアップエラー: {e}")


@router.get("/backups")
def get_backups(_ctx=Depends(require_analyst)):
    """バックアップ一覧を返す (analyst 限定)"""
    return {"success": True, "data": list_backups()}


# ─── クラウドフォルダ連携 ──────────────────────────────────────────────────────

@router.get("/cloud/packages")
def list_cloud_packages(db: Session = Depends(get_db), _ctx=Depends(require_analyst)):
    """
    設定済みの sync_folder_path から .sspkg ファイル一覧を返す。
    OneDrive / SharePoint 等の共有フォルダに置いたパッケージの候補表示に使用。
    """
    settings = _load_settings(db)
    folder = settings.get("sync_folder_path", "")
    if not folder:
        return {"success": True, "data": [], "folder": "", "configured": False}

    folder_path = Path(folder)
    if not folder_path.exists() or not folder_path.is_dir():
        return {"success": True, "data": [], "folder": folder, "configured": True, "error": "フォルダが見つかりません"}

    packages = []
    for f in sorted(folder_path.glob("*.sspkg"), reverse=True):
        stat = f.stat()
        packages.append({
            "filename": f.name,
            "path": str(f),
            "size_bytes": stat.st_size,
            "modified_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
        })

    return {"success": True, "data": packages, "folder": folder, "configured": True}


@router.post("/cloud/copy")
async def copy_to_cloud(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _ctx=Depends(require_analyst),
):
    """
    クライアントがアップロードした .sspkg を sync_folder_path へコピーする。
    エクスポート後の自動コピーに使用。
    """
    settings = _load_settings(db)
    folder = settings.get("sync_folder_path", "")
    if not folder:
        raise HTTPException(status_code=400, detail="sync_folder_path が設定されていません")

    folder_path = Path(folder)
    if not folder_path.exists():
        try:
            folder_path.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"フォルダ作成エラー: {e}")

    # Path traversal 防止: ファイル名からディレクトリ成分を除去し .sspkg のみ許可
    safe_name = Path(file.filename or "").name
    if not safe_name.endswith(".sspkg"):
        raise HTTPException(status_code=400, detail=".sspkg ファイルのみコピーできます")
    dest = folder_path / safe_name
    raw = await file.read(_MAX_IMPORT_BYTES + 1)
    if len(raw) > _MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail=f"ファイルサイズが上限（{_MAX_IMPORT_BYTES // 1024 // 1024} MB）を超えています")
    dest.write_bytes(raw)

    return {"success": True, "data": {"path": str(dest), "filename": file.filename}}


@router.post("/cloud/import_from_path")
def import_from_cloud_path(
    path: str = Query(..., description="クラウドフォルダ内の .sspkg フルパス"),
    dry_run: bool = Query(False),
    db: Session = Depends(get_db),
    _ctx=Depends(require_analyst),
):
    """
    sync_folder_path 内の指定 .sspkg ファイルを直接インポート。
    dry_run=True の場合はプレビューのみ。
    """
    # Path-injection 防止: 同期フォルダを基準に結合 → resolve → 基準配下チェックを優先
    settings_cfg = _load_settings(db)
    sync_folder = settings_cfg.get("sync_folder_path", "")
    if not sync_folder:
        raise HTTPException(status_code=400, detail="同期フォルダが設定されていません")
    sync_root = Path(sync_folder).resolve()
    raw_path = Path(path)
    pkg_path = (raw_path if raw_path.is_absolute() else (sync_root / raw_path)).resolve()
    try:
        pkg_path.relative_to(sync_root)
    except ValueError:
        raise HTTPException(status_code=403, detail="指定パスは同期フォルダ外です")

    # 拡張子を .sspkg に限定
    if pkg_path.suffix.lower() != ".sspkg":
        raise HTTPException(status_code=400, detail=".sspkg ファイルのみ指定できます")

    if not pkg_path.exists() or not pkg_path.is_file():
        raise HTTPException(status_code=404, detail="ファイルが見つかりません")

    raw = pkg_path.read_bytes()
    if len(raw) > _MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail=f"ファイルサイズが上限（{_MAX_IMPORT_BYTES // 1024 // 1024} MB）を超えています")
    validation = validate_package(raw)
    if not validation["valid"]:
        raise HTTPException(status_code=422, detail=validation["error"])

    summary = import_package(db, raw, dry_run=dry_run)
    return {
        "success": True,
        "data": {
            "dry_run": dry_run,
            "added": summary.added,
            "updated": summary.updated,
            "kept": summary.kept,
            "deleted": summary.deleted,
            "conflicts": summary.conflicts,
            "conflict_log": summary.conflict_log,
            "errors": _sanitize_errors(summary.errors),
        },
    }


# ─── パッケージ検証のみ ────────────────────────────────────────────────────────

@router.post("/validate")
async def validate_only(file: UploadFile = File(...), _ctx=Depends(require_analyst)):
    """DB を変更せずパッケージの整合性のみ検証"""
    raw = await file.read(_MAX_IMPORT_BYTES + 1)
    if len(raw) > _MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail=f"ファイルサイズが上限（{_MAX_IMPORT_BYTES // 1024 // 1024} MB）を超えています")
    result = validate_package(raw)
    # Stack-trace-exposure 防止: 例外文字列 (error) を汎用化
    if isinstance(result, dict) and not result.get("valid") and "error" in result:
        logger.warning("package validation failed (sanitized): %s", result.get("error"))
        result = {**result, "error": "パッケージ検証に失敗しました"}
    return {"success": result["valid"], "data": result}


# ─── 競合レビュー ──────────────────────────────────────────────────────────────

class ConflictResolveBody(_BaseModel):
    resolution: str  # "keep_local" | "use_incoming"


@router.get("/conflicts")
def list_conflicts(db: Session = Depends(get_db), _ctx=Depends(require_analyst)):
    """未解決の競合レコード一覧を返す。
    incoming_snapshot に他チーム/他選手のレコードが含まれ得るため analyst/admin のみ。
    """
    conflicts = (
        db.query(SyncConflict)
        .filter(SyncConflict.resolution.is_(None))
        .order_by(SyncConflict.created_at.desc())
        .all()
    )
    return {
        "success": True,
        "data": [
            {
                "id": c.id,
                "record_table": c.record_table,
                "record_uuid": c.record_uuid,
                "import_device": c.import_device,
                "import_updated_at": c.import_updated_at,
                "local_updated_at": c.local_updated_at,
                "reason": c.reason,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            }
            for c in conflicts
        ],
    }


@router.post("/conflicts/{conflict_id}/resolve")
def resolve_conflict(
    conflict_id: int,
    body: ConflictResolveBody,
    db: Session = Depends(get_db),
    _ctx=Depends(require_analyst),
):
    """
    競合を解決する (analyst/admin のみ)。

    resolution:
      - keep_local: ローカルレコードをそのまま維持
      - use_incoming: incoming スナップショットでローカルを上書き

    use_incoming は他者からの incoming 任意 JSON で対象テーブルの
    既存レコードを直接更新する経路を持つため、role を持たないユーザに
    開放すると Player/Match の任意改ざんに繋がる。analyst/admin に限定する。
    """
    conflict = db.get(SyncConflict, conflict_id)
    if not conflict:
        raise HTTPException(status_code=404, detail="競合が見つかりません")

    if body.resolution not in ("keep_local", "use_incoming"):
        raise HTTPException(status_code=400, detail="resolution は keep_local または use_incoming を指定してください")

    if body.resolution == "use_incoming" and conflict.incoming_snapshot:
        # incoming のスナップショットを対象テーブルに適用
        import json as _json
        from backend.services.import_package import _TABLE_MAP, _find_by_uuid, _get_columns, _remap_fks
        table_map = {k: v for k, v in _TABLE_MAP}
        model_cls = table_map.get(conflict.record_table)
        if model_cls:
            try:
                incoming = _json.loads(conflict.incoming_snapshot)
                local_obj = _find_by_uuid(db, model_cls, conflict.record_uuid)
                if local_obj:
                    valid_cols = _get_columns(model_cls)
                    data = {k: v for k, v in incoming.items() if k in valid_cols and k != "id"}
                    for k, v in data.items():
                        setattr(local_obj, k, v)
                    db.commit()
            except Exception as e:
                db.rollback()
                raise HTTPException(status_code=500, detail=f"適用エラー: {e}")

    conflict.resolution = body.resolution
    conflict.resolved_at = datetime.utcnow()
    db.commit()

    return {"success": True, "data": {"id": conflict_id, "resolution": body.resolution}}
