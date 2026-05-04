"""E — データ資産化 API（/api/export, /api/import）

.sspkg（ZIP バイナリ同期フォーマット）とは別に、
人間が読める・学習データに使える JSON パッケージを入出力する。

エンドポイント:
  GET  /api/export/package?match_id=X           → match_YYYYMMDD_vs_OPPONENT.json
  POST /api/import/package                       → JSON パッケージをインポート
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, GameSet, Rally, Stroke, Player
from backend.utils.auth import get_auth, check_export_match_scope, require_analyst

router = APIRouter()
logger = logging.getLogger(__name__)

PACKAGE_VERSION = "1.0"


# ─── ヘルパー ─────────────────────────────────────────────────────────────────

def _dt(v: Any) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.isoformat()
    return str(v)


def _match_dict(m: Match) -> dict:
    return {
        "id": m.id,
        "uuid": m.uuid,
        "tournament": m.tournament,
        "tournament_level": m.tournament_level,
        "round": m.round,
        "date": _dt(m.date),
        "venue": m.venue,
        "format": m.format,
        "player_a_id": m.player_a_id,
        "player_b_id": m.player_b_id,
        "partner_a_id": m.partner_a_id,
        "partner_b_id": m.partner_b_id,
        "result": m.result,
        "final_score": m.final_score,
        "annotation_status": m.annotation_status,
        "competition_type": m.competition_type,
        "notes": m.notes,
    }


def _player_dict(p: Player) -> dict:
    return {
        "id": p.id,
        "uuid": p.uuid,
        "name": p.name,
        "name_en": p.name_en,
        "team": p.team,
        "nationality": p.nationality,
        "dominant_hand": p.dominant_hand,
        "birth_year": p.birth_year,
    }


def _set_dict(s: GameSet) -> dict:
    return {
        "id": s.id,
        "uuid": s.uuid,
        "set_num": s.set_num,
        "winner": s.winner,
        "score_a": s.score_a,
        "score_b": s.score_b,
        "duration_min": s.duration_min,
        "is_deuce": s.is_deuce,
    }


def _rally_dict(r: Rally) -> dict:
    return {
        "id": r.id,
        "uuid": r.uuid,
        "set_id": r.set_id,
        "rally_num": r.rally_num,
        "server": r.server,
        "winner": r.winner,
        "end_type": r.end_type,
        "rally_length": r.rally_length,
        "duration_sec": r.duration_sec,
        "score_a_before": r.score_a_before,
        "score_b_before": r.score_b_before,
        "score_a_after": r.score_a_after,
        "score_b_after": r.score_b_after,
        "is_deuce": r.is_deuce,
        "video_timestamp_start": r.video_timestamp_start,
        "video_timestamp_end": r.video_timestamp_end,
        "is_skipped": r.is_skipped,
        "annotation_mode": r.annotation_mode,
    }


def _stroke_dict(s: Stroke) -> dict:
    return {
        "id": s.id,
        "uuid": s.uuid,
        "rally_id": s.rally_id,
        "stroke_num": s.stroke_num,
        "player": s.player,
        "shot_type": s.shot_type,
        "shot_quality": s.shot_quality,
        "hit_x": s.hit_x,
        "hit_y": s.hit_y,
        "land_x": s.land_x,
        "land_y": s.land_y,
        "player_x": s.player_x,
        "player_y": s.player_y,
        "opponent_x": s.opponent_x,
        "opponent_y": s.opponent_y,
        "hit_zone": s.hit_zone,
        "land_zone": s.land_zone,
        "is_backhand": s.is_backhand,
        "is_around_head": s.is_around_head,
        "is_cross": s.is_cross,
        "above_net": s.above_net,
        "timestamp_sec": s.timestamp_sec,
        "return_quality": s.return_quality,
        "contact_height": s.contact_height,
        "contact_zone": s.contact_zone,
        "epv": s.epv,
        "source_method": s.source_method,
    }


# ─── エクスポート ──────────────────────────────────────────────────────────────

@router.get("/export/package")
def export_package(match_id: int, request: Request, db: Session = Depends(get_db)):
    """試合データを JSON パッケージとしてダウンロードする。

    レスポンスボディ形式:
    {
      "version": "1.0",
      "exported_at": "...",
      "match": {...},
      "players": [...],
      "sets": [...],
      "rallies": [...],
      "strokes": [...]
    }
    """
    ctx = get_auth(request)

    # Phase B2: X-Idempotency-Key ヘッダで二重 export 防止 + access_log の重複記録防止
    # 同じキーでの 2 回目以降は前回の署名済みパッケージをそのまま返す（nonce 再利用なし）
    idem_key = request.headers.get("X-Idempotency-Key", "").strip()
    endpoint_id = f"export_package:{match_id}"
    if idem_key:
        from backend.utils.idempotency import is_valid_key, get_cached, replay_response
        if not is_valid_key(idem_key):
            raise HTTPException(status_code=400, detail="X-Idempotency-Key の形式が不正です")
        cached = get_cached(idem_key, ctx.user_id, endpoint_id)
        if cached is not None:
            cached_payload = replay_response(cached)
            cached_body = json.dumps(cached_payload, ensure_ascii=False, indent=2).encode("utf-8")
            return Response(
                content=cached_body,
                media_type="application/json",
                headers={
                    "Content-Disposition": "attachment; filename=\"replay.json\"",
                    "X-Idempotent-Replay": "1",
                },
            )

    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    check_export_match_scope(ctx, [match], db)

    # プレイヤー収集（重複なし）
    player_ids = {match.player_a_id, match.player_b_id}
    if match.partner_a_id:
        player_ids.add(match.partner_a_id)
    if match.partner_b_id:
        player_ids.add(match.partner_b_id)
    player_ids.discard(None)
    players = db.query(Player).filter(Player.id.in_(player_ids)).all()

    # セット
    sets = db.query(GameSet).filter(GameSet.match_id == match_id).order_by(GameSet.set_num).all()
    set_ids = [s.id for s in sets]

    # ラリー
    rallies = (
        db.query(Rally)
        .filter(Rally.set_id.in_(set_ids), Rally.deleted_at.is_(None))
        .order_by(Rally.set_id, Rally.rally_num)
        .all()
    )
    rally_ids = [r.id for r in rallies]

    # ストローク
    strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(rally_ids), Stroke.deleted_at.is_(None))
        .order_by(Stroke.rally_id, Stroke.stroke_num)
        .all()
    ) if rally_ids else []

    payload = {
        "version": PACKAGE_VERSION,
        "exported_at": datetime.utcnow().isoformat(),
        "match": _match_dict(match),
        "players": [_player_dict(p) for p in players],
        "sets": [_set_dict(s) for s in sets],
        "rallies": [_rally_dict(r) for r in rallies],
        "strokes": [_stroke_dict(s) for s in strokes],
    }

    # Phase A3: HMAC 署名 + 有効期限 24h + nonce を埋め込み、改ざん検知 + 1回利用化
    from backend.utils.export_signing import sign_package
    payload = sign_package(payload)

    # access_log に記録（漏洩追跡用）
    try:
        from backend.utils.access_log import log_access
        log_access(
            db, "export_package_created",
            user_id=ctx.user_id,
            resource_type="match",
            resource_id=match_id,
            details={
                "actor_role": ctx.role,
                "nonce": payload.get("_nonce"),
                "expires_at": payload.get("_expires_at"),
            },
        )
    except Exception as exc:
        import logging as _lg
        _lg.getLogger(__name__).warning("[export] access_log failed: %s", exc)

    # ファイル名: match_YYYYMMDD_vs_opponent.json
    date_str = match.date.strftime("%Y%m%d") if match.date else "unknown"
    opp = db.get(Player, match.player_b_id)
    opp_name = (opp.name if opp else "opponent").replace(" ", "_").replace("/", "-")[:20]
    filename = f"match_{date_str}_vs_{opp_name}.json"

    # HTTP ヘッダは latin-1 限定なので RFC 5987 形式で UTF-8 ファイル名を提供する。
    # ASCII フォールバック名と filename*=UTF-8''... の両方を含めて旧・新ブラウザ両対応。
    from urllib.parse import quote as _urlquote
    ascii_fallback = filename.encode("ascii", errors="replace").decode("ascii").replace("?", "_")
    encoded = _urlquote(filename, safe="")
    disposition = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{encoded}"

    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    # idempotency キャッシュへ保存（同じキーでの再要求は同じパッケージを返す）
    if idem_key:
        from backend.utils.idempotency import store
        store(idem_key, ctx.user_id, endpoint_id, payload, status_code=200)

    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": disposition},
    )


# ─── インポート ────────────────────────────────────────────────────────────────

@router.post("/import/package")
async def import_package_endpoint(request: Request, db: Session = Depends(get_db)):
    """JSON パッケージをインポートする（analyst / admin 限定）。

    クエリパラメータ:
      force=true  既存 match.uuid が存在する場合に上書きする

    リクエストボディ: export_package が生成した JSON
    """
    require_analyst(request)
    force = request.query_params.get("force", "false").lower() == "true"

    try:
        body = await request.body()
        pkg = json.loads(body)
    except Exception:
        raise HTTPException(status_code=422, detail="不正な JSON フォーマットです")

    if pkg.get("version") != PACKAGE_VERSION:
        raise HTTPException(
            status_code=422,
            detail=f"パッケージバージョン '{pkg.get('version')}' に対応していません（期待値: {PACKAGE_VERSION}）",
        )

    # Phase A3: HMAC 署名 + 有効期限 + nonce 重複の検証
    from backend.utils.export_signing import verify_package, consume_nonce
    ok, reason = verify_package(pkg, db)
    if not ok:
        raise HTTPException(
            status_code=403,
            detail=f"パッケージ検証失敗: {reason}",
        )
    # 検証成功後に nonce を消費（二重インポート防止）
    nonce = pkg.get("_nonce")
    if nonce:
        consume_nonce(db, nonce)

    match_data = pkg.get("match")
    if not match_data:
        raise HTTPException(status_code=422, detail="match データが含まれていません")

    # ── Player 解決: name マッチング → 既存再利用 or 新規作成 ──────────────
    player_id_map: dict[int, int] = {}  # pkg 内 player.id → ローカル DB id
    for p_data in pkg.get("players", []):
        existing = db.query(Player).filter(Player.uuid == p_data["uuid"]).first()
        if not existing:
            existing = db.query(Player).filter(Player.name == p_data["name"]).first()
        if existing:
            player_id_map[p_data["id"]] = existing.id
        else:
            new_player = Player(
                name=p_data["name"],
                name_en=p_data.get("name_en"),
                team=p_data.get("team"),
                nationality=p_data.get("nationality"),
                dominant_hand=p_data.get("dominant_hand"),
                birth_year=p_data.get("birth_year"),
            )
            db.add(new_player)
            db.flush()
            player_id_map[p_data["id"]] = new_player.id

    # ── Match 解決 ────────────────────────────────────────────────────────────
    existing_match = db.query(Match).filter(Match.uuid == match_data["uuid"]).first()
    if existing_match and not force:
        return {
            "success": False,
            "conflict": True,
            "message": "同じ UUID の試合が既に存在します。force=true で上書きできます。",
            "existing_match_id": existing_match.id,
        }

    if existing_match and force:
        # 既存の子データを削除してから上書き
        _cascade_delete_match(db, existing_match.id)
        match_obj = existing_match
    else:
        match_obj = Match()
        db.add(match_obj)

    _apply_match_data(match_obj, match_data, player_id_map)
    db.flush()

    # ── Sets ─────────────────────────────────────────────────────────────────
    set_id_map: dict[int, int] = {}
    for s_data in pkg.get("sets", []):
        gs = GameSet(
            match_id=match_obj.id,
            set_num=s_data["set_num"],
            winner=s_data.get("winner"),
            score_a=s_data.get("score_a", 0),
            score_b=s_data.get("score_b", 0),
            duration_min=s_data.get("duration_min"),
            is_deuce=s_data.get("is_deuce", False),
        )
        db.add(gs)
        db.flush()
        set_id_map[s_data["id"]] = gs.id

    # ── Rallies ───────────────────────────────────────────────────────────────
    rally_id_map: dict[int, int] = {}
    for r_data in pkg.get("rallies", []):
        local_set_id = set_id_map.get(r_data["set_id"])
        if not local_set_id:
            continue
        r = Rally(
            set_id=local_set_id,
            rally_num=r_data["rally_num"],
            server=r_data["server"],
            winner=r_data["winner"],
            end_type=r_data["end_type"],
            rally_length=r_data.get("rally_length", 0),
            duration_sec=r_data.get("duration_sec"),
            score_a_before=r_data.get("score_a_before", 0),
            score_b_before=r_data.get("score_b_before", 0),
            score_a_after=r_data.get("score_a_after", 0),
            score_b_after=r_data.get("score_b_after", 0),
            is_deuce=r_data.get("is_deuce", False),
            video_timestamp_start=r_data.get("video_timestamp_start"),
            video_timestamp_end=r_data.get("video_timestamp_end"),
            is_skipped=r_data.get("is_skipped", False),
            annotation_mode=r_data.get("annotation_mode"),
        )
        db.add(r)
        db.flush()
        rally_id_map[r_data["id"]] = r.id

    # ── Strokes ───────────────────────────────────────────────────────────────
    stroke_count = 0
    for s_data in pkg.get("strokes", []):
        local_rally_id = rally_id_map.get(s_data["rally_id"])
        if not local_rally_id:
            continue
        s = Stroke(
            rally_id=local_rally_id,
            stroke_num=s_data["stroke_num"],
            player=s_data["player"],
            shot_type=s_data["shot_type"],
            shot_quality=s_data.get("shot_quality"),
            hit_x=s_data.get("hit_x"),
            hit_y=s_data.get("hit_y"),
            land_x=s_data.get("land_x"),
            land_y=s_data.get("land_y"),
            player_x=s_data.get("player_x"),
            player_y=s_data.get("player_y"),
            opponent_x=s_data.get("opponent_x"),
            opponent_y=s_data.get("opponent_y"),
            hit_zone=s_data.get("hit_zone"),
            land_zone=s_data.get("land_zone"),
            is_backhand=s_data.get("is_backhand", False),
            is_around_head=s_data.get("is_around_head", False),
            is_cross=s_data.get("is_cross", False),
            above_net=s_data.get("above_net"),
            timestamp_sec=s_data.get("timestamp_sec"),
            return_quality=s_data.get("return_quality"),
            contact_height=s_data.get("contact_height"),
            contact_zone=s_data.get("contact_zone"),
            epv=s_data.get("epv"),
            source_method=s_data.get("source_method"),
        )
        db.add(s)
        stroke_count += 1

    db.commit()

    return {
        "success": True,
        "match_id": match_obj.id,
        "sets_imported": len(set_id_map),
        "rallies_imported": len(rally_id_map),
        "strokes_imported": stroke_count,
        "players_resolved": len(player_id_map),
    }


# ─── 内部ヘルパー ──────────────────────────────────────────────────────────────

def _cascade_delete_match(db: Session, match_id: int) -> None:
    """試合に紐づく sets / rallies / strokes を削除（force 上書き用）"""
    sets = db.query(GameSet).filter(GameSet.match_id == match_id).all()
    for s in sets:
        rallies = db.query(Rally).filter(Rally.set_id == s.id).all()
        for r in rallies:
            db.query(Stroke).filter(Stroke.rally_id == r.id).delete()
            db.delete(r)
        db.delete(s)
    db.flush()


def _apply_match_data(match_obj: Match, data: dict, player_id_map: dict) -> None:
    match_obj.uuid = data["uuid"]
    match_obj.tournament = data["tournament"]
    match_obj.tournament_level = data["tournament_level"]
    match_obj.round = data["round"]
    if data.get("date"):
        from datetime import date
        match_obj.date = date.fromisoformat(data["date"])
    match_obj.venue = data.get("venue")
    match_obj.format = data["format"]
    match_obj.player_a_id = player_id_map.get(data["player_a_id"], data["player_a_id"])
    match_obj.player_b_id = player_id_map.get(data["player_b_id"], data["player_b_id"])
    match_obj.partner_a_id = player_id_map.get(data["partner_a_id"]) if data.get("partner_a_id") else None
    match_obj.partner_b_id = player_id_map.get(data["partner_b_id"]) if data.get("partner_b_id") else None
    match_obj.result = data["result"]
    match_obj.final_score = data.get("final_score")
    match_obj.annotation_status = data.get("annotation_status", "complete")
    match_obj.competition_type = data.get("competition_type")
    match_obj.notes = data.get("notes")
