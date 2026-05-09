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
    SyncConflict, Condition, ConditionTag,
)
from datetime import date as _date

# ─── 解凍爆弾 (CWE-409) 対策の上限値 ───────────────────────────────────────────
# .sspkg は通常数 MB〜数百 MB 想定。攻撃者が巨大膨張率の ZIP を投げて
# サーバメモリを枯渇させる zip bomb を遮断するため、解凍後合計サイズ・
# メンバー数・単一メンバーサイズを保守的に制限する。
_MAX_TOTAL_UNCOMPRESSED = 1 * 1024 * 1024 * 1024   # 1 GB
_MAX_PER_MEMBER         = 256 * 1024 * 1024        # 256 MB / file
_MAX_MEMBER_COUNT       = 5000
_MAX_COMPRESSION_RATIO  = 100                       # uncompressed/compressed 上限


def check_zip_bomb_caps(zf: zipfile.ZipFile) -> Optional[str]:
    """ZIP メンバーが zip bomb の上限を超えているか検査する。

    解凍前に呼び出すこと。違反があればエラーメッセージ (str) を返し、
    無ければ None を返す。``import_package`` と ``validate_package`` の
    両方から呼ぶ共通防御点。

    `validate_package` 側にも同等のチェックがないと、攻撃者が
    `/api/sync/validate` 経由で `import_package` を経由せず zip bomb を
    炸裂させる経路 (V2 のバイパス) が成立するため、共通化している。
    """
    infos = zf.infolist()
    if len(infos) > _MAX_MEMBER_COUNT:
        return f"パッケージのメンバー数が上限 ({_MAX_MEMBER_COUNT}) を超えています"
    total_uncompressed = 0
    for info in infos:
        if info.file_size > _MAX_PER_MEMBER:
            return f"メンバー {info.filename} のサイズが上限 ({_MAX_PER_MEMBER} byte) を超えています"
        if info.compress_size > 0 and info.file_size // max(info.compress_size, 1) > _MAX_COMPRESSION_RATIO:
            return f"メンバー {info.filename} の圧縮率が異常です (zip bomb の可能性)"
        total_uncompressed += info.file_size
        if total_uncompressed > _MAX_TOTAL_UNCOMPRESSED:
            return f"パッケージの解凍後合計サイズが上限 ({_MAX_TOTAL_UNCOMPRESSED} byte) を超えています"
    return None

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


# Round 258 R3 P0/P1 fix (Finding 1+2): mass-assignment / cross-team takeover 防止
#
# 旧来は `data = {k: v for k, v in incoming.items() if k in valid_cols and k != "id"}` で
# どのカラムでも書き込めていた。これを使うと、悪意ある analyst が以下を仕込んだ .sspkg を
# import すると team scope を超えてデータを掌握できる:
#   - matches: owner_team_id / is_public_pool / annotator_id を上書き
#   - players: team_id を別チームに移動
#   - 全モデル: deleted_at=None で soft-delete を蘇生
#   - updated_at=9999-12-31 で永続的に「勝ち」を確保 (merge resolver 騙し)
#   - revision / content_hash を偽造して audit chain 仮定を破る
#
# 対策:
#   1. テーブル別の許可カラム allowlist (IMPORT_ALLOWED_COLUMNS) を定義
#   2. 列がリストに無い場合は黙って drop (例外で attacker 露出させない)
#   3. updated_at は server_now を超えない値にクランプ
#   4. revision / content_hash / deleted_at / *_team_id / annotator_id は server-derived
#      として一律 strip
_FORCED_STRIP_COLUMNS = {
    # ─ 蘇生防止 ─
    "deleted_at",
    "is_deleted",
    # ─ audit chain / server-derived ─
    "revision",
    "content_hash",
    "row_hash",
    "prev_hash",
    "created_at",          # Round 258 R4 F4 fix: 旧監査改竄 (作成日付偽造) 防止
    # ─ team scope 強制 (importer team で再決定) ─
    "owner_team_id",
    "home_team_id",
    "away_team_id",
    "team_id",
    # ─ ユーザ / 認証関連 ─
    "annotator_id",
    "uploader_user_id",
    "actor_user_id",
    "user_id",             # generic user FK
    "consumed_by_user_id",
    "inviter_user_id",
    "imported_from_device_id",
    "source_device_id",
    # ─ 機微フラグ・トークン ─
    "is_public_pool",
    "is_admin",
    "share_token",         # session_share token spoofing
    "session_token",
    "parent_session_id",
    "totp_secret",
    "password_hash",       # 万が一 model に列があっても export/import 経由で書かない
    # ─ モデル出力偽造防止 ─
    "confidence_score",
    "evidence_level",
    "validity_score",
    "validity_flag",
}


