"""
backup_service.py — ローカル DB の安全コピー（ZIP / ローテーション管理）

仕様書 §12.4 に基づく。
"""
from __future__ import annotations

import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.config import settings

# バックアップ保存先（設定で上書き可）
_DEFAULT_BACKUP_DIR = Path(settings.DATABASE_URL.replace("sqlite:///", "")).parent / "backups"


def get_backup_dir() -> Path:
    d = _DEFAULT_BACKUP_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def create_backup(label: Optional[str] = None, max_generations: int = 10) -> Path:
    """
    現行 SQLite DB を ZIP に固めてバックアップ。

    Returns:
        作成したバックアップ ZIP のパス
    """
    db_path = Path(settings.DATABASE_URL.replace("sqlite:///", ""))
    if not db_path.exists():
        raise FileNotFoundError(f"DB ファイルが見つかりません: {db_path}")

    backup_dir = get_backup_dir()
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{label}" if label else ""
    zip_name = f"backup_{ts}{suffix}.zip"
    zip_path = backup_dir / zip_name

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(db_path, db_path.name)

    # 古い世代を削除
    _rotate_backups(backup_dir, max_generations)

    return zip_path


def list_backups() -> list[dict]:
    """バックアップ一覧を新しい順で返す"""
    backup_dir = get_backup_dir()
    result = []
    for f in sorted(backup_dir.glob("backup_*.zip"), reverse=True):
        stat = f.stat()
        result.append({
            "filename": f.name,
            "path": str(f),
            "size_bytes": stat.st_size,
            "created_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
        })
    return result


def _rotate_backups(backup_dir: Path, max_generations: int) -> None:
    files = sorted(backup_dir.glob("backup_*.zip"))
    while len(files) > max_generations:
        files[0].unlink(missing_ok=True)
        files = files[1:]
