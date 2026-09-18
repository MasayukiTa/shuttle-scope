"""ラリー管理API（/api/rallies）"""
from typing import Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Rally, GameSet, Match, Stroke
from backend.utils.sync_meta import touch
from backend.utils import response_cache
from backend.utils.match_players import players_for_set, players_for_rally

router = APIRouter()


def _rally_require_scope(request: Request, db: Session, set_id: int) -> Match:
    """rally が属する match を取得し、analyst/coach の team scope を検証する。
    admin 無条件許可、player は参加試合のみ。"""
    gs = db.get(GameSet, set_id)
    if not gs:
        raise HTTPException(status_code=404, detail="セットが見つかりません")
    match = db.get(Match, gs.match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    from backend.utils.auth import require_match_scope
    require_match_scope(request, match, db)
    return match


class RallyCreate(BaseModel):
    # 未知フィールド禁止 (mass assignment 防御)
    model_config = {"extra": "forbid"}
    set_id: int = Field(..., ge=1, le=2_147_483_647)
    rally_num: int = Field(..., ge=1, le=10000)
    # server / winner / end_type は handler 側で enum 検査されるが、
    # Pydantic 層でも長さ制限を入れて DoS / DB 列長エラーを防ぐ
    server: str = Field(..., max_length=32)
    winner: str = Field(..., max_length=32)
    end_type: str = Field(..., max_length=32)
    rally_length: int = Field(..., ge=0, le=10000)
    duration_sec: Optional[float] = Field(default=None, ge=0, le=86400)
    score_a_after: int = Field(..., ge=0, le=1000)
    score_b_after: int = Field(..., ge=0, le=1000)
    is_deuce: bool = False
    video_timestamp_start: Optional[float] = Field(default=None, ge=0, le=86400)
    video_timestamp_end: Optional[float] = Field(default=None, ge=0, le=86400)


class RallyUpdate(BaseModel):
    model_config = {"extra": "forbid"}
    winner: Optional[str] = Field(default=None, max_length=32)
    end_type: Optional[str] = Field(default=None, max_length=32)
    rally_length: Optional[int] = Field(default=None, ge=0, le=10000)
    duration_sec: Optional[float] = Field(default=None, ge=0, le=86400)
    score_a_after: Optional[int] = Field(default=None, ge=0, le=1000)
    score_b_after: Optional[int] = Field(default=None, ge=0, le=1000)
    is_deuce: Optional[bool] = None
    video_timestamp_start: Optional[float] = Field(default=None, ge=0, le=86400)
    video_timestamp_end: Optional[float] = Field(default=None, ge=0, le=86400)


def rally_to_dict(r: Rally) -> dict:
    return {
        "id": r.id,
        # uuid を返していなかったため、クライアント側の重複排除キー
        # (MobileAnnotatePage の client_uuid) が常に undefined になり、
        # 二重登録ガードが死んでいた。
        "uuid": r.uuid,
        "set_id": r.set_id,
        "rally_num": r.rally_num,
        "server": r.server,
        "winner": r.winner,
        "end_type": r.end_type,
        "rally_length": r.rally_length,
        "duration_sec": r.duration_sec,
        "score_a_after": r.score_a_after,
        "score_b_after": r.score_b_after,
        "is_deuce": r.is_deuce,
        "video_timestamp_start": r.video_timestamp_start,
        "video_timestamp_end": r.video_timestamp_end,
    }


@router.post("/rallies", status_code=201)
def create_rally(
    body: RallyCreate,
    request: Request,
    db: Session = Depends(get_db),
    idem_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """ラリー作成。

    **冪等性**: `src/utils/mobileAnnotateQueue.ts` は以前から
    `X-Idempotency-Key` を送っていたが、このルータは読んでいなかった。
    レスポンスを失った再送で同じ rally_num の行が二重に入り、
    `get_annotation_state` が `ORDER BY rally_num DESC .first()` で拾うため
    **再開時のスコアがどちらの重複を引くか次第**になっていた。

    R48: player ロール (= 選手) が自分が出場する試合に対して mobile annotation
    から書き込めるよう、明示拒否を削除。require_match_scope が
    user_can_access_match (player は match.player_a/b_id == ctx.player_id のみ可)
    で正しく弾く。他選手の試合に書き込もうとした player は依然 403。
    """
    endpoint_id = "create_rally"
    from backend.utils.auth import get_auth as _ga
    ctx_for_idem = _ga(request)
    if idem_key:
        from backend.utils.idempotency import is_valid_key, get_cached, replay_response
        if not is_valid_key(idem_key):
            raise HTTPException(status_code=400, detail="X-Idempotency-Key の形式が不正です")
        cached = get_cached(idem_key, ctx_for_idem.user_id, endpoint_id)
        if cached is not None:
            return replay_response(cached)

    _rally_require_scope(request, db, body.set_id)

    # A-5: (set_id, rally_num) は一意 (migration 0053)。sibling の POST /sets と
    # 同じく、既に同じ番号があればそれを返す。再開・再送・複数端末で同じ番号が
    # 二重に入ると、スコア推移も集計も静かに壊れる。
    existing = db.query(Rally).filter(
        Rally.set_id == body.set_id,
        Rally.rally_num == body.rally_num,
        Rally.deleted_at.is_(None),
    ).first()
    if existing:
        response = {"success": True, "data": rally_to_dict(existing)}
        if idem_key:
            from backend.utils.idempotency import store
            store(idem_key, ctx_for_idem.user_id, endpoint_id, response, status_code=201)
        return response

    rally = Rally(**body.model_dump())
    touch(rally)
    db.add(rally)
    try:
        db.commit()
    except IntegrityError:
        # 上の検査と INSERT の間に別リクエストが入った場合。
        # 一意インデックスが最終的な砦なので、ここは勝った側の行を返す。
        db.rollback()
        existing = db.query(Rally).filter(
            Rally.set_id == body.set_id,
            Rally.rally_num == body.rally_num,
            Rally.deleted_at.is_(None),
        ).first()
        if existing is None:
            raise
        response = {"success": True, "data": rally_to_dict(existing)}
        if idem_key:
            from backend.utils.idempotency import store
            store(idem_key, ctx_for_idem.user_id, endpoint_id, response, status_code=201)
        return response
    # set_id から辿って試合の関与選手のみ無効化
    response_cache.bump_players(players_for_set(db, body.set_id))
    db.refresh(rally)
    response = {"success": True, "data": rally_to_dict(rally)}
    if idem_key:
        from backend.utils.idempotency import store
        store(idem_key, ctx_for_idem.user_id, endpoint_id, response, status_code=201)
    return response


@router.put("/rallies/{rally_id}")
def update_rally(rally_id: int, body: RallyUpdate, request: Request, db: Session = Depends(get_db)):
    """ラリー更新。R48: player は自分の試合に限り更新可 (scope 経由判定)。"""
    rally = db.get(Rally, rally_id)
    if not rally:
        raise HTTPException(status_code=404, detail="ラリーが見つかりません")
    _rally_require_scope(request, db, rally.set_id)
    from backend.utils.db_update import apply_update
    apply_update(rally, body.model_dump(exclude_unset=True))
    touch(rally)
    db.commit()
    # 対象 rally の試合の関与選手のみ無効化
    response_cache.bump_players(players_for_set(db, rally.set_id))
    db.refresh(rally)
    return {"success": True, "data": rally_to_dict(rally)}


@router.delete("/rallies/{rally_id}")
def delete_rally(rally_id: int, request: Request, db: Session = Depends(get_db)):
    """ラリー削除（アンドゥ用）。R48: player は自分の試合に限り delete 可。"""
    rally = db.get(Rally, rally_id)
    if not rally:
        raise HTTPException(status_code=404, detail="ラリーが見つかりません")
    _rally_require_scope(request, db, rally.set_id)
    # 削除前に関与選手を控える
    affected_players = players_for_set(db, rally.set_id)
    db.delete(rally)
    db.commit()
    response_cache.bump_players(affected_players)
    return {"success": True, "data": {"id": rally_id}}


@router.get("/rallies/match/{match_id}")
def get_rallies_for_match(match_id: int, request: Request, db: Session = Depends(get_db)):
    """試合のラリー一覧（再開用）。

    モバイル注釈は「既に入っているラリー」を取れないと、リロードのたびに
    スコアが 0-0 に戻り rally_num が 1 から重複する。これまでこの経路の
    エンドポイントが存在せず (クライアントは無い `GET /rallies?match_id=`
    を叩いて 405 を受けていた)、一覧は常に空だった。

    scope は sibling の `GET /sets/match/{match_id}` と同じ考え方で、
    match 単位で検証する。
    """
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    from backend.utils.auth import require_match_scope
    require_match_scope(request, match, db)

    rallies = (
        db.query(Rally)
        .join(GameSet, Rally.set_id == GameSet.id)
        .filter(GameSet.match_id == match_id)
        .order_by(GameSet.set_num, Rally.rally_num)
        .all()
    )
    return {"success": True, "data": [rally_to_dict(r) for r in rallies]}


@router.get("/annotation/{match_id}/state")
def get_annotation_state(match_id: int, request: Request, db: Session = Depends(get_db)):
    """アノテーション現在状態（再開用）"""
    from backend.utils.auth import get_auth as _ga
    from fastapi import HTTPException as _HE
    _ctx = _ga(request)
    if _ctx.role is None:
        from backend.utils.control_plane import allow_legacy_header_auth
        if not allow_legacy_header_auth(request):
            raise _HE(status_code=401, detail="認証が必要です")
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    from backend.utils.auth import user_can_access_match
    if not _ctx.is_admin and not user_can_access_match(_ctx, match):
        raise HTTPException(status_code=404, detail="試合が見つかりません")

    # 最後のセットと最後のラリーを取得
    last_set = db.query(GameSet).filter(
        GameSet.match_id == match_id
    ).order_by(GameSet.set_num.desc()).first()

    if not last_set:
        return {
            "success": True,
            "data": {
                "match_id": match_id,
                "current_set_num": 1,
                "current_rally_num": 1,
                "score_a": 0,
                "score_b": 0,
                "next_server": match.initial_server,
            }
        }

    last_rally = db.query(Rally).filter(
        Rally.set_id == last_set.id
    ).order_by(Rally.rally_num.desc()).first()

    if last_rally:
        return {
            "success": True,
            "data": {
                "match_id": match_id,
                "current_set_num": last_set.set_num,
                "current_rally_num": last_rally.rally_num + 1,
                "score_a": last_rally.score_a_after,
                "score_b": last_rally.score_b_after,
                # A-2: サーブ権を返していなかったため、途中まで入力した試合を
                # 開き直すと次のラリーが必ず player_a のサーブで始まり、
                # 以降の打者が全部ずれていた。バドミントンでは前ラリーの
                # 勝者が次のサーバなので、それをそのまま返す。
                "next_server": last_rally.winner,
            }
        }

    # このセットにまだラリーが無い = セット頭。前セットの勝者がサーバ。
    # 前セットも無ければ試合の初期サーバ。
    prev_set = db.query(GameSet).filter(
        GameSet.match_id == match_id,
        GameSet.set_num < last_set.set_num,
    ).order_by(GameSet.set_num.desc()).first()
    next_server = (prev_set.winner if prev_set and prev_set.winner else match.initial_server)

    return {
        "success": True,
        "data": {
            "match_id": match_id,
            "current_set_num": last_set.set_num,
            "current_rally_num": 1,
            "score_a": 0,
            "score_b": 0,
            "next_server": next_server,
        }
    }


@router.post("/annotation/{match_id}/undo")
def undo_last_stroke(match_id: int, request: Request, db: Session = Depends(get_db)):
    """最後のストロークを取り消し"""
    from backend.utils.auth import get_auth as _ga, user_can_access_match
    from fastapi import HTTPException as _HE
    _ctx = _ga(request)
    if _ctx.role is None:
        from backend.utils.control_plane import allow_legacy_header_auth
        if not allow_legacy_header_auth(request):
            raise _HE(status_code=401, detail="認証が必要です")
    if _ctx.is_player:
        raise _HE(status_code=403, detail="この操作を行う権限がありません")
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    if not _ctx.is_admin and not user_can_access_match(_ctx, match):
        raise HTTPException(status_code=404, detail="試合が見つかりません")

    last_set = db.query(GameSet).filter(
        GameSet.match_id == match_id
    ).order_by(GameSet.set_num.desc()).first()

    if not last_set:
        raise HTTPException(status_code=400, detail="アンドゥするデータがありません")

    last_rally = db.query(Rally).filter(
        Rally.set_id == last_set.id
    ).order_by(Rally.rally_num.desc()).first()

    if not last_rally:
        raise HTTPException(status_code=400, detail="アンドゥするラリーがありません")

    last_stroke = db.query(Stroke).filter(
        Stroke.rally_id == last_rally.id
    ).order_by(Stroke.stroke_num.desc()).first()

    if last_stroke:
        db.delete(last_stroke)
        db.commit()
        # match_id は既に確定しているので、そこから関与選手のみ無効化
        from backend.utils.match_players import players_for_match
        response_cache.bump_players(players_for_match(db, match_id))
        return {"success": True, "data": {"deleted_stroke_id": last_stroke.id}}

    raise HTTPException(status_code=400, detail="アンドゥするストロークがありません")
