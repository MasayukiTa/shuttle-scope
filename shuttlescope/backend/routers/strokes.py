"""ストローク管理API（/api/strokes）"""
import logging
from typing import Literal, Optional
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.exc import DBAPIError, DisconnectionError, IntegrityError, InterfaceError, OperationalError
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Stroke, Rally, GameSet, Match
from backend.utils.validators import validate_stroke, validate_rally
from backend.utils.sync_meta import touch
from backend.analysis.shot_taxonomy import canonicalize as canonicalize_shot
from backend.utils import response_cache
from backend.utils.match_players import players_for_match, players_for_rally
from backend.analysis.analysis_population import IN_PROGRESS_END_TYPE

logger = logging.getLogger(__name__)
router = APIRouter()


def _stroke_require_scope(request: Request, db: Session, rally_id: int) -> Match:
    """stroke が属する match を辿り team scope を検証する。"""
    rally = db.get(Rally, rally_id)
    if not rally:
        raise HTTPException(status_code=404, detail="ラリーが見つかりません")
    gs = db.get(GameSet, rally.set_id)
    if not gs:
        raise HTTPException(status_code=404, detail="ゲームが見つかりません")
    match = db.get(Match, gs.match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    # R48: player ロールの明示拒否を撤去。require_match_scope が
    # user_can_access_match (player は自分の試合だけ) で正しく弾く。
    from backend.utils.auth import require_match_scope
    require_match_scope(request, match, db)
    return match


# The mobile Pass 2 / Pass 3 flow saves two values that are not in the canonical shot
# vocabulary: 'serve' for the first stroke and a placeholder for the last hit that Pass 3
# classifies later (see Pass2ServeFinal.tsx / Pass3ShotDetail.tsx). They are the only
# non-canonical values the single-stroke API keeps; every other value is canonicalized the
# same way /strokes/batch does, so a raw client string never reaches the database.
PENDING_FINAL_SHOT_TYPE = "__final_pending"
_MOBILE_SHOT_TYPES = frozenset({"serve", PENDING_FINAL_SHOT_TYPE})


def _normalize_shot_type(value: str) -> str:
    if value in _MOBILE_SHOT_TYPES:
        return value
    return canonicalize_shot(value)


def _human_land_zone_source(land_zone: Optional[str]) -> Optional[str]:
    """人が API 経由で land_zone を指定したときの入力元。値が空なら記録しない。"""
    return "human" if land_zone else None


# 要望6 (仙台大 2026-11-05): ショットの意図タグの固定語彙。
# shot_type / hit_zone_source と同じ思想で、自由文字列を DB に素通しさせない
# (任意のクライアントが綴り違いや未知の値を保存でき、後の集計・AI 分析が壊れる)。
# 未知の非空値は 'other' に寄せる。空・None は「意図未入力」として NULL のまま。
INTENT_TAGS = frozenset(
    {"deep", "net", "body", "sideline", "cross", "deception", "clear_safe", "other"}
)


def _canonicalize_intent_tag(value: Optional[str]) -> Optional[str]:
    """意図タグを固定語彙へ正規化する。空なら NULL、未知の非空値は 'other'。"""
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    return v if v in INTENT_TAGS else "other"


def _clean_intent_note(value: Optional[str]) -> Optional[str]:
    """自由記述の前後空白を除き、空なら NULL。長さは Pydantic 層で制限済み。"""
    if value is None:
        return None
    v = value.strip()
    return v or None


class StrokeData(BaseModel):
    # 未知フィールド silent drop 遮断
    model_config = {"extra": "forbid"}
    stroke_num: int = Field(..., ge=1, le=10000)
    # 文字列は handler 側で enum 検査されるが Pydantic 層でも DoS / DB 列長保護
    player: str = Field(..., max_length=32)
    shot_type: str = Field(..., max_length=64)
    shot_quality: Optional[str] = Field(default=None, max_length=32)
    hit_x: Optional[float] = None
    hit_y: Optional[float] = None
    land_x: Optional[float] = None
    land_y: Optional[float] = None
    hit_zone: Optional[str] = Field(default=None, max_length=32)
    # 打点の由来。**自由文字列だったので、どの値でも書けた** (任意のクライアントが
    # 'manual' を名乗れたし、綴り違いも黙って保存された)。語彙を固定する。
    #   'manual'       = 人が明示的に指定した
    #   'carried_over' = 直前の打球の着地点を引き継いだ (人間由来の推測)
    #   'cv'           = CV の出力
    # 'carried_over' は 2026-09-18 に追加。それまでこの経路は 'cv' を名乗っており、
    # **CV を一度も走らせていない試合でも 2 打目以降が機械由来として残っていた**。
    hit_zone_source: Optional[Literal["manual", "carried_over", "cv"]] = None
    # Phase A: CV 元推定値 (override 後も保持)
    hit_zone_cv_original: Optional[str] = Field(default=None, max_length=32)
    land_zone: Optional[str] = Field(default=None, max_length=32)
    is_backhand: bool = False
    is_around_head: bool = False
    above_net: Optional[bool] = None
    is_cross: bool = False
    timestamp_sec: Optional[float] = None
    # N-002: 空間座標拡張
    opponent_contact_x: Optional[float] = None
    opponent_contact_y: Optional[float] = None
    player_contact_x:   Optional[float] = None
    player_contact_y:   Optional[float] = None
    return_target_x:    Optional[float] = None
    return_target_y:    Optional[float] = None
    # G2: 返球品質・打点高さ（ストローク確定後オプション）
    return_quality: Optional[str] = Field(default=None, max_length=32)   # attack/neutral/defensive/emergency
    contact_height: Optional[str] = Field(default=None, max_length=32)   # overhead/side/underhand/scoop
    # 移動系コンテキスト（4.1 Movement Features）
    contact_zone: Optional[str] = Field(default=None, max_length=32)     # front/mid/rear
    movement_burden: Optional[str] = Field(default=None, max_length=32)  # low/medium/high
    movement_direction: Optional[str] = Field(default=None, max_length=32)  # forward/backward/lateral
    # 要望6: ショットの意図メモ（選択式タグ + 短い自由記述）。どちらも任意。
    # タグはハンドラ側で固定語彙へ正規化する (未知値は 'other')。
    intent_tag: Optional[str] = Field(default=None, max_length=32)
    intent_note: Optional[str] = Field(default=None, max_length=200)
    # アノテーション記録方式 (manual / assisted / corrected)
    source_method: Optional[str] = Field(default=None, max_length=32)


class RallyData(BaseModel):
    model_config = {"extra": "forbid"}
    set_id: int = Field(..., ge=1, le=2_147_483_647)
    rally_num: int = Field(..., ge=1, le=10000)
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
    is_skipped: bool = False
    # アノテーション記録方式 (manual_record / assisted_record)
    annotation_mode: Optional[str] = Field(default=None, max_length=32)
    # レビューステータス (pending / completed)
    review_status: Optional[str] = Field(default=None, max_length=32)
    # 同期端末識別子。replace_strokes による置き換え時の所有者判定に使う。
    # Rally に作成者 (user_id) 列が無いため、同じ端末 (= 実質同じユーザー) からの
    # 書き込みに置き換えを限定する代理キーとして用いる。未指定 (None) の場合は
    # require_match_scope 通過 (= 同じ試合) をもって許可する (固定条件のフォールバック)。
    source_device_id: Optional[str] = Field(default=None, max_length=100)


class BatchSaveRequest(BaseModel):
    """ラリー確定時の一括保存リクエスト"""
    rally: RallyData
    strokes: list[StrokeData]
    # 途中保存 (mid-rally autosave) 対応。
    #   replace_strokes=True: 既存ラリーがあるとき already_saved で捨てず、既存の
    #     非削除ストロークを soft delete して送られたストロークを入れ直し、ラリーの
    #     項目 (勝者・終了種別・スコア) も更新する。uq_strokes_rally_id_stroke_num_active
    #     は非削除だけに掛かるので、soft delete してから入れ直せば当たらない。
    #   final=False (途中保存): 送られたストローク数が既存の非削除数より少ない場合は、
    #     古い途中保存が遅れて着いたものとみなし何も変えず既存を返す (確定後に縮めない)。
    # replace_strokes=False (既定) のときは従来どおり already_saved を返す。
    replace_strokes: bool = False
    final: bool = True


def stroke_to_dict(s: Stroke) -> dict:
    return {
        "id": s.id,
        "rally_id": s.rally_id,
        "stroke_num": s.stroke_num,
        "player": s.player,
        "shot_type": s.shot_type,
        "shot_quality": s.shot_quality,
        "hit_x": s.hit_x,
        "hit_y": s.hit_y,
        "land_x": s.land_x,
        "land_y": s.land_y,
        "hit_zone": s.hit_zone,
        "hit_zone_source": s.hit_zone_source,
        "hit_zone_cv_original": s.hit_zone_cv_original,
        "land_zone": s.land_zone,
        "land_zone_source": s.land_zone_source,
        "is_backhand": s.is_backhand,
        "is_around_head": s.is_around_head,
        "above_net": s.above_net,
        "is_cross": s.is_cross,
        "timestamp_sec": s.timestamp_sec,
        "epv": s.epv,
        "shot_influence": s.shot_influence,
        "opponent_contact_x": s.opponent_contact_x,
        "opponent_contact_y": s.opponent_contact_y,
        "player_contact_x":   s.player_contact_x,
        "player_contact_y":   s.player_contact_y,
        "return_target_x":    s.return_target_x,
        "return_target_y":    s.return_target_y,
        "return_quality":     s.return_quality,
        "contact_height":     s.contact_height,
        "contact_zone":       s.contact_zone,
        "movement_burden":    s.movement_burden,
        "movement_direction": s.movement_direction,
        "intent_tag":         s.intent_tag,
        "intent_note":        s.intent_note,
        "source_method":      s.source_method,
    }


def _batch_existing_response(
    db: Session,
    existing: Rally,
    idem_key: Optional[str],
    user_id,
    endpoint_id: str,
) -> dict:
    """同じ (set_id, rally_num) のラリーが既にある再送時の応答。

    初回保存と同じ形 ({"success": True, "data": {"rally_id", "stroke_count"}}) を返す。
    打球は足し直さず、既存の非削除ストローク数をそのまま返す。
    """
    stroke_count = (
        db.query(Stroke)
        .filter(Stroke.rally_id == existing.id, Stroke.deleted_at.is_(None))
        .count()
    )
    response = {
        "success": True,
        "data": {
            "rally_id": existing.id,
            "stroke_count": stroke_count,
            "already_saved": True,
        },
    }
    if idem_key:
        from backend.utils.idempotency import store
        store(idem_key, user_id, endpoint_id, response, status_code=201)
    return response


def _insert_strokes_for_rally(db: Session, rally_id: int, strokes: list["StrokeData"]) -> list[Stroke]:
    """送られたストロークを rally_id に新規挿入する。batch 初回保存と同じ正規化を使う。"""
    saved = []
    for stroke_data in strokes:
        stroke_dict = stroke_data.model_dump()
        stroke_dict["shot_type"] = canonicalize_shot(stroke_dict.get("shot_type", "other"))
        stroke_dict["intent_tag"] = _canonicalize_intent_tag(stroke_dict.get("intent_tag"))
        stroke_dict["intent_note"] = _clean_intent_note(stroke_dict.get("intent_note"))
        stroke = Stroke(
            rally_id=rally_id,
            land_zone_source=_human_land_zone_source(stroke_dict.get("land_zone")),
            **stroke_dict,
        )
        db.add(stroke)
        saved.append(stroke)
    return saved


def _batch_replace_existing(
    db: Session,
    existing: Rally,
    body: BatchSaveRequest,
    game_set: GameSet,
    idem_key: Optional[str],
    user_id,
    endpoint_id: str,
) -> dict:
    """replace_strokes=True の既存ラリーへの途中/最終保存。

    既存の非削除ストロークを soft delete して送られたストロークを入れ直し、ラリーの
    項目 (勝者・終了種別・スコア・長さ) を更新する。uq_strokes_rally_id_stroke_num_active
    は非削除だけに掛かるので、soft delete してから入れ直せば当たらない。

    別端末が同じ (set_id, rally_num) を作った場合に上書きしないよう、置き換えは
    require_match_scope を通過した同じ試合の同じユーザーの書き込みに限る (呼び出し元で
    検証済み)。Rally に作成者列が無いため、これがスコープ上の作成者一致にあたる。
    """
    from datetime import datetime
    # 所有者ガード: 別端末 (= 別ユーザー) が作ったラリーを上書きしない。
    # Rally に作成者 (user_id) 列が無いため source_device_id を代理キーとする。
    # 既存と今回の device が両方わかっていて食い違う場合だけ拒否する。どちらかが
    # 未設定なら require_match_scope 通過 (同じ試合) を根拠に許可する (固定条件の
    # 「できなければ同じ試合の同じユーザーの書き込みに限る」フォールバック)。
    incoming_device = body.rally.source_device_id
    if (
        existing.source_device_id
        and incoming_device
        and existing.source_device_id != incoming_device
    ):
        # 別端末からの置き換え要求は捨て、既存ラリーを already_saved として返す。
        return _batch_existing_response(db, existing, idem_key, user_id, endpoint_id)

    active = (
        db.query(Stroke)
        .filter(Stroke.rally_id == existing.id, Stroke.deleted_at.is_(None))
        .all()
    )
    # 途中保存 (final=False) が既存の非削除ストローク数より少ない場合は、古い途中保存が
    # 遅れて着いたものとみなし何も変えず既存を返す (確定後に縮めない)。
    if not body.final and len(body.strokes) < len(active):
        return _batch_existing_response(db, existing, idem_key, user_id, endpoint_id)

    now = datetime.utcnow()
    for s in active:
        s.deleted_at = now
    db.flush()  # soft delete を確定してから入れ直し、active 部分一意に当てない

    saved = _insert_strokes_for_rally(db, existing.id, body.strokes)

    # ラリーの項目を更新 (勝者・終了種別・スコアは最終送信で確定する)。score_before は
    # 既存値を保持する (前ラリー依存で初回保存時に計算済み)。
    existing.server = body.rally.server
    existing.winner = body.rally.winner
    existing.end_type = body.rally.end_type
    existing.rally_length = body.rally.rally_length
    existing.duration_sec = body.rally.duration_sec
    existing.score_a_after = body.rally.score_a_after
    existing.score_b_after = body.rally.score_b_after
    existing.is_deuce = body.rally.is_deuce
    existing.video_timestamp_start = body.rally.video_timestamp_start
    existing.video_timestamp_end = body.rally.video_timestamp_end
    existing.is_skipped = body.rally.is_skipped
    if body.rally.annotation_mode is not None:
        existing.annotation_mode = body.rally.annotation_mode
    if body.rally.review_status is not None:
        existing.review_status = body.rally.review_status
    # 所有端末を記録 (既存が未設定なら今回の端末を所有者として刻む)。上の所有者ガードで
    # 食い違う端末は既に弾いているので、ここでの代入は同じ端末か未設定時のみ到達する。
    if incoming_device:
        existing.source_device_id = incoming_device

    _update_annotation_progress(game_set.match_id, db)
    try:
        db.commit()
    except IntegrityError as exc:
        _raise_batch_db_error(db, body, exc, "commit")
    except (DBAPIError, DisconnectionError) as exc:
        _raise_batch_db_error(db, body, exc, "commit")

    response_cache.bump_players(players_for_match(db, game_set.match_id))

    # 確定送信 (final=true) のときだけ共有セッションへブロードキャストする。
    # 途中保存 (final=false) では未確定ラリーを観戦ビューへ流さない。
    if body.final:
        _broadcast_rally_saved(db, game_set.match_id, existing)

    response = {
        "success": True,
        "data": {
            "rally_id": existing.id,
            "stroke_count": len(saved),
            "replaced": True,
            "final": body.final,
        },
    }
    if idem_key:
        from backend.utils.idempotency import store
        store(idem_key, user_id, endpoint_id, response, status_code=201)
    return response


def _finalize_existing_in_progress_rally(
    db: Session,
    existing: Rally,
    body: BatchSaveRequest,
    game_set: GameSet,
    idem_key: Optional[str],
    user_id,
    endpoint_id: str,
) -> dict:
    """replace_strokes=False の確定送信 (final=true) で、既存の途中保存ラリーを確定する。

    既存ラリーが end_type=in_progress (途中保存) のとき、winner / end_type / score 等の
    確定項目を送信内容で必ず上書きする (打球本数が同じでも上書きされる)。打球自体は
    足し直さない (replace_strokes=False)。別端末が作ったラリーは上書きしない
    (_batch_replace_existing と同じ所有者ガード)。確定したので共有セッションへ
    ブロードキャストする。
    """
    # 所有者ガード: 別端末 (= 別ユーザー) が作ったラリーを上書きしない。
    # 既存と今回の device が両方わかっていて食い違う場合だけ拒否する。
    incoming_device = body.rally.source_device_id
    if (
        existing.source_device_id
        and incoming_device
        and existing.source_device_id != incoming_device
    ):
        return _batch_existing_response(db, existing, idem_key, user_id, endpoint_id)

    _finalize_rally_fields(existing, body)
    if incoming_device:
        existing.source_device_id = incoming_device

    stroke_count = (
        db.query(Stroke)
        .filter(Stroke.rally_id == existing.id, Stroke.deleted_at.is_(None))
        .count()
    )
    _update_annotation_progress(game_set.match_id, db)
    try:
        db.commit()
    except IntegrityError as exc:
        _raise_batch_db_error(db, body, exc, "commit")
    except (DBAPIError, DisconnectionError) as exc:
        _raise_batch_db_error(db, body, exc, "commit")

    response_cache.bump_players(players_for_match(db, game_set.match_id))

    # 確定したので共有セッションへブロードキャストする (途中保存では送っていない)。
    _broadcast_rally_saved(db, game_set.match_id, existing)

    response = {
        "success": True,
        "data": {
            "rally_id": existing.id,
            "stroke_count": stroke_count,
            "finalized": True,
            "final": True,
        },
    }
    if idem_key:
        from backend.utils.idempotency import store
        store(idem_key, user_id, endpoint_id, response, status_code=201)
    return response


def _raise_batch_db_error(db: Session, body: BatchSaveRequest, exc: Exception, phase: str):
    logger.exception(
        "Batch save %s failed: set_id=%s rally_num=%s stroke_count=%s error_type=%s error=%s orig=%s",
        phase, body.rally.set_id, body.rally.rally_num, len(body.strokes),
        type(exc).__name__, str(exc), getattr(exc, "orig", None),
    )
    db.rollback()
    if isinstance(exc, (OperationalError, InterfaceError, DisconnectionError)) or getattr(
        exc, "connection_invalidated", False
    ):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "DB_UNAVAILABLE_RETRYABLE",
                "message": "データベースが一時的に利用できません。再送してください。",
                "saved": {"rally": False, "strokes": 0},
            },
        ) from exc
    raise HTTPException(
        status_code=422,
        detail={
            "code": "BATCH_DATA_REJECTED",
            "message": "保存できない値が含まれています。",
            "error_type": type(exc).__name__,
            "saved": {"rally": False, "strokes": 0},
        },
    ) from exc


