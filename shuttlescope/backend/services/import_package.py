"""
import_package.py — .sspkg パッケージの解析とレコード単位マージ

仕様書 §8 に基づく。
  Phase 1: 別試合は自動マージ、同一 uuid は updated_at 優先、危険条件は conflict log へ
"""
from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy import text

from backend.services.merge_resolver import decide_merge, MergeDecision
from backend.db.models import (
    Match, GameSet, Rally, Stroke, Player,
    PreMatchObservation, HumanForecast, Comment, EventBookmark,
    SyncConflict,
)

# ─── インポートサマリー ────────────────────────────────────────────────────────

@dataclass
class ImportSummary:
    added: int = 0
    updated: int = 0
    kept: int = 0
    deleted: int = 0
    conflicts: int = 0
    conflict_log: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# ─── テーブル処理マップ ────────────────────────────────────────────────────────

# (JSON キー, SQLAlchemy モデル, uuid で検索するクエリ関数)
_TABLE_MAP = [
    ("players",        Player),
    ("matches",        Match),
    ("sets",           GameSet),
    ("rallies",        Rally),
    ("strokes",        Stroke),
    ("observations",   PreMatchObservation),
    ("human_forecasts", HumanForecast),
    ("comments",       Comment),
    ("bookmarks",      EventBookmark),
]

# モデルが持つカラム名セット（動的取得でキャッシュ）
_COLUMN_CACHE: dict[type, set[str]] = {}


def _get_columns(model_cls: type) -> set[str]:
    if model_cls not in _COLUMN_CACHE:
        _COLUMN_CACHE[model_cls] = {c.name for c in model_cls.__table__.columns}
    return _COLUMN_CACHE[model_cls]


def _find_by_uuid(db: Session, model_cls: type, uuid: str) -> Optional[Any]:
    return db.query(model_cls).filter_by(uuid=uuid).first()


def _obj_to_dict(obj: Any) -> dict:
    d = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if isinstance(val, datetime):
            val = val.isoformat()
        d[col.name] = val
    return d


def _apply_record(
    db: Session,
    model_cls: type,
    decision: MergeDecision,
    id_remap: dict[str, dict[str, int]],
    table_key: str,
) -> None:
    """
    MergeDecision に従ってレコードを DB に書き込む。

    id_remap: {"players": {old_id: new_id}, ...} で外部キーを変換する。
    """
    if decision.action == "keep":
        return

    incoming = decision.incoming_record or {}
    valid_cols = _get_columns(model_cls)

    # 論理削除
    if decision.action == "delete":
        obj = db.query(model_cls).filter_by(id=decision.local_id).first()
        if obj and hasattr(obj, "deleted_at") and obj.deleted_at is None:
            obj.deleted_at = datetime.utcnow()
            db.commit()
        return

    # フィールド準備（DB 内部 id は除く、外部キーをリマップ）
    data = {k: v for k, v in incoming.items() if k in valid_cols and k != "id"}

    # 外部キーリマップ（players: player_a_id/player_b_id etc.）
    _remap_fks(data, id_remap)

    if decision.action == "new":
        obj = model_cls(**data)
        db.add(obj)
        db.flush()
        # id リマップ登録
        old_id = incoming.get("id")
        if old_id and obj.id:
            id_remap.setdefault(table_key, {})[old_id] = obj.id

    elif decision.action == "update":
        obj = db.query(model_cls).filter_by(id=decision.local_id).first()
        if obj:
            for k, v in data.items():
                if k != "id":
                    setattr(obj, k, v)

    db.commit()


def _remap_fks(data: dict, id_remap: dict[str, dict[str, int]]) -> None:
    """外部キー列の値をリマップテーブルで変換する"""
    fk_map = {
        "player_a_id": "players",
        "player_b_id": "players",
        "partner_a_id": "players",
        "partner_b_id": "players",
        "player_id": "players",
        "match_id": "matches",
        "set_id": "sets",
        "rally_id": "rallies",
        "stroke_id": "strokes",
    }
    for col, src_table in fk_map.items():
        if col in data and data[col] is not None:
            old_val = data[col]
            new_val = id_remap.get(src_table, {}).get(old_val)
            if new_val is not None:
                data[col] = new_val


