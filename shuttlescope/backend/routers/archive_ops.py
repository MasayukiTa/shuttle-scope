"""動画アーカイブ操作 API (/api/archive/*)

24h 経過 DL 動画を SS_LIVE_ARCHIVE_ROOT/downloads/ に移すバッチを管理する admin API。

エンドポイント:
  GET  /api/archive/status   — archive_root の存在/設定状態と videos 配下の集計
  POST /api/archive/scan     — 即時スキャン (テスト/緊急用、通常は 30 分間隔の常駐ループで動く)
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Request

from backend.services.downloads_archiver import (
    ARCHIVE_AGE_SECONDS,
    SCAN_INTERVAL_SECONDS,
    VIDEO_EXTS,
    _archive_root,
    _videos_dir,
    scan_once,
)
from backend.utils.auth import require_admin

router = APIRouter(prefix="/archive", tags=["archive"])


@router.get("/status")
def archive_status(request: Request):
    """設定 + 現状を返す (admin のみ)。"""
    require_admin(request)
    root = _archive_root()
    videos = _videos_dir()
    pending_old = pending_recent = total = total_bytes = 0
    if videos.exists():
        import time as _t
        now = _t.time()
        for entry in videos.iterdir():
            if not entry.is_file() or entry.suffix.lower() not in VIDEO_EXTS:
                continue
            try:
                st = entry.stat()
            except OSError:
                continue
            total += 1
            total_bytes += st.st_size
            if (now - st.st_mtime) >= ARCHIVE_AGE_SECONDS:
                pending_old += 1
            else:
                pending_recent += 1

    archive_exists = bool(root and Path(root).exists())
    return {
        "archive_root": str(root) if root else None,
        "archive_root_exists": archive_exists,
        "scan_interval_seconds": SCAN_INTERVAL_SECONDS,
        "archive_age_seconds": ARCHIVE_AGE_SECONDS,
        "videos_dir": str(videos),
        "videos_total": total,
        "videos_total_bytes": total_bytes,
        "videos_pending_archive": pending_old,
        "videos_recent": pending_recent,
    }


@router.post("/scan")
def archive_scan_now(request: Request):
    """即時スキャン (admin のみ)。常駐ループとは独立に 1 回実行する。"""
    require_admin(request)
    return scan_once()