def _is_in_progress_rally(rally: Rally) -> bool:
    """途中保存 (final=false) で作られた未確定ラリーか。

    判定は end_type だけで足りる (専用フラグ列は増やさない)。共通の定数
    IN_PROGRESS_END_TYPE (analysis_population) を使い、得点・解析の集計と
    同じ語彙で「未確定」を識別する。
    """
    return rally.end_type == IN_PROGRESS_END_TYPE


def _broadcast_rally_saved(db: Session, match_id: int, rally: Rally) -> None:
    """確定ラリーのスコア更新を共有セッションへブロードキャストする (非同期)。

    途中保存 (final=false) の未確定ラリーでは呼ばない。確定 (final=true) 時だけ
    呼び、観戦側の共有ビューに「確定したラリー」だけが流れるようにする。
    """
    import asyncio
    from backend.ws.live import manager
    from backend.db.models import SharedSession
    sessions = (
        db.query(SharedSession)
        .filter(SharedSession.match_id == match_id, SharedSession.is_active.is_(True))
        .all()
    )
    if not sessions:
        return
    payload = {
        "type": "rally_saved",
        "data": {
            "rally_num": rally.rally_num,
            "winner": rally.winner,
            "end_type": rally.end_type,
            "score_a": rally.score_a_after,
            "score_b": rally.score_b_after,
            "rally_length": rally.rally_length,
            "is_skipped": rally.is_skipped,
        },
    }
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            for sess in sessions:
                asyncio.ensure_future(manager.broadcast(sess.session_code, payload))
    except Exception:
        pass


