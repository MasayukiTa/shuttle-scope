"""
export_package.py — Match / Player / Full-backup パッケージの生成

仕様書 §6, §7 に基づく。
パッケージ形式: .sspkg（実体 ZIP）
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import datetime
from typing import Any, Optional

from sqlalchemy.orm import Session

from backend.db.models import (
    Match, GameSet, Rally, Stroke, Player,
    PreMatchObservation, HumanForecast, Comment, EventBookmark,
    Condition, ConditionTag,
)

PACKAGE_VERSION = "1.1"
SCHEMA_VERSION = 9  # conditions / condition_tags 追加

from sqlalchemy import text as _text


# ─── 内部ヘルパー ──────────────────────────────────────────────────────────────

def _dt(v: Any) -> Optional[str]:
    """datetime → ISO 文字列（None は None）"""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def _model_to_dict(obj: Any) -> dict:
    """SQLAlchemy モデルを dict に変換（関係属性を除く）"""
    d = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.name)
        if isinstance(val, datetime):
            val = val.isoformat()
        d[col.name] = val
    return d


def _checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")


# ─── エクスポート: 試合単位 ────────────────────────────────────────────────────

def export_match(
    db: Session,
    match_ids: list[int],
    device_id: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> bytes:
    """
    指定した試合（複数可）と関連レコードを .sspkg バイト列として返す。

    含むもの:
      Match, GameSet, Rally, Stroke, 関連 Player（最小メタ）
      PreMatchObservation, HumanForecast, Comment, EventBookmark
      Condition (参加選手の since〜until 期間), ConditionTag (同期間)

    since/until は "YYYY-MM-DD" で Condition.measured_at / ConditionTag.start_date に適用。
    """
    matches = db.query(Match).filter(Match.id.in_(match_ids)).all()
    if not matches:
        raise ValueError("指定された試合が存在しません")

    # 選手 id 収集
    player_ids: set[int] = set()
    for m in matches:
        for pid in (m.player_a_id, m.player_b_id, m.partner_a_id, m.partner_b_id):
            if pid:
                player_ids.add(pid)

    players = db.query(Player).filter(Player.id.in_(player_ids)).all()
    sets_all: list[GameSet] = []
    rally_ids: list[int] = []

    for m in matches:
        sets_all.extend(db.query(GameSet).filter(GameSet.match_id == m.id).all())

    set_ids = [s.id for s in sets_all]
    rallies_all = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    rally_ids = [r.id for r in rallies_all]
    strokes_all = db.query(Stroke).filter(Stroke.rally_id.in_(rally_ids)).all() if rally_ids else []

    observations = (
        db.query(PreMatchObservation).filter(PreMatchObservation.match_id.in_(match_ids)).all()
    )
    forecasts = db.query(HumanForecast).filter(HumanForecast.match_id.in_(match_ids)).all()
    comments = db.query(Comment).filter(Comment.match_id.in_(match_ids)).all()
    bookmarks = db.query(EventBookmark).filter(EventBookmark.match_id.in_(match_ids)).all()

    # Condition / ConditionTag — 参加選手 × 期間で絞り込み
    conditions_all: list[Condition] = []
    condition_tags_all: list[ConditionTag] = []
    if player_ids:
        cq = db.query(Condition).filter(Condition.player_id.in_(player_ids))
        tq = db.query(ConditionTag).filter(ConditionTag.player_id.in_(player_ids))
        if since:
            cq = cq.filter(Condition.measured_at >= since)
            tq = tq.filter(
                (ConditionTag.end_date.is_(None) & (ConditionTag.start_date >= since))
                | (ConditionTag.end_date >= since)
            )
        if until:
            cq = cq.filter(Condition.measured_at <= until)
            tq = tq.filter(ConditionTag.start_date <= until)
        conditions_all = cq.all()
        condition_tags_all = tq.all()

    # dict 変換
    payload: dict[str, Any] = {
        "players":       [_model_to_dict(p) for p in players],
        "matches":       [_model_to_dict(m) for m in matches],
        "sets":          [_model_to_dict(s) for s in sets_all],
        "rallies":       [_model_to_dict(r) for r in rallies_all],
        "strokes":       [_model_to_dict(s) for s in strokes_all],
        "observations":  [_model_to_dict(o) for o in observations],
        "human_forecasts": [_model_to_dict(f) for f in forecasts],
        "comments":      [_model_to_dict(c) for c in comments],
        "bookmarks":     [_model_to_dict(b) for b in bookmarks],
        "conditions":    [_model_to_dict(c) for c in conditions_all],
        "condition_tags": [_model_to_dict(t) for t in condition_tags_all],
    }

    manifest = {
        "package_version": PACKAGE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.utcnow().isoformat(),
        "exported_by_device": device_id or "unknown",
        "export_mode": "match",
        "record_counts": {k: len(v) for k, v in payload.items()},
    }
    assets_manifest: list[dict] = []  # 動画は含めない（パス情報のみ）
    for m in matches:
        if m.video_local_path:
            assets_manifest.append({
                "relation": "match",
                "uuid": getattr(m, "uuid", None),
                "local_path": m.video_local_path,
                "cloud_url": None,
            })

    # ZIP 生成
    buf = io.BytesIO()
    checksums: dict[str, str] = {}

    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in payload.items():
            raw = _json_bytes(data)
            checksums[f"{name}.json"] = _checksum(raw)
            zf.writestr(f"{name}.json", raw)

        manifest_raw = _json_bytes(manifest)
        checksums["manifest.json"] = _checksum(manifest_raw)
        zf.writestr("manifest.json", manifest_raw)

        am_raw = _json_bytes(assets_manifest)
        checksums["assets_manifest.json"] = _checksum(am_raw)
        zf.writestr("assets_manifest.json", am_raw)

        checksums_raw = _json_bytes(checksums)
        zf.writestr("checksums.json", checksums_raw)

    return buf.getvalue()


# ─── エクスポート: 選手単位 ────────────────────────────────────────────────────

def export_player(
    db: Session,
    player_id: int,
    device_id: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> bytes:
    """対象選手に紐づく試合 + 期間内コンディションを .sspkg として生成。

    since/until が無ければ全期間。試合 0 件でも条件レコードが期間内にあれば
    選手単体エクスポートとして成立させる。
    """
    mq = db.query(Match).filter(
        (Match.player_a_id == player_id) | (Match.player_b_id == player_id) |
        (Match.partner_a_id == player_id) | (Match.partner_b_id == player_id)
    )
    if since:
        mq = mq.filter(Match.date >= since)
    if until:
        mq = mq.filter(Match.date <= until)
    matches = mq.all()
    match_ids = [m.id for m in matches]

    # 試合が期間内に 1 件もなくても conditions/tags があれば許可
    if match_ids:
        return export_match(db, match_ids, device_id=device_id, since=since, until=until)

    return export_conditions_only(
        db, [player_id], device_id=device_id, since=since, until=until
    )


def export_conditions_only(
    db: Session,
    player_ids: list[int],
    device_id: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> bytes:
    """選手群 × 期間の Condition/ConditionTag のみをパッケージ化 (試合無し)。"""
    if not player_ids:
        raise ValueError("player_ids が空です")

    players = db.query(Player).filter(Player.id.in_(player_ids)).all()
    cq = db.query(Condition).filter(Condition.player_id.in_(player_ids))
    tq = db.query(ConditionTag).filter(ConditionTag.player_id.in_(player_ids))
    if since:
        cq = cq.filter(Condition.measured_at >= since)
        tq = tq.filter(
            (ConditionTag.end_date.is_(None) & (ConditionTag.start_date >= since))
            | (ConditionTag.end_date >= since)
        )
    if until:
        cq = cq.filter(Condition.measured_at <= until)
        tq = tq.filter(ConditionTag.start_date <= until)
    conditions_all = cq.all()
    condition_tags_all = tq.all()

    if not conditions_all and not condition_tags_all:
        raise ValueError("指定期間にコンディション記録が見つかりません")

    payload: dict[str, Any] = {
        "players":       [_model_to_dict(p) for p in players],
        "matches":       [],
        "sets":          [],
        "rallies":       [],
        "strokes":       [],
        "observations":  [],
        "human_forecasts": [],
        "comments":      [],
        "bookmarks":     [],
        "conditions":    [_model_to_dict(c) for c in conditions_all],
        "condition_tags": [_model_to_dict(t) for t in condition_tags_all],
    }
    manifest = {
        "package_version": PACKAGE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.utcnow().isoformat(),
        "exported_by_device": device_id or "unknown",
        "export_mode": "conditions_only",
        "period": {"since": since, "until": until},
        "record_counts": {k: len(v) for k, v in payload.items()},
    }

    buf = io.BytesIO()
    checksums: dict[str, str] = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in payload.items():
            raw = _json_bytes(data)
            checksums[f"{name}.json"] = _checksum(raw)
            zf.writestr(f"{name}.json", raw)
        manifest_raw = _json_bytes(manifest)
        checksums["manifest.json"] = _checksum(manifest_raw)
        zf.writestr("manifest.json", manifest_raw)
        zf.writestr("assets_manifest.json", _json_bytes([]))
        zf.writestr("checksums.json", _json_bytes(checksums))
    return buf.getvalue()


# ─── エクスポート: Change Set ──────────────────────────────────────────────────

def export_change_set(db: Session, since: str, device_id: Optional[str] = None) -> bytes:
    """
    since（ISO 8601）以降に updated_at が変化した全レコードをエクスポート。
    仕様書 §6.3 Change Set Export。

    Args:
        since: "2026-04-01T00:00:00" 形式の日時文字列
        device_id: エクスポート端末識別子
    """
    # updated_at で比較可能なテーブルのみ収集
    def _changed(model_cls: type) -> list[Any]:
        if not hasattr(model_cls, "updated_at"):
            return []
        try:
            return db.query(model_cls).filter(
                model_cls.updated_at >= since
            ).all()
        except Exception:
            return []

    players_list    = _changed(Player)
    matches_list    = _changed(Match)
    sets_list       = _changed(GameSet)
    rallies_list    = _changed(Rally)
    strokes_list    = _changed(Stroke)
    obs_list        = _changed(PreMatchObservation)
    forecast_list   = _changed(HumanForecast)
    comment_list    = _changed(Comment)
    bookmark_list   = _changed(EventBookmark)
    conditions_list = _changed(Condition)
    # ConditionTag は updated_at を持たないため created_at で代替
    try:
        tags_list = db.query(ConditionTag).filter(ConditionTag.created_at >= since).all()
    except Exception:
        tags_list = []

    payload = {
        "players":         [_model_to_dict(p) for p in players_list],
        "matches":         [_model_to_dict(m) for m in matches_list],
        "sets":            [_model_to_dict(s) for s in sets_list],
        "rallies":         [_model_to_dict(r) for r in rallies_list],
        "strokes":         [_model_to_dict(s) for s in strokes_list],
        "observations":    [_model_to_dict(o) for o in obs_list],
        "human_forecasts": [_model_to_dict(f) for f in forecast_list],
        "comments":        [_model_to_dict(c) for c in comment_list],
        "bookmarks":       [_model_to_dict(b) for b in bookmark_list],
        "conditions":      [_model_to_dict(c) for c in conditions_list],
        "condition_tags":  [_model_to_dict(t) for t in tags_list],
    }

    manifest = {
        "package_version": PACKAGE_VERSION,
        "schema_version": SCHEMA_VERSION,
        "exported_at": datetime.utcnow().isoformat(),
        "exported_by_device": device_id or "unknown",
        "export_mode": "change_set",
        "change_set_since": since,
        "record_counts": {k: len(v) for k, v in payload.items()},
    }

    buf = io.BytesIO()
    checksums: dict[str, str] = {}
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in payload.items():
            raw = _json_bytes(data)
            checksums[f"{name}.json"] = _checksum(raw)
            zf.writestr(f"{name}.json", raw)
        manifest_raw = _json_bytes(manifest)
        checksums["manifest.json"] = _checksum(manifest_raw)
        zf.writestr("manifest.json", manifest_raw)
        zf.writestr("assets_manifest.json", _json_bytes([]))
        zf.writestr("checksums.json", _json_bytes(checksums))

    return buf.getvalue()


# ─── パッケージ検証 ────────────────────────────────────────────────────────────

def validate_package(raw: bytes) -> dict:
    """
    .sspkg バイト列を検証してマニフェストと件数情報を返す。
    チェックサム検証も実施。
    """
    try:
        buf = io.BytesIO(raw)
        with zipfile.ZipFile(buf, "r") as zf:
            names = zf.namelist()
            required = {"manifest.json", "matches.json", "players.json"}
            missing = required - set(names)
            if missing:
                return {"valid": False, "error": f"必須ファイル不足: {missing}"}

            manifest = json.loads(zf.read("manifest.json"))

            # チェックサム検証（checksums.json がある場合）
            if "checksums.json" in names:
                checksums = json.loads(zf.read("checksums.json"))
                mismatches = []
                for fname, expected in checksums.items():
                    if fname == "checksums.json":
                        continue
                    if fname in names:
                        actual = _checksum(zf.read(fname))
                        if actual != expected:
                            mismatches.append(fname)
                if mismatches:
                    return {"valid": False, "error": f"チェックサム不一致: {mismatches}"}

            counts = {}
            for key in ("players", "matches", "sets", "rallies", "strokes",
                        "observations", "human_forecasts", "comments", "bookmarks",
                        "conditions", "condition_tags"):
                fname = f"{key}.json"
                if fname in names:
                    counts[key] = len(json.loads(zf.read(fname)))
                else:
                    counts[key] = 0

            return {
                "valid": True,
                "manifest": manifest,
                "record_counts": counts,
            }
    except zipfile.BadZipFile:
        return {"valid": False, "error": "不正な ZIP ファイルです"}
    except Exception as e:
        return {"valid": False, "error": str(e)}
