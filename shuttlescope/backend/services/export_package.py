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
)

PACKAGE_VERSION = "1.0"
SCHEMA_VERSION = 8  # 同期メタデータ導入後


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

def export_match(db: Session, match_ids: list[int], device_id: Optional[str] = None) -> bytes:
    """
    指定した試合（複数可）と関連レコードを .sspkg バイト列として返す。

    含むもの:
      Match, GameSet, Rally, Stroke, 関連 Player（最小メタ）
      PreMatchObservation, HumanForecast, Comment, EventBookmark
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

def export_player(db: Session, player_id: int, device_id: Optional[str] = None) -> bytes:
    """対象選手に紐づく全試合を Match Export として生成"""
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id) |
            (Match.partner_a_id == player_id) | (Match.partner_b_id == player_id)
        )
        .all()
    )
    match_ids = [m.id for m in matches]
    if not match_ids:
        raise ValueError("指定された選手の試合が見つかりません")
    return export_match(db, match_ids, device_id=device_id)


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
                        "observations", "human_forecasts", "comments", "bookmarks"):
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