def _finalize_rally_fields(existing: Rally, body: "BatchSaveRequest") -> None:
    """final=true の確定送信で、既存ラリーの確定項目を送信内容で必ず上書きする。

    winner / end_type / score を含む確定項目を無条件に上書きする。途中保存で仮値
    (winner=player_a, end_type=in_progress) が入っていても、本数が同じでも、確定内容で
    置き換える。score_a_before / score_b_before は初回保存時に前ラリー依存で計算済みの
    ため保持する。
    """
    existing.server = body.rally.server
    existing.winner = body.rally.winner
    existing.end_type = body.rally.end_type
    existing.rally_length = body.rally.rally_length
    existing.duration_sec = body.rally.duration_sec
    existing.score_a_after = body.rally.score_a_after
    existing.score_b_after = body.rally.score_b_after
    existing.is_deuce = body.rally.is_deuce
    existing.video_timestamp_start = body.rally.video_timestamp_start
    existing.video_timestamp_end = body.rally.video_timestamp_end
    existing.is_skipped = body.rally.is_skipped
    if body.rally.annotation_mode is not None:
        existing.annotation_mode = body.rally.annotation_mode
    if body.rally.review_status is not None:
        existing.review_status = body.rally.review_status


@router.post("/strokes/batch", status_code=201)
def batch_save_rally(
    body: BatchSaveRequest,
    request: Request,
    db: Session = Depends(get_db),
    idem_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """ラリー確定時の一括保存（個別保存より効率的）

    **冪等性**: `src/utils/mobileAnnotateQueue.ts` と `useOfflineSync.ts` は
    以前から `X-Idempotency-Key` を送っていたが、**このルータは読んでいなかった**。
    再送が起きるのは「サーバは処理したがレスポンスを失った」ときで、まさに
    モバイル注釈キューが想定している iOS の背景化・弱電波の状況。結果として
    **ラリーと打球が二重に入り、ラリー数と下流の全指標が静かに壊れていた**。
    """
    endpoint_id = "batch_save_rally"
    from backend.utils.auth import get_auth
    ctx_for_idem = get_auth(request)
    # 冪等キーを「処理の最初」に予約する。commit 成功後にしか冪等レコードを
    # 残さなかった旧方式では、commit 前に失敗した再送が本処理を最初から
    # やり直し、(set_id, rally_num) の一意制約や strokes の重複を踏んでいた。
    # 予約方式では、同じキーの近接再送は「処理中(409)」で入口から弾き、
    # commit 前に失敗した経路では予約を解放して再送を許す。
    reserved_key = None  # release すべきキー。store/409 が走ったら None に戻す。
    if idem_key:
        from backend.utils.idempotency import (
            is_valid_key, reserve, replay_response, REPLAY, IN_PROGRESS,
        )
        if not is_valid_key(idem_key):
            raise HTTPException(status_code=400, detail="X-Idempotency-Key の形式が不正です")
        status, cached = reserve(idem_key, ctx_for_idem.user_id, endpoint_id)
        if status == REPLAY:
            return replay_response(cached)
        if status == IN_PROGRESS:
            # 同じキーの処理が進行中 (または別ユーザ/別エンドポイントとの衝突)。
            # 二重処理を入口で止める。再送側はしばらく待って再試行すればよい。
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "IDEMPOTENT_REQUEST_IN_PROGRESS",
                    "message": "同じリクエストを処理中です。しばらく待って再送してください。",
                },
            )
        # status == RESERVED: 予約を取得した。失敗経路で解放するため控える。
        reserved_key = idem_key

    try:
        result = _batch_save_rally_body(
            body, request, db, idem_key, endpoint_id, ctx_for_idem
        )
    except Exception:
        # commit 前に失敗した (DB 一時エラーの 503、バリデーション 422、
        # scope 404/403、予期せぬ例外)。予約を解放して再送を許す。成功経路は
        # store() が予約を完了へ昇格済みなので、ここには到達しない。
        if reserved_key is not None:
            from backend.utils.idempotency import release
            release(reserved_key, ctx_for_idem.user_id, endpoint_id)
        raise

    # Emit one INFO line per successful POST /api/strokes/batch (HTTP 201).
    # All success paths (new save, already_saved resend, replaced mid/final
    # save) funnel through this single point, so lines are not duplicated.
    # Failure paths re-raise above and are covered by the existing
    # logger.exception / _raise_batch_db_error, so no duplicate line is emitted
    # here. No PII, tokens, or request body are logged: only the
    # non-identifying set_id / rally_num plus the batch result.
    data = result.get("data", {}) if isinstance(result, dict) else {}
    logger.info(
        "strokes/batch saved: status=%s set_id=%s rally_num=%s already_saved=%s stroke_count=%s",
        201,
        body.rally.set_id,
        body.rally.rally_num,
        bool(data.get("already_saved", False)),
        data.get("stroke_count"),
    )
    return result


