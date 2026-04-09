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
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# データ保存先（backend/ 直下の data/ ディレクトリ）
_DATA_DIR = Path(__file__).parent.parent / "data"
_OVERRIDE_FILE = _DATA_DIR / "promotion_overrides.json"
_AUDIT_LOG_FILE = _DATA_DIR / "promotion_audit_log.json"

# 有効なステータス値
VALID_STATUSES = {"promotion_ready", "requires_review", "insufficient_data", "hold"}

# hold ステータスでは note を強く推奨（バリデーションは呼び出し元で実施）
HOLD_NOTE_REQUIRED = True


def _load() -> dict[str, dict]:
    if not _OVERRIDE_FILE.exists():
        return {}
    try:
        with open(_OVERRIDE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save(data: dict[str, dict]) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(_OVERRIDE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _append_audit(action: dict) -> None:
    """全アクションを追記する（削除後も参照可能にするためのグローバルログ）。"""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    log: list[dict] = []
    if _AUDIT_LOG_FILE.exists():
        try:
            with open(_AUDIT_LOG_FILE, encoding="utf-8") as f:
                log = json.load(f)
        except Exception:
            log = []
    log.append(action)
    with open(_AUDIT_LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


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
    if not _AUDIT_LOG_FILE.exists():
        return []
    try:
        with open(_AUDIT_LOG_FILE, encoding="utf-8") as f:
            log: list[dict] = json.load(f)
    except Exception:
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

    overrides = _load()
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
    _save(overrides)
    _append_audit(audit_action)
    return entry


def delete_override(analysis_type: str, analyst: str = "analyst") -> bool:
    """
    Override を削除する。削除できたら True を返す。
    削除アクションはグローバル監査ログに記録される。
    """
    overrides = _load()
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
    _save(overrides)
    _append_audit(audit_action)
    return True
