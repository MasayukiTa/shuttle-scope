"""DL 動画 24h 経過後アーカイブ。

設計:
  - `./videos/` 配下の mp4 / mkv / webm / mov を mtime ベースで判定
  - 24h 以上経過したファイルを `SS_LIVE_ARCHIVE_ROOT/downloads/{YYYY}/{MM}/m{match_id}_{filename}` へ移動
  - 移動成功時、DB の Match.video_local_path を `localfile:///{archive_path}` に書き換え
  - SS_LIVE_ARCHIVE_ROOT 未設定 / 不在ならスキップ
  - path_jail.allowed_video_roots() に SS_LIVE_ARCHIVE_ROOT が含まれているため、
    アーカイブ後も assert_allowed_video_path / アノテーション動画ストリームは通る
  - 30 分間隔で実行（lifespan の asyncio task）

ファイル名規約:
  m{match_id}_{original_filename}     match 紐付け済み
  orphan_{original_filename}          紐付けなし（DL 直後で match_id 取得前など）
  → どちらも一覧で人間が grep / explorer で識別可能
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 24h
ARCHIVE_AGE_SECONDS = 24 * 60 * 60
# 30 分ごとに走査
SCAN_INTERVAL_SECONDS = 30 * 60
# 対象拡張子（小文字比較）
VIDEO_EXTS = {".mp4", ".mkv", ".webm", ".mov", ".m4v"}


def _videos_dir() -> Path:
    return Path(os.path.abspath("./videos"))


def _archive_root() -> Optional[Path]:
    try:
        from backend.config import settings
        val = (getattr(settings, "ss_live_archive_root", "") or "").strip()
    except Exception:
        val = os.environ.get("SS_LIVE_ARCHIVE_ROOT", "").strip()
    if not val:
        return None
    p = Path(val)
    return p


def _path_to_localfile_url(path: Path) -> str:
    """Windows パスを localfile:///C:/... 形式に変換（既存 yt_live_recorder と互換）。"""
    s = str(path).replace("\\", "/")
    return f"localfile:///{s}"


def _server_url(filename: str) -> str:
    return f"server://{filename}"


def _find_match_for_file(filename: str) -> Optional[int]:
    """./videos/{filename} を参照する Match を 1 件返す。"""
    try:
        from backend.db.database import SessionLocal
        from backend.db.models import Match
    except Exception:
        return None
    server_url = _server_url(filename)
    abs_url = _path_to_localfile_url(_videos_dir() / filename)
    with SessionLocal() as db:
        row = (
            db.query(Match.id)
            .filter(Match.video_local_path.in_([server_url, abs_url, str(_videos_dir() / filename)]))
            .first()
        )
        return int(row[0]) if row else None


def _update_match_path(filename: str, new_path: Path) -> int:
    """./videos/{filename} 参照を localfile:///{new_path} に書き換え。返り値=更新行数。"""
    try:
        from backend.db.database import SessionLocal
        from backend.db.models import Match
    except Exception:
        return 0
    server_url = _server_url(filename)
    abs_url = _path_to_localfile_url(_videos_dir() / filename)
    raw_str = str(_videos_dir() / filename)
    new_url = _path_to_localfile_url(new_path)
    with SessionLocal() as db:
        n = (
            db.query(Match)
            .filter(Match.video_local_path.in_([server_url, abs_url, raw_str]))
            .update({"video_local_path": new_url}, synchronize_session=False)
        )
        db.commit()
        return int(n)


def _archive_one(src: Path, archive_root: Path) -> bool:
    """1 ファイルをアーカイブへ移動 + DB 更新。成功 True。"""
    from backend.utils.path_jail import resolve_within  # noqa: WPS433

    filename = src.name
    match_id = _find_match_for_file(filename)
    prefix = f"m{match_id}_" if match_id is not None else "orphan_"

    now = datetime.now()
    dest_dir = archive_root / "downloads" / f"{now.year:04d}" / f"{now.month:02d}"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{prefix}{filename}"

    try:
        resolve_within(dest, archive_root)
    except ValueError as exc:
        logger.error("[dl_archive] path_jail block: %s", exc)
        return False

    # 既存ファイルとの衝突回避
    if dest.exists():
        base, ext = os.path.splitext(dest.name)
        i = 1
        while True:
            candidate = dest.with_name(f"{base}_{i}{ext}")
            if not candidate.exists():
                dest = candidate
                break
            i += 1

    try:
        shutil.move(str(src), str(dest))
    except Exception as exc:
        logger.error("[dl_archive] move failed: %s → %s : %s", src, dest, exc)
        return False

    try:
        n = _update_match_path(filename, dest)
        if n:
            logger.info("[dl_archive] %s → %s (match rows updated: %d)", filename, dest, n)
        else:
            logger.info("[dl_archive] %s → %s (no match link)", filename, dest)
    except Exception as exc:
        logger.error("[dl_archive] DB update failed (file already moved): %s", exc)

    return True


def scan_once() -> dict:
    """1 回スキャンして 24h 超のファイルをアーカイブへ移動。

    返り値: {"scanned": N, "moved": M, "skipped": S, "errors": E, "archive_root": "..."}
    """
    root = _archive_root()
    if root is None:
        return {"scanned": 0, "moved": 0, "skipped": 0, "errors": 0, "archive_root": None}
    if not root.exists():
        logger.warning("[dl_archive] archive root does not exist: %s — 外付けドライブ未接続の可能性", root)
        return {"scanned": 0, "moved": 0, "skipped": 0, "errors": 0, "archive_root": str(root), "missing_root": True}

    videos = _videos_dir()
    if not videos.exists():
        return {"scanned": 0, "moved": 0, "skipped": 0, "errors": 0, "archive_root": str(root)}

    now_ts = datetime.now().timestamp()
    scanned = moved = skipped = errors = 0

    for entry in videos.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in VIDEO_EXTS:
            continue
        scanned += 1
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            errors += 1
            continue
        if (now_ts - mtime) < ARCHIVE_AGE_SECONDS:
            skipped += 1
            continue
        ok = _archive_one(entry, root)
        if ok:
            moved += 1
        else:
            errors += 1

    return {
        "scanned": scanned, "moved": moved, "skipped": skipped, "errors": errors,
        "archive_root": str(root),
    }


async def archive_loop() -> None:
    """30 分ごとに scan_once を呼ぶ常駐ループ（lifespan で起動）。"""
    logger.info("[dl_archive] loop started (interval=%ds, age=%ds)", SCAN_INTERVAL_SECONDS, ARCHIVE_AGE_SECONDS)
    while True:
        try:
            result = await asyncio.get_event_loop().run_in_executor(None, scan_once)
            if result.get("moved") or result.get("errors"):
                logger.info("[dl_archive] scan: %s", result)
            else:
                logger.debug("[dl_archive] scan: %s", result)
        except asyncio.CancelledError:
            logger.info("[dl_archive] loop cancelled")
            raise
        except Exception as exc:
            logger.exception("[dl_archive] loop error: %s", exc)
        try:
            await asyncio.sleep(SCAN_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise
