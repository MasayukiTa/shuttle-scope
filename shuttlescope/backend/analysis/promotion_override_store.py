"""
promotion_override_store.py — アナリスト昇格判断 Override の永続化

POCフェーズ: shuttlescope/backend/data/promotion_overrides.json に保存。
本番環境では DB テーブルに移行すること。

監査ログ:
  - 各エントリに audit_log 配列を保持（create/update アクション）
  - 削除を含む全アクションは promotion_audit_log.json にも追記
  - これにより削除後もアクション履歴が参照できる
"""
from __future__ import annotations
import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# データ保存先（backend/ 直下の data/ ディレクトリ）
_DATA_DIR = Path(__file__).parent.parent / "data"
_OVERRIDE_FILE = _DATA_DIR / "promotion_overrides.json"
_AUDIT_LOG_FILE = _DATA_DIR / "promotion_audit_log.json"

# 有効なステータス値
VALID_STATUSES = {"promotion_ready", "requires_review", "insufficient_data", "hold"}

# hold ステータスでは note を強く推奨（バリデーションは呼び出し元で実施）
HOLD_NOTE_REQUIRED = True


class StoreCorruptError(RuntimeError):
    """保存ファイルはあるが読めない。空として扱うと次の保存で全件を失うので、書き込みは止める。"""


# 読み込み→変更→保存を 1 まとまりにする (同時に 2 つの操作が走ると片方が失われる)
_LOCK = threading.RLock()


def _read_json(path: Path, default: Any, *, strict: bool) -> Any:
    """JSON を読む。ファイルが無ければ default。

    壊れていて読めない場合:
      strict=True  (書き込み側)  StoreCorruptError。壊れたファイルは上書きせず残す
      strict=False (読み取り側)  default を返す。ファイルには触らない
    どちらも、壊れたファイルを空として扱ったまま保存してしまうことはない。
    """
    if not path.exists():
        return default
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError) as exc:
        logger.error("promotion store: cannot read %s: %s", path, exc)
        if strict:
            raise StoreCorruptError(
                f"{path.name} が読めません。内容を確認してから手で直してください (上書きはしていません)"
            ) from exc
        return default


def _write_json_atomic(path: Path, data: Any) -> None:
    """同じディレクトリの一時ファイルに書いてから置き換える。途中で落ちても元のファイルは残る。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def _load(*, strict: bool = False) -> dict[str, dict]:
    data = _read_json(_OVERRIDE_FILE, {}, strict=strict)
    return data if isinstance(data, dict) else {}


def _save(data: dict[str, dict]) -> None:
    _write_json_atomic(_OVERRIDE_FILE, data)


def _append_audit(action: dict) -> None:
    """全アクションを追記する（削除後も参照可能にするためのグローバルログ）。"""
    log = _read_json(_AUDIT_LOG_FILE, [], strict=True)
    if not isinstance(log, list):
        raise StoreCorruptError(f"{_AUDIT_LOG_FILE.name} が一覧ではありません (上書きはしていません)")
    log.append(action)
    _write_json_atomic(_AUDIT_LOG_FILE, log)


def load_all_overrides() -> dict[str, dict]:
    """全 override を返す。"""
    return _load()


def get_override(analysis_type: str) -> Optional[dict]:
    """特定の analysis_type の override を返す。なければ None。"""
    return _load().get(analysis_type)


def get_audit_log(analysis_type: Optional[str] = None) -> list[dict]:
    """
    監査ログを返す。

    Args:
        analysis_type: 指定すれば該当 analysis_type のみ絞り込み。None で全件。

    Returns:
        アクション履歴のリスト（新しい順）
    """
    log = _read_json(_AUDIT_LOG_FILE, [], strict=False)
    if not isinstance(log, list):
        return []
    if analysis_type:
        log = [e for e in log if e.get("analysis_type") == analysis_type]
    # 新しい順に返す
    return list(reversed(log))


def save_override(
    analysis_type: str,
    status: str,
    note: str = "",
    analyst: str = "analyst",
) -> dict:
    """
    Override を保存する。既存エントリがあれば上書き。

    Args:
        analysis_type: 対象の解析種別
        status: "promotion_ready" | "requires_review" | "insufficient_data" | "hold"
        note: アナリストのコメント（hold 時は強く推奨）
        analyst: 操作者のロール名（POCではロール文字列）

    Returns:
        保存したエントリの dict
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}. Must be one of {VALID_STATUSES}")

    with _LOCK:
        return _save_override_locked(analysis_type, status, note, analyst)


def _save_override_locked(analysis_type: str, status: str, note: str, analyst: str) -> dict:
    overrides = _load(strict=True)
    old_entry = overrides.get(analysis_type)
    timestamp = datetime.now(timezone.utc).isoformat()

    # 監査アクション
    audit_action: dict = {
        "timestamp": timestamp,
        "analysis_type": analysis_type,
        "analyst": analyst,
        "action": "update" if old_entry else "create",
        "old_status": old_entry.get("status") if old_entry else None,
        "new_status": status,
        "note": note,
    }

    # エントリ内の audit_log にも追記（エントリが残っている間は参照できる）
    entry_audit_log: list[dict] = old_entry.get("audit_log", []) if old_entry else []
    entry_audit_log = entry_audit_log + [audit_action]

    entry: dict = {
        "analysis_type": analysis_type,
        "status": status,
        "note": note,
        "analyst": analyst,
        "updated_at": timestamp,
        "audit_log": entry_audit_log,
    }
    overrides[analysis_type] = entry
    # 監査ログを先に書く: 記録の無い変更を作らない (ログが壊れていれば、ここで止まり何も変えない)
    _append_audit(audit_action)
    _save(overrides)
    return entry


def delete_override(analysis_type: str, analyst: str = "analyst") -> bool:
    """
    Override を削除する。削除できたら True を返す。
    削除アクションはグローバル監査ログに記録される。
    """
    with _LOCK:
        return _delete_override_locked(analysis_type, analyst)


def _delete_override_locked(analysis_type: str, analyst: str) -> bool:
    overrides = _load(strict=True)
    if analysis_type not in overrides:
        return False

    old_entry = overrides[analysis_type]
    timestamp = datetime.now(timezone.utc).isoformat()

    audit_action: dict = {
        "timestamp": timestamp,
        "analysis_type": analysis_type,
        "analyst": analyst,
        "action": "delete",
        "old_status": old_entry.get("status"),
        "new_status": None,
        "note": "",
    }

    del overrides[analysis_type]
    _append_audit(audit_action)
    _save(overrides)
    return True