def _batch_save_rally_body(
    body: BatchSaveRequest,
    request: Request,
    db: Session,
    idem_key: Optional[str],
    endpoint_id: str,
    ctx_for_idem,
):
    from backend.utils.auth import require_match_scope
    # セット存在確認 + team scope (R48: player は自分の試合のみ可、scope 経由判定)
    game_set = db.get(GameSet, body.rally.set_id)
    if not game_set:
        raise HTTPException(status_code=404, detail="ゲームが見つかりません")
    match = db.get(Match, game_set.match_id)
    if match:
        require_match_scope(request, match, db)

    # ラリー整合性チェック
    stroke_dicts = [s.model_dump() for s in body.strokes]
    rally_dict = body.rally.model_dump()
    valid, error = validate_rally(rally_dict, stroke_dicts)
    if not valid:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": error}
        )

    # 各ストロークの整合性チェック
    for stroke_data in stroke_dicts:
        valid, error = validate_stroke(stroke_data)
        if not valid:
            raise HTTPException(
                status_code=422,
                detail={"code": "VALIDATION_ERROR", "message": error}
            )

    # (set_id, rally_num) は一意 (migration 0053 / uq_rallies_set_id_rally_num_active)。
    # sibling の POST /api/rallies と同じく、X-Idempotency-Key 無しでも同じ番号が
    # 既にあればそれを返す。再開・再送・複数端末で同じ番号が二重に入ると、ラリー数と
    # 下流の全指標が静かに壊れる。再送では打球を足さず、初回保存と同じ形の成功を返す。
    existing = (
        db.query(Rally)
        .filter(
            Rally.set_id == body.rally.set_id,
            Rally.rally_num == body.rally.rally_num,
            Rally.deleted_at.is_(None),
        )
        .first()
    )
    if existing is not None:
        # replace_strokes=True のときは already_saved で捨てず、既存ラリーの
        # ストロークを置き換える (途中保存 / 最終保存)。require_match_scope を
        # 通過しているので、同じ試合の同じユーザーの書き込みに限られる。
        if body.replace_strokes:
            return _batch_replace_existing(
                db, existing, body, game_set, idem_key,
                ctx_for_idem.user_id, endpoint_id,
            )
        # replace_strokes=False でも、既存が途中保存 (in_progress) のラリーで、
        # 今回が確定送信 (final=true) なら、winner / end_type / score を確定内容で
        # 必ず上書きする (打球本数が同じでも上書きする)。打球は足し直さない
        # (replace_strokes=False なので既存のまま)。確定したので共有セッションへ
        # ブロードキャストする。
        if body.final and _is_in_progress_rally(existing):
            return _finalize_existing_in_progress_rally(
                db, existing, body, game_set, idem_key,
                ctx_for_idem.user_id, endpoint_id,
            )
        return _batch_existing_response(
            db, existing, idem_key, ctx_for_idem.user_id, endpoint_id
        )

    # score_before を前のラリーから自動計算
    prev_rally = (
        db.query(Rally)
        .filter(
            Rally.set_id == body.rally.set_id,
            Rally.rally_num == body.rally.rally_num - 1,
            Rally.deleted_at.is_(None),
        )
        .first()
    )
    score_a_before = prev_rally.score_a_after if prev_rally else 0
    score_b_before = prev_rally.score_b_after if prev_rally else 0

    # ラリー保存（score_before はサーバー側で計算）
    rally = Rally(**body.rally.model_dump())
    rally.score_a_before = score_a_before
    rally.score_b_before = score_b_before
    db.add(rally)
    try:
        db.flush()  # IDを取得するため先にflush
    except IntegrityError as exc:
        logger.exception(
            "Batch save flush failed: set_id=%s rally_num=%s stroke_count=%s error_type=%s error=%s orig=%s",
            body.rally.set_id, body.rally.rally_num, len(body.strokes),
            type(exc).__name__, str(exc), exc.orig,
        )
        if exc.connection_invalidated:
            _raise_batch_db_error(db, body, exc, "flush")
        # 上の検査と flush の間に別リクエストが同じ (set_id, rally_num) を入れた場合。
        # 一意インデックスが最終的な砦。rollback して勝った側の行を再送として返す。
        db.rollback()
        existing = (
            db.query(Rally)
            .filter(
                Rally.set_id == body.rally.set_id,
                Rally.rally_num == body.rally.rally_num,
                Rally.deleted_at.is_(None),
            )
            .first()
        )
        if existing is None:
            _raise_batch_db_error(db, body, exc, "flush")
        if body.replace_strokes:
            return _batch_replace_existing(
                db, existing, body, game_set, idem_key,
                ctx_for_idem.user_id, endpoint_id,
            )
        return _batch_existing_response(
            db, existing, idem_key, ctx_for_idem.user_id, endpoint_id
        )
    except (DBAPIError, DisconnectionError) as exc:
        _raise_batch_db_error(db, body, exc, "flush")

    # ストローク一括保存（shot_type を canonical 化）
    saved_strokes = []
    for stroke_data in body.strokes:
        stroke_dict = stroke_data.model_dump()
        stroke_dict["shot_type"] = canonicalize_shot(stroke_dict.get("shot_type", "other"))
        # 要望6: 意図タグは固定語彙へ正規化、自由記述は前後空白除去 (空は NULL)
        stroke_dict["intent_tag"] = _canonicalize_intent_tag(stroke_dict.get("intent_tag"))
        stroke_dict["intent_note"] = _clean_intent_note(stroke_dict.get("intent_note"))
        stroke = Stroke(
            rally_id=rally.id,
            land_zone_source=_human_land_zone_source(stroke_dict.get("land_zone")),
            **stroke_dict,
        )
        db.add(stroke)
        saved_strokes.append(stroke)

    # アノテーション進捗を更新
    _update_annotation_progress(game_set.match_id, db)

    try:
        db.commit()
    except IntegrityError as exc:
        logger.exception(
            "Batch save commit failed: set_id=%s rally_num=%s stroke_count=%s error_type=%s error=%s orig=%s",
            body.rally.set_id, body.rally.rally_num, len(body.strokes),
            type(exc).__name__, str(exc), exc.orig,
        )
        if exc.connection_invalidated:
            _raise_batch_db_error(db, body, exc, "commit")
        # flush を通過したのに commit で一意制約に当たる競合（別端末が同じ
        # (set_id, rally_num) を同時に確定した等）。strokes 自体に一意制約は無いが、
        # ラリーの uq_rallies_set_id_rally_num_active が最終防壁になる。再送扱いで
        # 既存ラリーを already_saved の冪等応答として返す。
        db.rollback()
        existing = (
            db.query(Rally)
            .filter(
                Rally.set_id == body.rally.set_id,
                Rally.rally_num == body.rally.rally_num,
                Rally.deleted_at.is_(None),
            )
            .first()
        )
        if existing is None:
            _raise_batch_db_error(db, body, exc, "commit")
        if body.replace_strokes:
            return _batch_replace_existing(
                db, existing, body, game_set, idem_key,
                ctx_for_idem.user_id, endpoint_id,
            )
        return _batch_existing_response(
            db, existing, idem_key, ctx_for_idem.user_id, endpoint_id
        )
    except (DBAPIError, DisconnectionError) as exc:
        _raise_batch_db_error(db, body, exc, "commit")

    # 試合の関与選手のみキャッシュ無効化（他選手の解析結果は保持）
    response_cache.bump_players(players_for_match(db, game_set.match_id))

    # S-001: アクティブセッションへスコア更新をブロードキャスト（非同期）。
    # 途中保存 (final=false) で作られた未確定ラリーはブロードキャストしない。
    # これにより observer の共有ビューには「確定したラリー」だけが流れる。確定
    # (final=true) は後から同じラリーへ確定送信が来たとき _batch_replace_existing /
    # finalize 経路でブロードキャストされる。
    if body.final:
        _broadcast_rally_saved(db, game_set.match_id, rally)

    response = {
        "success": True,
        "data": {
            "rally_id": rally.id,
            "stroke_count": len(saved_strokes),
        }
    }
    if idem_key:
        from backend.utils.idempotency import store
        store(idem_key, ctx_for_idem.user_id, endpoint_id, response, status_code=201)
    return response


