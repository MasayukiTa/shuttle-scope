"""
promotion_override_store.py — アナリスト昇格判断 Override の永続化

POCフェーズ: shuttlescope/backend/data/promotion_overrides.json に保存。
本番環境では DB テーブルに移行すること。
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# データ保存先（backend/ 直下の data/ ディレクトリ）
_DATA_DIR = Path(__file__).parent.parent / "data"
_OVERRIDE_FILE = _DATA_DIR / "promotion_overrides.json"

# 有効なステータス値
VALID_STATUSES = {"promotion_ready", "requires_review", "insufficient_data", "hold"}


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


def load_all_overrides() -> dict[str, dict]:
    """全 override を返す。"""
    return _load()


def get_override(analysis_type: str) -> Optional[dict]:
    """特定の analysis_type の override を返す。なければ None。"""
    return _load().get(analysis_type)


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
        note: アナリストのコメント
        analyst: 操作者のロール名（POCではロール文字列）

    Returns:
        保存したエントリの dict
    """
    if status not in VALID_STATUSES:
        raise ValueError(f"Invalid status: {status}. Must be one of {VALID_STATUSES}")

    overrides = _load()
    entry: dict = {
        "analysis_type": analysis_type,
        "status": status,
        "note": note,
        "analyst": analyst,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    overrides[analysis_type] = entry
    _save(overrides)
    return entry


def delete_override(analysis_type: str) -> bool:
    """Override を削除する。削除できたら True を返す。"""
    overrides = _load()
    if analysis_type not in overrides:
        return False
    del overrides[analysis_type]
    _save(overrides)
    return True
