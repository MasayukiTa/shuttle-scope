"""CV補助アノテーション候補API（/api/cv-candidates）

エンドポイント:
  POST /cv-candidates/build/{match_id}   — 候補を生成してアーティファクトに保存
  GET  /cv-candidates/{match_id}         — 生成済み候補を返す
  POST /cv-candidates/apply/{match_id}   — 高確信度候補をストロークに書き戻す
  PUT  /cv-candidates/review/{rally_id}  — ラリーのレビューステータスを更新

Round 258 P1 fix: 旧来は router 内部で auth check を一切持たず、
TeamScopeAccessControlMiddleware の path-pattern マッチングに依存していた。
PUT /cv-candidates/review/{rally_id} は match_id ではなく rally_id を取るので
middleware の _MATCH_ID_PATTERNS には引っ掛からず、coach/analyst が cross-team
の rally の review_status を書き換える IDOR が成立していた。
本ファイルでは全 endpoint に auth + team scope を明示的に書く。
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, GameSet, Rally, Stroke, MatchCVArtifact
from backend.cv.candidate_builder import build_candidates
from backend.yolo.cv_aligner import align_match

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_match_team_scope(request: Request, db: Session, match_id: int) -> Match:
    """match_id に対する team-scope 強制 + auth check.

    - 未認証 → 401
    - admin → スルー
    - coach/analyst → 自チームの match (owner/home/away に自チームがあれば OK) のみ
    - player → 自分が出場している match のみ
    無ければ 404 (列挙耐性)。Round 258 P1 fix のため明示。
    """
    from backend.utils.auth import get_auth as _ga
    ctx = _ga(request)
    if ctx.role is None:
        raise HTTPException(status_code=401, detail="認証が必要です")
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    if ctx.is_admin:
        return match
    # team scope: coach / analyst
    if ctx.is_coach or ctx.is_analyst:
        from backend.db.models import Team as _Team
        team_name = (ctx.team_name or "").strip()
        if not team_name:
            raise HTTPException(status_code=403, detail="team_name 未設定")
        team_row = db.query(_Team).filter(_Team.name == team_name, _Team.deleted_at.is_(None)).first()
        if not team_row:
            raise HTTPException(status_code=404, detail="試合が見つかりません")
        team_id = team_row.id
        if match.owner_team_id != team_id and match.home_team_id != team_id and match.away_team_id != team_id:
            # 公開プールの場合は許可
            if not getattr(match, "is_public_pool", False):
                raise HTTPException(status_code=404, detail="試合が見つかりません")
        return match
    if ctx.is_player:
        if not ctx.player_id:
            raise HTTPException(status_code=403, detail="player_id 未設定")
        pids = {match.player_a_id, match.player_b_id, match.partner_a_id, match.partner_b_id}
        if ctx.player_id not in pids:
            raise HTTPException(status_code=404, detail="試合が見つかりません")
        return match
    raise HTTPException(status_code=403, detail="権限がありません")


def _require_rally_team_scope(request: Request, db: Session, rally_id: int) -> Rally:
    """rally_id に対する team-scope 強制 + auth check (rally → set → match で resolve)."""
    rally = db.get(Rally, rally_id)
    if not rally:
        raise HTTPException(status_code=404, detail="ラリーが見つかりません")
    game_set = db.get(GameSet, rally.set_id)
    if not game_set:
        raise HTTPException(status_code=404, detail="ラリーが見つかりません")
    _require_match_team_scope(request, db, game_set.match_id)
    return rally

ARTIFACT_TYPE_CANDIDATES      = "cv_candidates"
ARTIFACT_TYPE_TRACKNET        = "tracknet_shuttle_track"
ARTIFACT_TYPE_YOLO            = "yolo_player_detections"
ARTIFACT_TYPE_ALIGNMENT       = "cv_alignment"
# A5: ラリー境界の CV 自動検出候補（suggested 中心。自動でラリーを切らない）
ARTIFACT_TYPE_RALLY_BOUNDARIES = "rally_boundaries"


# ────────────────────────────────────────────────────────────────────────────
# POST /cv-candidates/build/{match_id}
# ────────────────────────────────────────────────────────────────────────────

@router.post("/cv-candidates/build/{match_id}")
def build_cv_candidates(match_id: int, request: Request, db: Session = Depends(get_db)):
    """TrackNet + YOLO アーティファクトから CV 候補を生成して保存する。

    どちらかのアーティファクトが欠けていても部分的な候補を生成する。
    Round 258 P1: team scope check 追加 (cross-team match に対する誤動作・抗解析を遮断)。
    """
    match = _require_match_team_scope(request, db, match_id)

    # ── アーティファクト取得 ──────────────────────────────────────────────────
    tracknet_artifact = _latest_artifact(db, match_id, ARTIFACT_TYPE_TRACKNET)
    yolo_artifact     = _latest_artifact(db, match_id, ARTIFACT_TYPE_YOLO)
    alignment_artifact = _latest_artifact(db, match_id, ARTIFACT_TYPE_ALIGNMENT)

    tracknet_frames: list[dict] = []
    yolo_frames: list[dict]     = []
    alignment_data: list[dict]  = []

    if tracknet_artifact and tracknet_artifact.data:
        try:
            tracknet_frames = json.loads(tracknet_artifact.data)
        except Exception:
            logger.warning("TrackNet artifact JSON 解析失敗 match_id=%d", match_id)

    if yolo_artifact and yolo_artifact.data:
        try:
            yolo_frames = json.loads(yolo_artifact.data)
        except Exception:
            logger.warning("YOLO artifact JSON 解析失敗 match_id=%d", match_id)

    if alignment_artifact and alignment_artifact.data:
        try:
            alignment_data = json.loads(alignment_artifact.data)
        except Exception:
            logger.warning("アライメント artifact JSON 解析失敗 match_id=%d", match_id)

    # アライメントデータがなく両方揃っていれば即時計算
    if not alignment_data and tracknet_frames and yolo_frames:
        rally_boundaries = _get_rally_boundaries(db, match_id)
        try:
            alignment_data = align_match(yolo_frames, tracknet_frames, rally_boundaries)
        except Exception as e:
            logger.warning("アライメント計算失敗: %s", e)

    if not tracknet_frames and not yolo_frames:
        raise HTTPException(
            status_code=400,
            detail="TrackNet または YOLO アーティファクトが必要です。先に CV 解析を実行してください。",
        )

    # ── DB からラリー・ストローク情報を取得 ──────────────────────────────────
    rallies_db = _get_rallies_for_match(db, match_id)
    rally_ids  = [r["id"] for r in rallies_db]
    strokes_db = _get_strokes_for_rallies(db, rally_ids)

    # ── 候補生成 ─────────────────────────────────────────────────────────────
    fps = _resolve_match_fps(db, match_id)
    candidates = build_candidates(
        match_id=match_id,
        rallies_db=rallies_db,
        strokes_db=strokes_db,
        tracknet_frames=tracknet_frames,
        yolo_frames=yolo_frames,
        alignment_data=alignment_data,
        fps=fps,
    )

    candidates_json = json.dumps(candidates, ensure_ascii=False)

    # ── A5: ラリー境界候補を別アーティファクトとして保存 ──────────────────────
    # SS_RALLY_BOUNDARY_DETECT が OFF のときは build_candidates が
    # rally_boundaries キーを返さない → 保存もスキップ（従来挙動）。
    rally_boundaries = candidates.get("rally_boundaries")
    if rally_boundaries is not None:
        _save_rally_boundaries_artifact(db, match_id, rally_boundaries)

    # ── アーティファクト保存（既存があれば上書き） ────────────────────────────
    existing = _latest_artifact(db, match_id, ARTIFACT_TYPE_CANDIDATES)
    if existing:
        existing.data       = candidates_json
        existing.summary    = json.dumps({
            "rally_count": len(candidates["rallies"]),
            "built_at":    candidates["built_at"],
        }, ensure_ascii=False)
        existing.updated_at = datetime.utcnow()
    else:
        artifact = MatchCVArtifact(
            match_id      = match_id,
            artifact_type = ARTIFACT_TYPE_CANDIDATES,
            summary       = json.dumps({
                "rally_count": len(candidates["rallies"]),
                "built_at":    candidates["built_at"],
            }, ensure_ascii=False),
            data          = candidates_json,
        )
        db.add(artifact)

    db.commit()

    return {
        "success": True,
        "data": {
            "match_id":    match_id,
            "rally_count": len(candidates["rallies"]),
            "built_at":    candidates["built_at"],
            # A5: ラリー境界候補数（rally_boundaries 検出 OFF 時は None）
            "rally_boundary_count": (
                rally_boundaries.get("boundary_count") if rally_boundaries else None
            ),
        },
    }


# ────────────────────────────────────────────────────────────────────────────
# GET /cv-candidates/{match_id}
# ────────────────────────────────────────────────────────────────────────────

@router.get("/cv-candidates/{match_id}")
def get_cv_candidates(match_id: int, request: Request, db: Session = Depends(get_db)):
    """生成済み CV 候補を返す。未生成の場合は data: null を返す。"""
    _require_match_team_scope(request, db, match_id)  # Round 258 P1
    artifact = _latest_artifact(db, match_id, ARTIFACT_TYPE_CANDIDATES)
    if not artifact or not artifact.data:
        return {"success": True, "data": None}

    try:
        data = json.loads(artifact.data)
    except Exception:
        return {"success": True, "data": None}

    return {"success": True, "data": data}


# ────────────────────────────────────────────────────────────────────────────
# POST /cv-candidates/apply/{match_id}
# ────────────────────────────────────────────────────────────────────────────

class ApplyRequest(BaseModel):
    mode: str = "auto_filled"  # "auto_filled" | "suggested" | "all"
    fields: list[str] = ["land_zone", "hitter"]  # 適用するフィールド

    # A1-2: レビュー一括適用フィルタ（すべて任意。未指定時は従来挙動を完全維持）
    min_confidence: Optional[float] = None      # この値未満の候補は適用しない
    max_confidence: Optional[float] = None      # この値超の候補は適用しない
    exclude_reason_codes: Optional[list[str]] = None  # この reason_code を持つ候補を除外
    rally_ids: Optional[list[int]] = None       # 対象ラリーを限定


def _field_passes_filters(
    cand: Optional[dict],
    body: ApplyRequest,
    apply_modes: set[str],
) -> bool:
    """候補フィールド（land_zone / hitter）が apply 条件 + A1-2 フィルタを満たすか。"""
    if not cand:
        return False
    if cand.get("decision_mode") not in apply_modes:
        return False

    conf = cand.get("confidence_score")
    if body.min_confidence is not None and (conf is None or conf < body.min_confidence):
        return False
    if body.max_confidence is not None and (conf is None or conf > body.max_confidence):
        return False

    if body.exclude_reason_codes:
        codes = set(cand.get("reason_codes") or [])
        if codes & set(body.exclude_reason_codes):
            return False

    return True


@router.post("/cv-candidates/apply/{match_id}")
def apply_cv_candidates(
    match_id: int,
    body: ApplyRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    # Round 258 P1: team scope check 追加 (cross-team match の stroke 書き換え防止)
    _require_match_team_scope(request, db, match_id)
    """候補を既存ストロークに書き戻す。

    - mode="auto_filled": decision_mode=="auto_filled" の候補のみ適用
    - mode="suggested": auto_filled + suggested を適用
    - mode="all": 全候補を適用（確認なし）

    A1-2: 任意の絞り込みフィルタ（min/max_confidence, exclude_reason_codes,
    fields, rally_ids）と併用可能。フィルタ未指定時の挙動は従来どおり。
    """
    artifact = _latest_artifact(db, match_id, ARTIFACT_TYPE_CANDIDATES)
    if not artifact or not artifact.data:
        raise HTTPException(status_code=404, detail="CV 候補がありません。先にビルドを実行してください。")

    try:
        candidates = json.loads(artifact.data)
    except Exception:
        raise HTTPException(status_code=500, detail="候補データの解析に失敗しました")

    # 適用モード
    apply_modes: set[str] = {"auto_filled"}
    if body.mode in ("suggested", "all"):
        apply_modes.add("suggested")
    if body.mode == "all":
        apply_modes.add("review_required")

    rally_filter: Optional[set[int]] = (
        set(body.rally_ids) if body.rally_ids else None
    )

    updated_count = 0
    land_zone_count = 0
    hitter_count = 0
    skipped_count = 0  # フィルタや条件で適用しなかったフィールド数

    for rally_id_str, rally_cand in candidates.get("rallies", {}).items():
        # A1-2: rally_ids フィルタ
        if rally_filter is not None:
            try:
                rid = int(rally_id_str)
            except (TypeError, ValueError):
                rid = rally_cand.get("rally_id")
            if rid not in rally_filter:
                continue

        for sc in rally_cand.get("strokes", []):
            stroke_id = sc.get("stroke_id")
            if not stroke_id:
                continue

            stroke = db.get(Stroke, stroke_id)
            if not stroke:
                continue

            changed = False

            # 着地ゾーン書き戻し
            if "land_zone" in body.fields:
                lz = sc.get("land_zone")
                if _field_passes_filters(lz, body, apply_modes):
                    if stroke.land_zone != lz["value"]:
                        stroke.land_zone = lz["value"]
                        land_zone_count += 1
                        changed = True
                elif lz:
                    skipped_count += 1

            # 打者書き戻し
            if "hitter" in body.fields:
                ht = sc.get("hitter")
                if _field_passes_filters(ht, body, apply_modes):
                    # player フィールドに書き戻す
                    if stroke.player != ht["value"]:
                        stroke.player = ht["value"]
                        hitter_count += 1
                        changed = True
                elif ht:
                    skipped_count += 1

            if changed:
                stroke.source_method = "assisted"
                updated_count += 1

    db.commit()

    return {
        "success": True,
        "data": {
            "updated_strokes": updated_count,
            "land_zone_count": land_zone_count,
            "hitter_count":    hitter_count,
            "skipped_count":   skipped_count,
            "applied_by_mode": body.mode,
            "applied_fields":  list(body.fields),
            "filters": {
                "min_confidence":       body.min_confidence,
                "max_confidence":       body.max_confidence,
                "exclude_reason_codes": body.exclude_reason_codes or [],
                "rally_ids":            body.rally_ids or [],
            },
        },
    }


# ────────────────────────────────────────────────────────────────────────────
# PUT /cv-candidates/review/{rally_id}
# ────────────────────────────────────────────────────────────────────────────

class ReviewStatusUpdate(BaseModel):
    review_status: str  # "pending" | "completed"


@router.put("/cv-candidates/review/{rally_id}")
def update_rally_review_status(
    rally_id: int,
    body: ReviewStatusUpdate,
    request: Request,
    db: Session = Depends(get_db),
):
    """ラリーのレビューステータスを更新する。

    Round 258 P1 fix: 旧来は auth/team scope check が一切なかったため、
    任意の coach/analyst が他チーム rally の review_status を書き換えられた
    (rally_id は連番なので列挙容易)。rally → set → match で team scope 強制。
    """
    if body.review_status not in ("pending", "completed"):
        raise HTTPException(status_code=400, detail="review_status は pending / completed のいずれかです")

    rally = _require_rally_team_scope(request, db, rally_id)

    rally.review_status = body.review_status
    db.commit()

    return {"success": True, "data": {"rally_id": rally_id, "review_status": body.review_status}}


# ────────────────────────────────────────────────────────────────────────────
# GET /cv-candidates/review-queue/{match_id}
# ────────────────────────────────────────────────────────────────────────────

@router.get("/cv-candidates/review-queue/{match_id}")
def get_review_queue(match_id: int, request: Request, db: Session = Depends(get_db)):
    """review_status='pending' のラリー一覧を返す（自動フラグ + 手動フラグ両方）。"""
    _require_match_team_scope(request, db, match_id)  # Round 258 P1
    # 手動フラグされたラリー
    sets = (
        db.query(GameSet)
        .filter(GameSet.match_id == match_id)
        .all()
    )
    set_ids = [s.id for s in sets]
    if not set_ids:
        return {"success": True, "data": []}

    pending_rallies = (
        db.query(Rally)
        .filter(
            Rally.set_id.in_(set_ids),
            Rally.review_status == "pending",
        )
        .order_by(Rally.rally_num)
        .all()
    )

    # CV 候補からも review_required フラグを取得
    artifact = _latest_artifact(db, match_id, ARTIFACT_TYPE_CANDIDATES)
    cv_review_reasons: dict[int, list[str]] = {}
    if artifact and artifact.data:
        try:
            candidates = json.loads(artifact.data)
            for rally_id_str, rc in candidates.get("rallies", {}).items():
                if rc.get("review_reason_codes"):
                    cv_review_reasons[int(rally_id_str)] = rc["review_reason_codes"]
        except Exception:
            pass

    result = []
    for rally in pending_rallies:
        result.append({
            "rally_id":    rally.id,
            "rally_num":   rally.rally_num,
            "set_id":      rally.set_id,
            "review_status": rally.review_status,
            "cv_reason_codes": cv_review_reasons.get(rally.id, []),
        })

    # CV 候補で要確認だが review_status が pending でないものも追加
    for rally_id, codes in cv_review_reasons.items():
        if not any(r["rally_id"] == rally_id for r in result):
            rally = db.get(Rally, rally_id)
            if rally:
                result.append({
                    "rally_id":    rally.id,
                    "rally_num":   rally.rally_num,
                    "set_id":      rally.set_id,
                    "review_status": rally.review_status or "pending",
                    "cv_reason_codes": codes,
                })

    result.sort(key=lambda r: r["rally_num"])
    return {"success": True, "data": result}


# ── ヘルパー ──────────────────────────────────────────────────────────────────

def _latest_artifact(db: Session, match_id: int, artifact_type: str) -> Optional[MatchCVArtifact]:
    return (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == artifact_type,
        )
        .order_by(MatchCVArtifact.created_at.desc())
        .first()
    )


def _resolve_match_fps(db: Session, match_id: int, default: float = 60.0) -> float:
    """ラリー境界検出の秒→frame 換算に使う FPS を解決する。

    Recording.fps（試合に紐づく動画）があればそれを使い、無ければ default(60)。
    """
    try:
        from backend.db.models import Recording
        rec = (
            db.query(Recording)
            .filter(Recording.match_id == match_id, Recording.fps != None)  # noqa: E711
            .order_by(Recording.branch_no)
            .first()
        )
        if rec and rec.fps and rec.fps > 0:
            return float(rec.fps)
    except Exception:
        pass
    return default


def _save_rally_boundaries_artifact(
    db: Session, match_id: int, rally_boundaries: dict
) -> None:
    """A5: ラリー境界の CV 自動検出候補を MatchCVArtifact として保存（上書き）。

    annotation truth には書かない（候補のみ）。既存の手動 Rally は不変。
    """
    boundaries = rally_boundaries.get("boundaries", []) if rally_boundaries else []
    data_json = json.dumps(rally_boundaries, ensure_ascii=False)
    summary_json = json.dumps({
        "boundary_count": rally_boundaries.get("boundary_count", len(boundaries)),
        "fps":            rally_boundaries.get("fps"),
    }, ensure_ascii=False)

    existing = _latest_artifact(db, match_id, ARTIFACT_TYPE_RALLY_BOUNDARIES)
    if existing:
        existing.data        = data_json
        existing.summary     = summary_json
        existing.frame_count = len(boundaries)
        existing.updated_at  = datetime.utcnow()
    else:
        db.add(MatchCVArtifact(
            match_id      = match_id,
            artifact_type = ARTIFACT_TYPE_RALLY_BOUNDARIES,
            frame_count   = len(boundaries),
            summary       = summary_json,
            data          = data_json,
        ))


def _get_rally_boundaries(db: Session, match_id: int) -> list[dict]:
    sets = db.query(GameSet).filter(GameSet.match_id == match_id).all()
    set_ids = [s.id for s in sets]
    if not set_ids:
        return []
    rallies = (
        db.query(Rally)
        .filter(Rally.set_id.in_(set_ids))
        .order_by(Rally.id)
        .all()
    )
    return [
        {
            "rally_id": r.id,
            "start_sec": r.video_timestamp_start or 0.0,
            "end_sec":   r.video_timestamp_end or 0.0,
        }
        for r in rallies
    ]


def _get_rallies_for_match(db: Session, match_id: int) -> list[dict]:
    sets = db.query(GameSet).filter(GameSet.match_id == match_id).all()
    set_ids = [s.id for s in sets]
    if not set_ids:
        return []
    rallies = (
        db.query(Rally)
        .filter(Rally.set_id.in_(set_ids))
        .order_by(Rally.id)
        .all()
    )
    return [
        {
            "id":                    r.id,
            "set_id":                r.set_id,
            "rally_num":             r.rally_num,
            "video_timestamp_start": r.video_timestamp_start,
            "video_timestamp_end":   r.video_timestamp_end,
            "review_status":         r.review_status,
            "annotation_mode":       r.annotation_mode,
        }
        for r in rallies
    ]


def _get_strokes_for_rallies(db: Session, rally_ids: list[int]) -> list[dict]:
    if not rally_ids:
        return []
    strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(rally_ids))
        .order_by(Stroke.rally_id, Stroke.stroke_num)
        .all()
    )
    return [
        {
            "id":           s.id,
            "rally_id":     s.rally_id,
            "stroke_num":   s.stroke_num,
            "player":       s.player,
            "shot_type":    s.shot_type,
            "timestamp_sec": s.timestamp_sec,
            "land_zone":    s.land_zone,
            "source_method": s.source_method,
        }
        for s in strokes
    ]
