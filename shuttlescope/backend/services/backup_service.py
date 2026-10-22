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
import subprocess
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

def _resolve_backup_dir() -> Path:
    """バックアップ保存ディレクトリを返す。

    SQLite なら DB ファイル隣接の backups/、それ以外 (PostgreSQL 等) は
    backend/data/backups/ にフォールバックする。
    """
    db_url = settings.DATABASE_URL
    if db_url.startswith("sqlite:///"):
        db_path = Path(db_url[len("sqlite:///"):])
        return db_path.parent / "backups"
    # PostgreSQL 等: backend/data/backups
    return Path(__file__).resolve().parent.parent / "data" / "backups"


_DEFAULT_BACKUP_DIR = _resolve_backup_dir()


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


DEFAULT_MAX_GENERATIONS = 10


def create_backup(label: Optional[str] = None, max_generations: int = DEFAULT_MAX_GENERATIONS) -> Path:
    """DB を AES-256 暗号化 ZIP に固めてバックアップする。

    SQLite は DB ファイルをそのまま、PostgreSQL は pg_dump (custom 形式) の出力を入れる。
    PostgreSQL の復元は pg_restore で手動 (restore_backup は SQLite 専用)。

    パスフレーズ未設定時は平文 ZIP にフォールバック（警告ログを必ず出す）。
    本番運用では SS_BACKUP_PASSPHRASE を必ず設定すること。
    """
    passphrase = _passphrase()
    # 平文 ZIP を作らないための検査 (production posture では fail-closed)。
    # 重い処理 (pg_dump など) の前に行い、通らないなら何も書かない。
    _enforce_passphrase_policy(passphrase)

    backup_dir = get_backup_dir()
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{label}" if label else ""

    dump_tmp: Optional[Path] = None
    if settings.DATABASE_URL.startswith("sqlite:///"):
        src_path = Path(settings.DATABASE_URL[len("sqlite:///"):])
        if not src_path.exists():
            raise FileNotFoundError(f"DB ファイルが見つかりません: {src_path}")
        arcname = src_path.name
    else:
        # PostgreSQL: pg_dump のカスタム形式を ZIP に入れる (pg_restore で戻せる)
        dump_tmp = backup_dir / f".pgdump_{ts}_{os.getpid()}.tmp"
        try:
            _run_pg_dump(dump_tmp)
        except BaseException:
            dump_tmp.unlink(missing_ok=True)
            raise
        src_path = dump_tmp
        arcname = "database.pgdump"

    try:
        src_hash = _file_sha256_short(src_path)
        zip_name = f"backup_{ts}{suffix}_{src_hash}.zip"
        zip_path = backup_dir / zip_name
        _write_backup_zip(zip_path, src_path, arcname, passphrase)
    finally:
        if dump_tmp is not None:
            dump_tmp.unlink(missing_ok=True)

    _rotate_backups(backup_dir, max_generations)
    return zip_path


def _write_backup_zip(zip_path: Path, src_path: Path, arcname: str, passphrase: Optional[bytes]) -> None:
    if passphrase and _HAS_PYZIPPER:
        # AES-256 暗号化 ZIP
        with pyzipper.AESZipFile(
            zip_path, "w",
            compression=pyzipper.ZIP_DEFLATED,
            encryption=pyzipper.WZ_AES,
        ) as zf:
            zf.setpassword(passphrase)
            zf.setencryption(pyzipper.WZ_AES, nbits=256)
            zf.write(src_path, arcname)
        logger.info("[backup] AES-256 暗号化 ZIP を作成: %s", zip_path.name)
    else:
        # 開発時のみ: フォールバック平文 ZIP（本番では上で raise 済み）
        if not passphrase:
            logger.warning(
                "[backup] SS_BACKUP_PASSPHRASE 未設定 (dev only)。平文 ZIP で作成します。"
            )
        elif not _HAS_PYZIPPER:
            logger.error(
                "[backup] pyzipper 未インストール (dev only)。フォールバックで平文 ZIP を作成します。"
            )
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(src_path, arcname)


