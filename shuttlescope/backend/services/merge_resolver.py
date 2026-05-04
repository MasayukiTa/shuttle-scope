"""
merge_resolver.py — UUID ベースのレコード比較・マージ判定

仕様書 §8 に基づく。
  - new:       ローカルに uuid が存在しない → 新規追加
  - keep:      ローカルの updated_at が新しい → ローカル維持
  - update:    incoming の updated_at が新しい → インポート側で上書き
  - conflict:  両方が更新されており content_hash が異なる → 競合候補
  - delete:    incoming に deleted_at あり → 論理削除を反映
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal, Optional

MergeAction = Literal["new", "update", "keep", "conflict", "delete"]

# updated_at が近接しているとみなす秒数
CONFLICT_WINDOW_SEC = 5


def _parse_dt(val: Any) -> Optional[datetime]:
    """ISO 文字列 / datetime を datetime に統一（タイムゾーン naive）"""
    if val is None:
        return None
    if isinstance(val, datetime):
        return val.replace(tzinfo=None) if val.tzinfo else val
    try:
        dt = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
        return dt.replace(tzinfo=None)
    except Exception:
        return None


@dataclass
class MergeDecision:
    uuid: str
    action: MergeAction
    table: str
    local_id: Optional[int] = None
    incoming_record: Optional[dict] = field(default=None, repr=False)
    reason: str = ""


def decide_merge(
    table: str,
    incoming: dict,
    local: Optional[dict],
) -> MergeDecision:
    """
    incoming と local を比較し MergeDecision を返す。

    Args:
        table: テーブル名（ログ用）
        incoming: パッケージから読み込んだレコード dict（uuid 必須）
        local: DB 上の既存レコード dict、None なら新規
    """
    uuid = incoming.get("uuid", "")

    if local is None:
        return MergeDecision(uuid=uuid, action="new", table=table,
                             incoming_record=incoming, reason="uuid not found locally")

    local_id = local.get("id")
    inc_deleted = _parse_dt(incoming.get("deleted_at"))
    loc_updated = _parse_dt(local.get("updated_at"))
    inc_updated = _parse_dt(incoming.get("updated_at"))
    inc_hash = incoming.get("content_hash")
    loc_hash = local.get("content_hash")

    # 論理削除を反映（incoming が削除済み かつ ローカルより新しい）
    if inc_deleted is not None:
        if loc_updated is None or inc_deleted >= loc_updated:
            return MergeDecision(uuid=uuid, action="delete", table=table,
                                 local_id=local_id, incoming_record=incoming,
                                 reason="incoming deleted_at >= local updated_at")
        return MergeDecision(uuid=uuid, action="keep", table=table,
                             local_id=local_id, reason="local was updated after incoming deletion")

    # タイムスタンプが取得できない場合はローカル優先
    if inc_updated is None:
        return MergeDecision(uuid=uuid, action="keep", table=table,
                             local_id=local_id, reason="incoming has no updated_at")
    if loc_updated is None:
        return MergeDecision(uuid=uuid, action="update", table=table,
                             local_id=local_id, incoming_record=incoming,
                             reason="local has no updated_at")

    delta = abs((inc_updated - loc_updated).total_seconds())

    # 近接タイムスタンプ + ハッシュ不一致 → 競合
    if delta <= CONFLICT_WINDOW_SEC and inc_hash and loc_hash and inc_hash != loc_hash:
        return MergeDecision(uuid=uuid, action="conflict", table=table,
                             local_id=local_id, incoming_record=incoming,
                             reason=f"both updated within {CONFLICT_WINDOW_SEC}s, hash differs")

    if inc_updated > loc_updated:
        return MergeDecision(uuid=uuid, action="update", table=table,
                             local_id=local_id, incoming_record=incoming,
                             reason="incoming.updated_at > local.updated_at")

    return MergeDecision(uuid=uuid, action="keep", table=table,
                         local_id=local_id, reason="local.updated_at >= incoming.updated_at")
