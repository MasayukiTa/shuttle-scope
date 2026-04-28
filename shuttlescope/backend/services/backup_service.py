"""
backup_service.py — ローカル DB の安全コピー（AES-256 暗号化 ZIP / ローテーション管理）

Phase A2 セキュリティ強化:
  - pyzipper による AES-256 暗号化（パスフレーズ: SS_BACKUP_PASSPHRASE）
  - パスフレーズ未設定時は警告ログ + 平文 ZIP にフォールバック (本番禁止)
  - 復元時 (restore_backup) はパスフレーズ必須
  - SHA-256 ハッシュをファイル名に含めて改ざん検知補助
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from backend.config import settings

try:
    import pyzipper  # type: ignore
    _HAS_PYZIPPER = True
except ImportError:
    _HAS_PYZIPPER = False

logger = logging.getLogger(__name__)

_DEFAULT_BACKUP_DIR = Path(settings.DATABASE_URL.replace("sqlite:///", "")).parent / "backups"


def _passphrase() -> Optional[bytes]:
    """SS_BACKUP_PASSPHRASE を取得する。未設定なら None。"""
    val = (getattr(settings, "ss_backup_passphrase", "") or "").strip()
    if not val:
        val = (os.environ.get("SS_BACKUP_PASSPHRASE", "") or "").strip()
    return val.encode("utf-8") if val else None


def get_backup_dir() -> Path:
    d = _DEFAULT_BACKUP_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _file_sha256_short(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def create_backup(label: Optional[str] = None, max_generations: int = 10) -> Path:
    """SQLite DB を AES-256 暗号化 ZIP に固めてバックアップする。

    パスフレーズ未設定時は平文 ZIP にフォールバック（警告ログを必ず出す）。
    本番運用では SS_BACKUP_PASSPHRASE を必ず設定すること。
    """
    db_path = Path(settings.DATABASE_URL.replace("sqlite:///", ""))
    if not db_path.exists():
        raise FileNotFoundError(f"DB ファイルが見つかりません: {db_path}")

    backup_dir = get_backup_dir()
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{label}" if label else ""
    src_hash = _file_sha256_short(db_path)
    zip_name = f"backup_{ts}{suffix}_{src_hash}.zip"
    zip_path = backup_dir / zip_name

    passphrase = _passphrase()

    if passphrase and _HAS_PYZIPPER:
        # AES-256 暗号化 ZIP
        with pyzipper.AESZipFile(
            zip_path, "w",
            compression=pyzipper.ZIP_DEFLATED,
            encryption=pyzipper.WZ_AES,
        ) as zf:
            zf.setpassword(passphrase)
            zf.setencryption(pyzipper.WZ_AES, nbits=256)
            zf.write(db_path, db_path.name)
        logger.info("[backup] AES-256 暗号化 ZIP を作成: %s", zip_path.name)
    else:
        # フォールバック: 平文 ZIP（本番では使わないこと）
        if not passphrase:
            logger.warning(
                "[backup] SS_BACKUP_PASSPHRASE 未設定。平文 ZIP で作成します。"
                " 本番運用前に必ず設定してください。"
            )
        elif not _HAS_PYZIPPER:
            logger.error(
                "[backup] pyzipper 未インストール。pip install pyzipper を実行してください。"
                " フォールバックで平文 ZIP を作成します。"
            )
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(db_path, db_path.name)

    _rotate_backups(backup_dir, max_generations)
    return zip_path


def restore_backup(zip_path: Path, target_db_path: Optional[Path] = None) -> Path:
    """バックアップ ZIP から DB を復元する。AES 暗号化 ZIP は SS_BACKUP_PASSPHRASE が必須。

    Returns: 復元先 DB ファイルパス
    """
    if not zip_path.exists():
        raise FileNotFoundError(f"バックアップ ZIP が見つかりません: {zip_path}")

    if target_db_path is None:
        target_db_path = Path(settings.DATABASE_URL.replace("sqlite:///", ""))

    passphrase = _passphrase()

    # まず AES 暗号化 ZIP として開く試み
    if _HAS_PYZIPPER and passphrase:
        try:
            with pyzipper.AESZipFile(zip_path, "r") as zf:
                zf.setpassword(passphrase)
                names = zf.namelist()
                if not names:
                    raise ValueError("ZIP が空です")
                with zf.open(names[0]) as src:
                    with open(target_db_path, "wb") as dst:
                        shutil.copyfileobj(src, dst)
            logger.info("[backup] AES 暗号化 ZIP から復元: %s", zip_path.name)
            return target_db_path
        except (RuntimeError, pyzipper.BadZipFile):
            # AES ZIP ではない → 通常 ZIP として再試行
            pass
        except Exception as exc:
            # パスフレーズ不一致など
            raise PermissionError(f"バックアップ復元失敗（パスフレーズ不一致の可能性）: {exc}")

    # 通常 ZIP（互換性維持）
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        if not names:
            raise ValueError("ZIP が空です")
        with zf.open(names[0]) as src:
            with open(target_db_path, "wb") as dst:
                shutil.copyfileobj(src, dst)
    logger.info("[backup] 平文 ZIP から復元: %s", zip_path.name)
    return target_db_path


def list_backups() -> list[dict]:
    """バックアップ一覧を新しい順で返す。暗号化有無も明示する。"""
    backup_dir = get_backup_dir()
    result = []
    for f in sorted(backup_dir.glob("backup_*.zip"), reverse=True):
        stat = f.stat()
        result.append({
            "filename": f.name,
            "path": str(f),
            "size_bytes": stat.st_size,
            "created_at": datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
            "encrypted": _is_aes_encrypted(f),
        })
    return result


def _is_aes_encrypted(zip_path: Path) -> bool:
    """ZIP ファイルが AES 暗号化されているかを判定する。"""
    if not _HAS_PYZIPPER:
        return False
    try:
        with pyzipper.AESZipFile(zip_path, "r") as zf:
            for info in zf.infolist():
                if getattr(info, "compress_type", None) == 99:  # AES marker
                    return True
                if getattr(info, "flag_bits", 0) & 0x1:  # encrypted bit
                    return True
        return False
    except Exception:
        return False


def _rotate_backups(backup_dir: Path, max_generations: int) -> None:
    files = sorted(backup_dir.glob("backup_*.zip"))
    while len(files) > max_generations:
        files[0].unlink(missing_ok=True)
        files = files[1:]