@router.post("/strokes", status_code=201)
def create_stroke(
    rally_id: int,
    body: StrokeData,
    request: Request,
    db: Session = Depends(get_db),
    idem_key: Optional[str] = Header(None, alias="X-Idempotency-Key"),
):
    """ストローク記録（個別）

    **冪等性**: `/strokes/batch` と同じ理由でここも要る。
    `mobileAnnotateQueue.ts` がキューに載せる POST は
    `POST /api/rallies` と **`POST /api/strokes?rally_id=:rally_id`** の 2 つで、
    前者だけが冪等化されていた。再送は「サーバは処理したがレスポンスを失った」
    ときに起きるので、1 打球が二重に入り `rally_length` と下流の全カウントが
    静かにずれる。キューの PUT / DELETE は結果が同じなので再送しても害はない。
    """
    endpoint_id = f"create_stroke:{rally_id}"
    from backend.utils.auth import get_auth as _ga
    ctx_for_idem = _ga(request)
    if idem_key:
        from backend.utils.idempotency import is_valid_key, get_cached, replay_response
        if not is_valid_key(idem_key):
            raise HTTPException(status_code=400, detail="X-Idempotency-Key の形式が不正です")
        cached = get_cached(idem_key, ctx_for_idem.user_id, endpoint_id)
        if cached is not None:
            return replay_response(cached)

    _stroke_require_scope(request, db, rally_id)

    submitted = body.model_dump()
    submitted["shot_type"] = _normalize_shot_type(submitted["shot_type"])
    # 要望6: 意図タグ正規化・自由記述クリーンアップ
    submitted["intent_tag"] = _canonicalize_intent_tag(submitted.get("intent_tag"))
    submitted["intent_note"] = _clean_intent_note(submitted.get("intent_note"))
    valid, error = validate_stroke(submitted)
    if not valid:
        raise HTTPException(
            status_code=422,
            detail={"code": "VALIDATION_ERROR", "message": error}
        )

    # (rally_id, stroke_num) は DB 上 Index だけで一意制約ではない。Pass2 を同じラリーへ
    # 再実行すると別キーの POST で #1 / #9999 が二重に入り、分析が系列を複製する。
    # 同じ番号が既にある場合: 内容が同じなら再送として既存行を返し、違えば 409 で拒否する。
    dup = (
        db.query(Stroke)
        .filter(
            Stroke.rally_id == rally_id,
            Stroke.stroke_num == body.stroke_num,
            Stroke.deleted_at.is_(None),
        )
        .first()
    )
    if dup is not None:
        if any(getattr(dup, k) != v for k, v in submitted.items()):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "STROKE_NUM_CONFLICT",
                    "message": "このラリーには同じストローク番号が既に保存されています",
                    "stroke_num": body.stroke_num,
                    "existing_stroke_id": dup.id,
                },
            )
        response = {"success": True, "data": stroke_to_dict(dup)}
        if idem_key:
            from backend.utils.idempotency import store
            store(idem_key, ctx_for_idem.user_id, endpoint_id, response, status_code=201)
        return response

    stroke = Stroke(
        rally_id=rally_id,
        land_zone_source=_human_land_zone_source(body.land_zone),
        **submitted,
    )
    touch(stroke)
    db.add(stroke)
    db.commit()
    # rally → set → match 経由で関与選手のみ無効化
    response_cache.bump_players(players_for_rally(db, rally_id))
    response = {"success": True, "data": stroke_to_dict(stroke)}
    if idem_key:
        from backend.utils.idempotency import store
        store(idem_key, ctx_for_idem.user_id, endpoint_id, response, status_code=201)
    return response