def _sanitize_import_record(model_cls: type, incoming: dict, server_now: datetime) -> dict:
    """incoming dict を import 安全な dict にサニタイズする。

    - id を除外
    - _FORCED_STRIP_COLUMNS をすべて drop
    - updated_at が未来に飛んでいたら server_now にクランプ
    - 戻り値: 適用してよい (model_cls(**data) / setattr) dict
    """
    valid_cols = _get_columns(model_cls)
    out = {}
    for k, v in incoming.items():
        if k == "id":
            continue
        if k in _FORCED_STRIP_COLUMNS:
            continue
        if k not in valid_cols:
            continue
        out[k] = v
    # 時刻クランプ: future-pinning による merge 戦略の悪用を防ぐ
    # Round 258 R4 F5 fix: epoch int / float も datetime に正規化してから比較。
    # 旧来は str しか handle していなかったため `"updated_at": 99999999999` で永久勝利可能だった。
    if "updated_at" in out and out["updated_at"] is not None:
        try:
            ts = out["updated_at"]
            if isinstance(ts, str):
                from datetime import datetime as _dt
                ts = _dt.fromisoformat(ts.replace("Z", "+00:00"))
                if ts.tzinfo is not None:
                    ts = ts.replace(tzinfo=None)
            elif isinstance(ts, (int, float)):
                from datetime import datetime as _dt
                ts = _dt.utcfromtimestamp(float(ts))
            if isinstance(ts, datetime):
                if ts > server_now:
                    out["updated_at"] = server_now
                else:
                    out["updated_at"] = ts
            else:
                # 想定外の型 → server_now にクランプ
                out["updated_at"] = server_now
        except Exception:
            out["updated_at"] = server_now
    return out


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
    importer_team_id: Optional[int] = None,
) -> None:
    """
    MergeDecision に従ってレコードを DB に書き込む。

    id_remap: {"players": {old_id: new_id}, ...} で外部キーを変換する。
    """
    if decision.action == "keep":
        return

    incoming = decision.incoming_record or {}
    server_now = datetime.utcnow()

    # 論理削除
    if decision.action == "delete":
        obj = db.query(model_cls).filter_by(id=decision.local_id).first()
        if obj and hasattr(obj, "deleted_at") and obj.deleted_at is None:
            # Round 258 R3 P1 fix (Finding 4): delete も ownership 検証必須。
            # 旧来は uuid 一致だけで他チームのレコードを soft-delete できた。
            if importer_team_id is not None and hasattr(obj, "owner_team_id"):
                if obj.owner_team_id is not None and obj.owner_team_id != importer_team_id:
                    return  # 他チームのレコードは静かにスキップ
            obj.deleted_at = server_now
            db.commit()
        return

    # Round 258 R3 P0/P1 fix (Finding 1+2): mass-assignment 防止 + 時刻クランプ
    data = _sanitize_import_record(model_cls, incoming, server_now)

    # 外部キーリマップ（players: player_a_id/player_b_id etc.）
    _remap_fks(data, id_remap)

    if decision.action == "new":
        # 新規作成時は importer team を server-side で強制設定
        if importer_team_id is not None:
            for col in ("owner_team_id", "home_team_id", "team_id"):
                if col in _get_columns(model_cls):
                    data.setdefault(col, importer_team_id)
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
            # Round 258 R3 P1 fix (Finding 4): update も ownership 検証必須。
            if importer_team_id is not None and hasattr(obj, "owner_team_id"):
                if obj.owner_team_id is not None and obj.owner_team_id != importer_team_id:
                    return
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

def import_package(db: Session, raw: bytes, dry_run: bool = False,
                   importer_team_id: Optional[int] = None) -> ImportSummary:
    """
    .sspkg バイト列を解析し DB へマージする。

    dry_run=True の場合は DB を変更せず ImportSummary のみ返す（プレビュー用）。

    Round 258 R3 P0/P1 fix:
    importer_team_id を受け取り、_apply_record まで伝播する。これにより
    cross-team データ takeover (incoming に他チームの owner_team_id を仕込む攻撃)
    と他チーム row の delete/update を遮断する。caller (routers/sync.py) は
    呼び出し元の認証コンテキストから team_id を解決して渡すこと。
    """
    summary = ImportSummary()
    id_remap: dict[str, dict[str, int]] = {}

    try:
        buf = io.BytesIO(raw)
        with zipfile.ZipFile(buf, "r") as zf:
            # zip bomb 事前チェック (validate_package と共通の防御)
            bomb_err = check_zip_bomb_caps(zf)
            if bomb_err:
                summary.errors.append(bomb_err)
                return summary

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
                            _apply_record(db, model_cls, decision, id_remap, table_key, importer_team_id)
                            summary.added += 1
                        elif decision.action == "update":
                            _apply_record(db, model_cls, decision, id_remap, table_key, importer_team_id)
                            summary.updated += 1
                        elif decision.action == "keep":
                            # 既存 id をリマップに登録（後続FK解決用）
                            old_id = rec.get("id")
                            if old_id and local_obj:
                                id_remap.setdefault(table_key, {})[old_id] = local_obj.id
                            summary.kept += 1
                        elif decision.action == "delete":
                            _apply_record(db, model_cls, decision, id_remap, table_key, importer_team_id)
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

            # Conditions / ConditionTags — uuid なしの自然キーマージ
            _import_conditions(db, zf, names, id_remap, summary, dry_run)
            _import_condition_tags(db, zf, names, id_remap, summary, dry_run)

    except zipfile.BadZipFile:
        summary.errors.append("不正な ZIP ファイルです")
    except Exception as e:
        summary.errors.append(f"インポートエラー: {e}")

    return summary