class BackupUnavailable(NotImplementedError):
    """この環境ではバックアップを作れない (pg_dump が無いなど)。

    NotImplementedError を継承するのは、取り込み前バックアップの「非対応 DB は
    バックアップなしで続行する」経路 (import_package) をそのまま使うため。
    message は画面に出してよい文面だけにする。
    """


def _enforce_passphrase_policy(passphrase: Optional[bytes]) -> None:
    # Round 258 R7 P2 fix (Codex review): production posture では平文 ZIP fallback
    # 禁止。SS_BACKUP_PASSPHRASE 未設定 / pyzipper 未導入なら fail-closed。
    # backup は DB 丸ごとなので漏洩時の影響範囲が大きい。「警告ログだけで平文」は
    # 運用ミスに極めて弱いので、エラーで止めて運用者に注意喚起する。
    # passphrase の最低長 (PKWARE-AES KDF が PBKDF2-SHA1 1000 iter と弱いため、
    # 実エントロピーで補償する) も同時に強制する。
    # 2026-09-22: `PUBLIC_MODE or ENVIRONMENT=="production"` のローカル再実装を
    # `is_production_posture` に寄せた。実本番は PUBLIC_MODE=False かつ
    # ENVIRONMENT が production に届いていない状態だったので、この fail-closed は
    # 一度も発動していなかった（passphrase が設定済みだったので平文にはならずに済んだ）。
    from backend.config import settings as _bp_settings
    _is_prod = bool(getattr(_bp_settings, "is_production_posture", False))
    if _is_prod:
        if not passphrase:
            raise RuntimeError(
                "[backup] production posture で SS_BACKUP_PASSPHRASE 未設定: "
                "fail-closed (平文 ZIP fallback を禁止)。20 文字以上の strong passphrase を設定してください"
            )
        if not _HAS_PYZIPPER:
            raise RuntimeError(
                "[backup] production posture で pyzipper 未インストール: "
                "fail-closed。`pip install pyzipper` を実行してください"
            )
        if len(passphrase) < 20:
            raise RuntimeError(
                "[backup] SS_BACKUP_PASSPHRASE が短すぎます (最低 20 文字)。"
                "PKWARE-AES の KDF (PBKDF2-SHA1 1000 iter) は脆弱なため passphrase 強度で補償が必要です"
            )
        # Round 258 R23 P2 fix (R18a-3 P2-1): 20 文字でも全部同じ char (例: "a"*20) なら
        # 5 bits 程度のエントロピーしか無く、PBKDF2-SHA1 1000 iter の弱 KDF と組み合わせて
        # オフライン総当たりの現実時間内で破られる。Shannon エントロピーの粗推定で
        # 80 bits 以上を強制する (= 大文字小文字数字記号それぞれ最低 1 種 + 重複の偏り低)。
        import math as _bp_math
        from collections import Counter as _bp_Counter
        _ch_counts = _bp_Counter(passphrase)
        _len = len(passphrase)
        _shannon = -sum((c / _len) * _bp_math.log2(c / _len) for c in _ch_counts.values())
        # 全 chars 一致なら shannon=0、20文字×全 unique なら shannon=log2(20)≒4.32。
        # 80 bits / 20 chars = 4.0 bit/char は最低ライン。
        if _shannon < 4.0:
            raise RuntimeError(
                "[backup] SS_BACKUP_PASSPHRASE のエントロピーが不足しています "
                f"(Shannon={_shannon:.2f} bit/char, 必要 4.0 bit/char 以上 = 約 80 bits 全体)。"
                "secrets.token_urlsafe(24) 等で生成してください"
            )
        # Round 258 R24 P2 fix (R24 P2):
        # Shannon ≥4.0 単独では `"abcdefghijklmnopqrst"` (a-t 20 chars unique) が
        # log2(20)≈4.32 で通るが、実体は 26-letter 辞書攻撃の射程内。
        # 大文字/小文字/数字/記号の 4 character class のうち最低 3 種を要求し、
        # 自然な強い passphrase (例: secrets.token_urlsafe / Diceware) でしか通らない
        # ようにする。
        _has_lower = any(c.islower() for c in passphrase)
        _has_upper = any(c.isupper() for c in passphrase)
        _has_digit = any(c.isdigit() for c in passphrase)
        _has_symbol = any(not c.isalnum() for c in passphrase)
        _classes = sum([_has_lower, _has_upper, _has_digit, _has_symbol])
        if _classes < 3:
            raise RuntimeError(
                "[backup] SS_BACKUP_PASSPHRASE は大文字 / 小文字 / 数字 / 記号 の "
                f"4 種のうち最低 3 種を含めてください (現在 {_classes} 種)。"
                "secrets.token_urlsafe(24) は自動で複数 class を含みます"
            )