@router.put("/strokes/{stroke_id}")
def update_stroke(stroke_id: int, body: StrokeData, request: Request, db: Session = Depends(get_db)):
    """ストローク更新"""
    stroke = db.get(Stroke, stroke_id)
    if not stroke:
        raise HTTPException(status_code=404, detail="ストロークが見つかりません")
    _stroke_require_scope(request, db, stroke.rally_id)
    # 番号を変える更新(最終打の再採番・挿入に伴う後ろ送り)が、同じラリーの別 stroke と
    # 衝突して同一 stroke_num を作らないようにする。番号を変えない更新は既存の重複データでも通す。
    if body.stroke_num != stroke.stroke_num:
        clash = (
            db.query(Stroke.id)
            .filter(
                Stroke.rally_id == stroke.rally_id,
                Stroke.stroke_num == body.stroke_num,
                Stroke.id != stroke.id,
                Stroke.deleted_at.is_(None),
            )
            .first()
        )
        if clash is not None:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "STROKE_NUM_CONFLICT",
                    "message": "このラリーには同じストローク番号が既に保存されています",
                    "stroke_num": body.stroke_num,
                    "existing_stroke_id": clash[0],
                },
            )
    from backend.utils.db_update import apply_update
    previous_land_zone = stroke.land_zone
    # 送られた項目だけを更新する (exclude_unset)。全項目を model_dump() で反映すると、
    # モバイル Pass3 のように 5 項目だけ送る編集が、送らなかった座標・品質・姿勢・時刻・
    # 移動特徴・由来を None / False で上書きして消していた (監査 #789)。
    # 送られた項目を明示的に null にした場合は従来どおり消える。
    changes = body.model_dump(exclude_unset=True)
    if "shot_type" in changes:
        changes["shot_type"] = _normalize_shot_type(changes["shot_type"])
    # 要望6: 送られた場合のみ意図タグを正規化・自由記述をクリーンアップする
    # (exclude_unset で送られていない項目は触らない=既存値を保持)。
    if "intent_tag" in changes:
        changes["intent_tag"] = _canonicalize_intent_tag(changes["intent_tag"])
    if "intent_note" in changes:
        changes["intent_note"] = _clean_intent_note(changes["intent_note"])
    apply_update(stroke, changes)
    # land_zone の入力元。値が変わった時だけ
    # 人の入力として記録する (CV が書いた値をそのまま送り返しただけなら 'cv' のまま)。
    # 値を消したら入力元も消す。
    if not stroke.land_zone:
        stroke.land_zone_source = None
    elif stroke.land_zone != previous_land_zone:
        stroke.land_zone_source = "human"
    touch(stroke)
    db.commit()
    # 対象 stroke の rally 経由で関与選手のみ無効化
    response_cache.bump_players(players_for_rally(db, stroke.rally_id))
    return {"success": True, "data": stroke_to_dict(stroke)}