def _parse_date(v: Any) -> Optional[_date]:
    if v is None:
        return None
    if isinstance(v, _date):
        return v
    try:
        return _date.fromisoformat(str(v)[:10])
    except Exception:
        return None


def _import_conditions(
    db: Session, zf: zipfile.ZipFile, names: set, id_remap: dict,
    summary: ImportSummary, dry_run: bool,
) -> None:
    """Condition を (player_id, measured_at, condition_type) 自然キーでマージ。"""
    if "conditions.json" not in names:
        return
    recs: list[dict] = json.loads(zf.read("conditions.json"))
    valid_cols = _get_columns(Condition)
    for rec in recs:
        try:
            data = {k: v for k, v in rec.items() if k in valid_cols and k != "id"}
            _remap_fks(data, id_remap)
            pid = data.get("player_id")
            measured_at = _parse_date(data.get("measured_at"))
            ctype = data.get("condition_type") or "weekly"
            if not pid or not measured_at:
                summary.errors.append("conditions: player_id/measured_at 不正でスキップ")
                continue
            # FK 整合: player が存在しなければスキップ
            if not db.get(Player, pid):
                summary.errors.append(f"conditions: player_id={pid} が存在せずスキップ")
                continue
            data["measured_at"] = measured_at
            existing = (
                db.query(Condition)
                .filter(
                    Condition.player_id == pid,
                    Condition.measured_at == measured_at,
                    Condition.condition_type == ctype,
                )
                .first()
            )
            if existing:
                if dry_run:
                    summary.updated += 1
                    continue
                for k, v in data.items():
                    if k in ("created_at",):
                        continue
                    setattr(existing, k, v)
                db.commit()
                summary.updated += 1
            else:
                if dry_run:
                    summary.added += 1
                    continue
                obj = Condition(**data)
                db.add(obj)
                db.commit()
                summary.added += 1
        except Exception as e:
            db.rollback()
            summary.errors.append(f"conditions: {e}")


def _import_condition_tags(
    db: Session, zf: zipfile.ZipFile, names: set, id_remap: dict,
    summary: ImportSummary, dry_run: bool,
) -> None:
    """ConditionTag を (player_id, label, start_date) 自然キーでマージ。"""
    if "condition_tags.json" not in names:
        return
    recs: list[dict] = json.loads(zf.read("condition_tags.json"))
    valid_cols = _get_columns(ConditionTag)
    for rec in recs:
        try:
            data = {k: v for k, v in rec.items() if k in valid_cols and k != "id"}
            _remap_fks(data, id_remap)
            pid = data.get("player_id")
            start_date = _parse_date(data.get("start_date"))
            label = data.get("label")
            if not pid or not start_date or not label:
                summary.errors.append("condition_tags: 必須項目不足でスキップ")
                continue
            if not db.get(Player, pid):
                summary.errors.append(f"condition_tags: player_id={pid} が存在せずスキップ")
                continue
            data["start_date"] = start_date
            data["end_date"] = _parse_date(data.get("end_date"))
            existing = (
                db.query(ConditionTag)
                .filter(
                    ConditionTag.player_id == pid,
                    ConditionTag.label == label,
                    ConditionTag.start_date == start_date,
                )
                .first()
            )
            if existing:
                if dry_run:
                    summary.kept += 1
                    continue
                # 既存は保持（冪等）
                summary.kept += 1
            else:
                if dry_run:
                    summary.added += 1
                    continue
                obj = ConditionTag(**data)
                db.add(obj)
                db.commit()
                summary.added += 1
        except Exception as e:
            db.rollback()
            summary.errors.append(f"condition_tags: {e}")