def _run_pg_dump(out_path: Path) -> None:
    """DATABASE_URL の PostgreSQL を pg_dump (custom 形式) で out_path へ書き出す。

    パスワードはコマンドラインにもログにも出さない。子プロセスの環境変数
    PGPASSWORD でだけ渡す。失敗時の stderr からも念のため取り除く。
    """
    from sqlalchemy.engine import make_url

    url = make_url(settings.DATABASE_URL)
    if not url.drivername.startswith("postgres"):
        raise BackupUnavailable("この DB の種類ではバックアップに対応していません")
    exe = shutil.which("pg_dump")
    if not exe:
        raise BackupUnavailable("pg_dump が見つかりません。サーバに PostgreSQL クライアントを入れてください")

    cmd = [exe, "--format=custom", "--no-owner", "--no-privileges", "--file", str(out_path)]
    if url.host:
        cmd += ["--host", url.host]
    if url.port:
        cmd += ["--port", str(url.port)]
    if url.username:
        cmd += ["--username", url.username]
    cmd += ["--dbname", url.database or ""]
    env = dict(os.environ)
    env.pop("PGPASSWORD", None)
    if url.password:
        env["PGPASSWORD"] = url.password

    proc = subprocess.run(cmd, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or "").strip()
        if url.password:
            err = err.replace(url.password, "***")
        logger.error("[backup] pg_dump failed (exit %s): %s", proc.returncode, err[:500])
        raise RuntimeError("pg_dump が失敗しました。サーバのログを確認してください")
    logger.info("[backup] pg_dump 完了: %s", out_path.name)


def restore_backup(zip_path: Path, target_db_path: Optional[Path] = None) -> Path:
    """バックアップ ZIP から DB を復元する。AES 暗号化 ZIP は SS_BACKUP_PASSPHRASE が必須。

    Returns: 復元先 DB ファイルパス
    """
    if not settings.DATABASE_URL.startswith("sqlite:///") and target_db_path is None:
        raise NotImplementedError("restore_backup は SQLite 専用です。PostgreSQL は pg_restore で復元してください")
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


def backup_status() -> dict:
    """バックアップ画面用の状態。作れるか・最後に成功した時刻・世代数を返す。

    最後の成功は、保存先にある最新のバックアップ ZIP の更新時刻 (UTC) で判断する。
    取れていないのに「最終成功」を出さないよう、ZIP が無ければ None。
    """
    url = settings.DATABASE_URL
    if url.startswith("sqlite:///"):
        engine, supported, reason = "sqlite", True, None
    elif url.startswith("postgres"):
        engine = "postgresql"
        supported = shutil.which("pg_dump") is not None
        reason = None if supported else "pg_dump_missing"
    else:
        engine, supported, reason = "other", False, "unsupported_engine"
    items = list_backups()
    latest = items[0] if items else None
    return {
        "engine": engine,
        "supported": supported,
        "reason": reason,
        "backup_dir": str(get_backup_dir()),
        "count": len(items),
        "max_generations": DEFAULT_MAX_GENERATIONS,
        "last_success_at": (latest["created_at"] + "Z") if latest else None,
        "last_size_bytes": latest["size_bytes"] if latest else None,
        "last_encrypted": latest["encrypted"] if latest else None,
    }


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