@router.delete("/strokes/{stroke_id}")
def delete_stroke(stroke_id: int, request: Request, db: Session = Depends(get_db)):
    """ストローク削除（アンドゥ用）"""
    stroke = db.get(Stroke, stroke_id)
    if not stroke:
        raise HTTPException(status_code=404, detail="ストロークが見つかりません")
    _stroke_require_scope(request, db, stroke.rally_id)
    # 削除前に関与選手を控える
    affected_players = players_for_rally(db, stroke.rally_id)
    db.delete(stroke)
    db.commit()
    response_cache.bump_players(affected_players)
    return {"success": True, "data": {"id": stroke_id}}


@router.get("/rallies/{rally_id}/strokes")
def list_rally_strokes(rally_id: int, request: Request, db: Session = Depends(get_db)):
    """ラリーの保存済みストローク一覧（確認モードの実データ表示・編集用）。

    `GET /analysis/rally_strokes` は id を返さず team scope 検証も無いため、
    確認モードから個別ストロークを編集する用途には使えない。ここは編集に必要な
    全フィールドを `stroke_to_dict` で返し、閲覧権限は既存の `PUT /strokes/{id}`
    と同じ `_stroke_require_scope`（= `require_match_scope`）に従う。
    削除済み (soft-delete) ストロークは除外する。
    """
    _stroke_require_scope(request, db, rally_id)
    strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id == rally_id, Stroke.deleted_at.is_(None))
        .order_by(Stroke.stroke_num)
        .all()
    )
    return {
        "success": True,
        "data": {
            "rally_id": rally_id,
            "strokes": [stroke_to_dict(s) for s in strokes],
        },
    }


def _update_annotation_progress(match_id: int, db: Session) -> None:
    """アノテーション進捗を更新（推定総ラリー数ベース）"""
    match = db.get(Match, match_id)
    if not match:
        return

    # 完了ラリー数を取得
    from sqlalchemy import func
    completed = db.query(func.count(Rally.id)).join(
        GameSet, Rally.set_id == GameSet.id
    ).filter(GameSet.match_id == match_id).scalar() or 0

    # 推定総ラリー数（バドミントン1試合の平均: 60ラリー）
    estimated_total = 60
    progress = min(completed / estimated_total, 1.0)
    match.annotation_progress = progress
    if progress >= 1.0:
        match.annotation_status = "complete"
    elif completed > 0:
        match.annotation_status = "in_progress"