# ─── メインインポート処理 ──────────────────────────────────────────────────────

def import_package(db: Session, raw: bytes, dry_run: bool = False) -> ImportSummary:
    """
    .sspkg バイト列を解析し DB へマージする。

    dry_run=True の場合は DB を変更せず ImportSummary のみ返す（プレビュー用）。
    """
    summary = ImportSummary()
    id_remap: dict[str, dict[str, int]] = {}

    try:
        buf = io.BytesIO(raw)
        with zipfile.ZipFile(buf, "r") as zf:
            names = set(zf.namelist())

            # テーブル順に処理（依存関係: Player → Match → Set → Rally → Stroke）
            for table_key, model_cls in _TABLE_MAP:
                fname = f"{table_key}.json"
                if fname not in names:
                    continue

                records: list[dict] = json.loads(zf.read(fname))

                for rec in records:
                    uuid = rec.get("uuid")
                    if not uuid:
                        summary.errors.append(f"{table_key}: uuid なしレコードをスキップ")
                        continue

                    local_obj = _find_by_uuid(db, model_cls, uuid)
                    local_dict = _obj_to_dict(local_obj) if local_obj else None
                    decision = decide_merge(table_key, rec, local_dict)

                    if dry_run:
                        # プレビューはカウントのみ
                        if decision.action == "new":
                            summary.added += 1
                        elif decision.action == "update":
                            summary.updated += 1
                        elif decision.action == "keep":
                            summary.kept += 1
                        elif decision.action == "delete":
                            summary.deleted += 1
                        elif decision.action == "conflict":
                            summary.conflicts += 1
                            summary.conflict_log.append({
                                "table": table_key,
                                "uuid": uuid,
                                "reason": decision.reason,
                            })
                        continue

                    # 実際の書き込み
                    try:
                        if decision.action == "new":
                            _apply_record(db, model_cls, decision, id_remap, table_key)
                            summary.added += 1
                        elif decision.action == "update":
                            _apply_record(db, model_cls, decision, id_remap, table_key)
                            summary.updated += 1
                        elif decision.action == "keep":
                            # 既存 id をリマップに登録（後続FK解決用）
                            old_id = rec.get("id")
                            if old_id and local_obj:
                                id_remap.setdefault(table_key, {})[old_id] = local_obj.id
                            summary.kept += 1
                        elif decision.action == "delete":
                            _apply_record(db, model_cls, decision, id_remap, table_key)
                            summary.deleted += 1
                        elif decision.action == "conflict":
                            summary.conflicts += 1
                            summary.conflict_log.append({
                                "table": table_key,
                                "uuid": uuid,
                                "reason": decision.reason,
                            })
                            # 競合を DB に永続化
                            try:
                                conflict_rec = SyncConflict(
                                    record_table=table_key,
                                    record_uuid=uuid,
                                    import_device=rec.get("source_device_id"),
                                    import_updated_at=str(rec.get("updated_at") or ""),
                                    local_updated_at=str((local_dict or {}).get("updated_at") or ""),
                                    incoming_snapshot=json.dumps(rec, ensure_ascii=False)[:4000],
                                    reason=decision.reason,
                                )
                                db.add(conflict_rec)
                                db.commit()
                            except Exception:
                                db.rollback()
                            # 競合は keep（Phase 3 の UI で解決）
                            old_id = rec.get("id")
                            if old_id and local_obj:
                                id_remap.setdefault(table_key, {})[old_id] = local_obj.id

                    except Exception as e:
                        db.rollback()
                        summary.errors.append(f"{table_key}[{uuid}]: {e}")

    except zipfile.BadZipFile:
        summary.errors.append("不正な ZIP ファイルです")
    except Exception as e:
        summary.errors.append(f"インポートエラー: {e}")

    return summary
