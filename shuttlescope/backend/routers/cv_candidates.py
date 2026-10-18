"""CV補助アノテーション候補API（/api/cv-candidates）

エンドポイント:
  POST /cv-candidates/build/{match_id}   — 候補を生成してアーティファクトに保存
  GET  /cv-candidates/{match_id}         — 生成済み候補を返す
  POST /cv-candidates/apply/{match_id}   — 高確信度候補をストロークに書き戻す
  PUT  /cv-candidates/review/{rally_id}  — ラリーのレビューステータスを更新

S-4（ラリー 0 本の動画の全体走査。案 A: CV は Rally/Stroke/GameSet を作らない）:
  POST /cv-candidates/scan/{match_id}                — video_import で動画全体を走査（二重起動は 409）
  GET  /cv-candidates/scan-status/{job_id}           — 走査ジョブの進捗
  GET  /cv-candidates/{match_id}/segments            — rally_boundaries の区間（operator 限定）
  POST /cv-candidates/{match_id}/segments/decisions  — 人の決定を追記（rally_boundary_decisions）
  POST /cv-candidates/{match_id}/segments/adopt      — 人が押したときだけ既存ラリーの時刻を設定

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
import math
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, GameSet, Rally, Stroke, MatchCVArtifact
from backend.cv.candidate_builder import build_candidates
from backend.yolo.cv_aligner import align_match

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_operator_role(request: Request) -> None:
    """CV 候補 (不確実な CV 出力) は admin / analyst / coach 専用。

    player / demo / llm には読み書きとも開けない (CLAUDE.md: player に研究・CV 候補を
    見せない)。出場試合の player を通す旧挙動では、自分の試合の cv_candidates /
    rally_boundaries / review-queue が読めた。ミドルウェアの許可リストに頼らず
    ルート自身で強制する (yolo.py の require_match_operator_scope と同じロール集合)。
    """
    from backend.utils.auth import get_auth as _ga
    ctx = _ga(request)
    if ctx.role is None:
        raise HTTPException(status_code=401, detail="認証が必要です")
    if not (ctx.is_admin or ctx.is_analyst or ctx.is_coach):
        raise HTTPException(status_code=403, detail="この操作の権限がありません")


def _require_match_team_scope(request: Request, db: Session, match_id: int) -> Match:
    """match_id に対する team-scope 強制 + auth check.

    - 未認証 → 401
    - player / demo / llm → 403 (CV 候補は admin/analyst/coach 専用)
    - admin → スルー
    - coach/analyst → 自チームの match (owner/home/away に自チームがあれば OK) のみ
    無ければ 404 (列挙耐性)。Round 258 P1 fix のため明示。
    """
    _require_operator_role(request)
    from backend.utils.auth import get_auth as _ga
    ctx = _ga(request)
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
    _require_operator_role(request)  # ラリー存在の有無を player に漏らさない
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
    # C-12: 「壊れていて読めなかった」と「そもそも無かった」を区別する。
    # 旧実装はどちらも空リストにして先へ進み、候補 0 件を `success: true` で
    # 返していた。読み手には «CV は走ったが何も見つからなかった» と映るし、
    # 両方壊れていたときに出る 400 は「先に CV 解析を実行してください」で、
    # 実際には解析済み・成果物が壊れているのに逆のことを言っていた。
    corrupt: list[str] = []

    def _load(artifact, label: str) -> list[dict]:
        if not artifact or not artifact.data:
            return []
        try:
            return json.loads(artifact.data)
        except Exception:
            logger.warning("%s artifact JSON 解析失敗 match_id=%d", label, match_id)
            corrupt.append(label)
            return []

    tracknet_frames = _load(tracknet_artifact, "TrackNet")
    yolo_frames     = _load(yolo_artifact, "YOLO")
    alignment_data  = _load(alignment_artifact, "アライメント")

    if corrupt:
        # 壊れた成果物を «無かったこと» にして候補を作ると、欠けたまま
        # 完成した顔の結果が残る。作り直しが要ることを言って止める。
        raise HTTPException(
            status_code=500,
            detail=(
                f"CV 成果物が読めません ({', '.join(corrupt)})。"
                "保存されたデータが壊れています。該当の CV 解析をやり直してください。"
            ),
        )

    # アライメントデータがなく両方揃っていれば即時計算
    if not alignment_data and tracknet_frames and yolo_frames:
        rally_boundaries = _get_rally_boundaries(db, match_id)
        try:
            from backend.cv.court_adapter import CourtAdapter
            alignment_data = align_match(
                yolo_frames,
                tracknet_frames,
                rally_boundaries,
                court_adapter=CourtAdapter.for_match(match_id),
            )
        except Exception as e:
            # アライメントは «あれば精度が上がる» 補助なので、失敗しても候補生成は
            # 続ける。ただし黙って落とすと «アライメント込みの結果» と区別が
            # 付かないので、成果物に残す (下の alignment_failed)。
            logger.warning("アライメント計算失敗: %s", e)
            alignment_failed = str(e) or e.__class__.__name__
        else:
            alignment_failed = None
    else:
        alignment_failed = None

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
    fps, fps_known = _resolve_match_fps(db, match_id)
    # CV ラベルは «画面の上側/下側» でしかないので、人に直すには開始サイドが要る。
    # 未設定なら翻訳せず要確認に落ちる (candidate_builder._attach_player_identity)。
    candidates = build_candidates(
        match_id=match_id,
        rallies_db=rallies_db,
        strokes_db=strokes_db,
        tracknet_frames=tracknet_frames,
        yolo_frames=yolo_frames,
        alignment_data=alignment_data,
        fps=fps,
        player_a_start_side=match.player_a_start_side,
    )
    # C-12: fps を推定できたかを成果物に残す。false のときは秒→フレーム換算が
    # ずれている可能性があり、ラリー境界候補の位置がそのぶん信用できない。
    # S-4: 境界検出の換算レートは成果物の実効サンプルレートになった。
    # rally_boundaries.time_axis が "sample_rate" なら動画 fps は境界位置に効かず、
    # "video_fps_fallback" のときだけ fps_known=false が境界位置の不確かさになる。
    if isinstance(candidates, dict):
        candidates["fps_used"] = fps
        candidates["fps_known"] = fps_known
        # C-12: アライメントを計算しようとして失敗したなら、その痕跡を残す。
        # 打者推定はアライメントがあるときと無いときで経路が変わる。
        candidates["alignment_failed"] = alignment_failed
        # A-1b の続き: キャリブレーションが無いと **着地ゾーンは一件も出ない**。
        # CV は画像座標から Zone9 を名乗るのをやめたので (ネット位置も半面も
        # 画像には入っていない)、コート座標に直せない試合では `zone` が常に
        # None になり、`candidate_builder` は候補を作らない。
        # その状態で画面に出るのは「CV候補なし」だけで、**なぜ無いのかが
        # 分からない**。理由を成果物に残して画面が言えるようにする。
        from backend.routers.court_calibration import load_calibration_from_db
        candidates["calibrated"] = bool(load_calibration_from_db(match_id, db))
        candidates["player_a_start_side_known"] = match.player_a_start_side in ("top", "bottom")

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
    fields: list[str] = ["land_zone", "hitter"]  # 適用するフィールド。hit_zone は明示指定時のみ

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
    # `Stroke.player` は «その試合の誰か» を指す。CV のラベルは «画面の上側/下側»
    # でしかないので、人に翻訳できていない候補は **mode="all" でも書かない**。
    # どちらの人か分からないまま、半分の確率で逆のものを確定値として残すことになる。
    if cand.get("player_identity_resolved") is False:
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
    fields, rally_ids）と併用可能。

    人の入力は書き換えない: land_zone は空欄か CV 自身が書いた値 (land_zone_source == "cv")
    だけ、hit_zone は空欄か CV 自身が書いた値 (hit_zone_source == "cv") だけ、
    打者(Stroke.player)は空の時だけ書く。人の値と食い違う
    候補は変更せず、レスポンスの preserved_count に数える。
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
    hit_zone_count = 0
    hitter_count = 0
    skipped_count = 0  # フィルタや条件で適用しなかったフィールド数
    # 人が入力済みで CV の候補と食い違うため、変更せずに残したフィールド数。
    # 人の入力を CV が黙って書き換えないための計数 (書き換えない理由の可視化)。
    preserved_count = 0

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

            # 着地ゾーン書き戻し。空欄か、CV 自身が前に書いた値 (land_zone_source == "cv")
            # だけを更新する。入力元が human または不明 (NULL) の値は人の入力として残す。
            if "land_zone" in body.fields:
                lz = sc.get("land_zone")
                if _field_passes_filters(lz, body, apply_modes):
                    if not stroke.land_zone or stroke.land_zone_source == "cv":
                        if stroke.land_zone != lz["value"] or stroke.land_zone_source != "cv":
                            stroke.land_zone = lz["value"]
                            stroke.land_zone_source = "cv"
                            land_zone_count += 1
                            changed = True
                    elif stroke.land_zone != lz["value"]:
                        preserved_count += 1
                elif lz:
                    skipped_count += 1

            # 打点ゾーン書き戻し。
            # D-1: CV hit_zone は空中シャトル位置ではなく、打球時の打者の
            # 足元を calibrated court へ投影した床面 Zone9。
            if "hit_zone" in body.fields:
                hz = sc.get("hit_zone")
                if _field_passes_filters(hz, body, apply_modes):
                    # 空欄か、CV 自身が前に書いた値 (hit_zone_source == "cv") だけを更新する。
                    # 入力元が manual または不明の値は人の入力として残す。
                    if not stroke.hit_zone or stroke.hit_zone_source == "cv":
                        if stroke.hit_zone != hz["value"] or stroke.hit_zone_source != "cv":
                            stroke.hit_zone = hz["value"]
                            stroke.hit_zone_source = "cv"
                            stroke.hit_zone_cv_original = hz["value"]
                            hit_zone_count += 1
                            changed = True
                    elif stroke.hit_zone != hz["value"]:
                        preserved_count += 1
                elif hz:
                    skipped_count += 1

            # 打者書き戻し
            if "hitter" in body.fields:
                ht = sc.get("hitter")
                if _field_passes_filters(ht, body, apply_modes):
                    # Stroke.player は入力時に必ず人が決める (NOT NULL)。CV の打者は
                    # それと突き合わせる候補であって、記録済みの打者を書き換える根拠にはならない。
                    if not stroke.player:
                        stroke.player = ht["value"]
                        hitter_count += 1
                        changed = True
                    elif stroke.player != ht["value"]:
                        preserved_count += 1
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
            "hit_zone_count":  hit_zone_count,
            "hitter_count":    hitter_count,
            "skipped_count":   skipped_count,
            "preserved_count": preserved_count,
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


# ────────────────────────────────────────────────────────────────────────────
# S-4: ラリー 0 本の動画の全体走査（案 A）
#
# CV は Rally / Stroke / GameSet 行を作らない。走査は video_import の既存の解析
# (_run_pipeline → _run_tracknet / _run_yolo) を呼ぶだけで、試合単位の成果物
# (coverage=full) に保存される。区間は rally_boundaries 成果物の `segments`。
# 人の決定は別種別 `rally_boundary_decisions`（追記のみ・1 決定 = 1 行）に置き、
# rally_boundaries の再ビルド（上書き）では消えない。
# ────────────────────────────────────────────────────────────────────────────

ARTIFACT_TYPE_BOUNDARY_DECISIONS = "rally_boundary_decisions"
_SCAN_JOB_KIND = "cv_scan"
# video_import.import_from_path と同じ拡張子集合（あちらは関数内ローカルなので写し）
_SCAN_VIDEO_EXTS = {'.mp4', '.avi', '.mov', '.mkv', '.wmv', '.flv', '.m4v', '.webm', '.ts', '.mts'}
_scan_lock = threading.Lock()  # 「実行中か」の確認とジョブ登録を 1 つの不可分操作にする


def _resolve_scan_video(match: Match) -> Path:
    """Match.video_local_path を video_import が読めるローカルファイルに解決する。

    routers/tracknet.py start_batch と同じ normalize_match_local_path を使い、
    video_import.import_from_path と同じ path_jail / 拡張子 / サイズの検査を通す。
    video_import は URL スキームを読めないので、読めないものはここで 400 にする。
    """
    from backend.utils.path_jail import normalize_match_local_path, is_allowed_video_path
    from backend.routers import video_import as _vi

    raw = (match.video_local_path or "").strip()
    if not raw:
        if match.video_url:
            raise HTTPException(
                status_code=400,
                detail="この試合の動画は URL（外部配信）のため全体走査できません。ローカルファイルの動画が必要です",
            )
        raise HTTPException(status_code=400, detail="動画ファイルが設定されていません")
    if any(ch in raw for ch in ("\x00", "\r", "\n")):
        raise HTTPException(status_code=400, detail="パスに不正な文字が含まれています")
    if raw.startswith(("http://", "https://")) or (
        re.match(r'^[a-zA-Z][a-zA-Z0-9+\-.]*://', raw)
        and not raw.startswith(("localfile:///", "server://"))
    ):
        raise HTTPException(
            status_code=400,
            detail="URL スキームの動画は全体走査できません（video_import はローカルファイルパスのみ読めます）",
        )
    is_server_ref = raw.startswith("server://")
    resolved = normalize_match_local_path(raw)
    if resolved is None:
        raise HTTPException(
            status_code=400,
            detail="動画の参照（server://）をローカルファイルに解決できません。全体走査には読めるローカルファイルが必要です",
        )
    if Path(str(resolved)).suffix.lower() not in _SCAN_VIDEO_EXTS:
        raise HTTPException(status_code=400, detail="動画ファイル以外は処理できません")
    path = Path(str(resolved)).resolve()
    if path.suffix.lower() not in _SCAN_VIDEO_EXTS:
        raise HTTPException(status_code=400, detail="動画ファイル以外は処理できません")
    # path_jail を存在確認より前に行う（許可ルート外の存在情報を漏らさない）
    if not is_allowed_video_path(path):
        if is_server_ref:
            raise HTTPException(
                status_code=400,
                detail="server:// の動画は video_import が読める許可ルート外にあるため全体走査できません",
            )
        raise HTTPException(status_code=403, detail="動画パスが許可ルート外です")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=400, detail="動画ファイルが存在しません")
    if path.stat().st_size > _vi._MAX_VIDEO_BYTES:
        raise HTTPException(status_code=413, detail="動画ファイルサイズが上限を超えています")
    return path


@router.post("/cv-candidates/scan/{match_id}")
def start_cv_scan(
    match_id: int,
    background_tasks: BackgroundTasks,
    request: Request,
    db: Session = Depends(get_db),
):
    """動画全体を TrackNet + YOLO で走査して試合単位の成果物に保存する（非同期）。

    新しい CV ロジックは持たず、video_import の _run_pipeline を呼ぶだけ。Rally /
    Stroke / GameSet 行は作らない。同じ試合の走査が実行中なら 409。
    完了後の候補化は既存の POST /cv-candidates/build/{match_id} で行う。
    """
    from backend.routers import video_import as _vi
    from backend.utils.auth import get_auth as _ga

    match = _require_match_team_scope(request, db, match_id)
    video_path = _resolve_scan_video(match)
    ctx = _ga(request)
    with _scan_lock:
        for jid, j in list(_vi._jobs.items()):
            if j.get("match_id") == match_id and j.get("phase") not in (_vi.Phase.DONE, _vi.Phase.ERROR):
                raise HTTPException(
                    status_code=409,
                    detail=f"この試合は既に動画の解析中です (job_id={jid})。",
                )
        job_id = uuid.uuid4().hex[:8]
        job = _vi._new_job(
            str(video_path), match_id,
            owner_user_id=ctx.user_id,
            owner_team_name=(ctx.team_name or None),
        )
        job["job_id"] = job_id
        job["kind"] = _SCAN_JOB_KIND
        _vi._jobs[job_id] = job
    background_tasks.add_task(_vi._run_pipeline, job_id)
    return {"success": True, "data": {"job_id": job_id, "match_id": match_id}}


@router.get("/cv-candidates/scan-status/{job_id}")
def get_cv_scan_status(job_id: str, request: Request, db: Session = Depends(get_db)):
    """走査ジョブの進捗。ジョブの試合に対する operator スコープを要求し、動画パスは返さない。"""
    from backend.routers import video_import as _vi

    _require_operator_role(request)
    job = _vi._jobs.get(job_id)
    if not job or job.get("kind") != _SCAN_JOB_KIND or job.get("match_id") is None:
        raise HTTPException(status_code=404, detail="ジョブが見つかりません")
    _require_match_team_scope(request, db, job["match_id"])
    return {
        "success": True,
        "data": {
            "job_id": job_id,
            "match_id": job["match_id"],
            "phase": job.get("phase"),
            "progress": job.get("progress"),
            "tracknet": job.get("tracknet"),
            "yolo": job.get("yolo"),
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
            "error": job.get("error"),
        },
    }


def _segment_key(start_sec: Optional[float], end_sec: Optional[float]) -> tuple:
    """決定の「時間区間キー」。小数 3 桁（成果物の timestamp_sec と同じ丸め）で比べる。"""
    return (
        None if start_sec is None else round(float(start_sec), 3),
        None if end_sec is None else round(float(end_sec), 3),
    )


def _read_decisions(db: Session, match_id: int) -> list[dict]:
    """rally_boundary_decisions を古い順に返す（読めない行は飛ばす）。"""
    rows = (
        db.query(MatchCVArtifact)
        .filter(
            MatchCVArtifact.match_id == match_id,
            MatchCVArtifact.artifact_type == ARTIFACT_TYPE_BOUNDARY_DECISIONS,
        )
        .order_by(MatchCVArtifact.id)
        .all()
    )
    out: list[dict] = []
    for row in rows:
        try:
            d = json.loads(row.data or "")
        except Exception:
            continue
        if isinstance(d, dict):
            d["decision_id"] = row.id
            out.append(d)
    return out


def _load_boundary_segments(db: Session, match_id: int) -> tuple[Optional[dict], Optional[str]]:
    """(rally_boundaries の中身, 読めなかった理由)。成果物が無ければ (None, 理由)。"""
    artifact = _latest_artifact(db, match_id, ARTIFACT_TYPE_RALLY_BOUNDARIES)
    if not artifact or not artifact.data:
        return None, "ラリー境界の成果物がありません（全体走査と候補生成が未実行）"
    try:
        data = json.loads(artifact.data)
    except Exception:
        return None, "ラリー境界の成果物が読めません（保存データが壊れています）"
    if not isinstance(data, dict):
        return None, "ラリー境界の成果物が読めません（形式が不正です）"
    return data, None


# ────────────────────────────────────────────────────────────────────────────
# GET /cv-candidates/{match_id}/segments
# ────────────────────────────────────────────────────────────────────────────

@router.get("/cv-candidates/{match_id}/segments")
def get_cv_segments(match_id: int, request: Request, db: Session = Depends(get_db)):
    """rally_boundaries の区間（segments）を返す。operator 限定（player には一切見せない）。

    各区間の data_status / open_ended / signal_score / coverage_ratio は成果物のまま。
    signal_score は「発火した信号数/3」の平均で統計的な確からしさではない。
    成果物が無い・サンプル不足のときは status="insufficient_data" と理由を返す
    （0 件を「ラリーが無い」と読ませない）。
    """
    _require_match_team_scope(request, db, match_id)
    decisions = _read_decisions(db, match_id)
    data, why = _load_boundary_segments(db, match_id)
    if data is None:
        return {"success": True, "data": {
            "match_id": match_id, "status": "insufficient_data", "reason": why,
            "segments": [], "decisions": decisions,
        }}
    seg_status = data.get("segments_status")
    segments = data.get("segments")
    if seg_status not in ("ok", "no_segments", "data_insufficient") or not isinstance(segments, list):
        return {"success": True, "data": {
            "match_id": match_id, "status": "insufficient_data",
            "reason": "区間（segments）を含まない旧形式の成果物です。候補を再生成してください",
            "segments": [], "decisions": decisions,
        }}
    latest: dict[tuple, dict] = {}
    for d in decisions:
        latest[_segment_key(d.get("start_sec"), d.get("end_sec"))] = d
    out_segments = []
    for seg in segments:
        s = dict(seg)
        s["latest_decision"] = latest.get(_segment_key(seg.get("start_sec"), seg.get("end_sec")))
        out_segments.append(s)
    return {"success": True, "data": {
        "match_id": match_id,
        "status": "insufficient_data" if seg_status == "data_insufficient" else seg_status,
        "reason": (
            "サンプル数が足りないため区間を主張できません" if seg_status == "data_insufficient" else None
        ),
        "sample_fps": data.get("sample_fps"),
        "time_axis": data.get("time_axis"),
        "sample_count": data.get("sample_count"),
        "segments": out_segments,
        "decisions": decisions,
    }}


# ────────────────────────────────────────────────────────────────────────────
# POST /cv-candidates/{match_id}/segments/decisions
# ────────────────────────────────────────────────────────────────────────────

def _finite_sec(v: Optional[float], name: str) -> None:
    if v is not None and not math.isfinite(v):
        raise ValueError(f"{name} は有限の数値で指定してください")


class SegmentDecisionRequest(BaseModel):
    model_config = {"extra": "forbid"}
    start_sec: Optional[float] = Field(default=None, ge=0, le=86400)
    end_sec: Optional[float] = Field(default=None, ge=0, le=86400)
    action: Literal["reject", "accept", "assign"]
    rally_id: Optional[int] = Field(default=None, ge=1, le=2_147_483_647)

    @model_validator(mode="after")
    def _check(self):
        _finite_sec(self.start_sec, "start_sec")
        _finite_sec(self.end_sec, "end_sec")
        if self.start_sec is None and self.end_sec is None:
            raise ValueError("start_sec と end_sec の少なくとも一方が必要です")
        if self.start_sec is not None and self.end_sec is not None and self.end_sec <= self.start_sec:
            raise ValueError("end_sec は start_sec より後にしてください")
        if self.action == "assign" and self.rally_id is None:
            raise ValueError("action=assign には rally_id が必要です")
        if self.action != "assign" and self.rally_id is not None:
            raise ValueError("rally_id は action=assign のときだけ指定できます")
        return self


def _rally_of_match(db: Session, match_id: int, rally_id: int) -> Rally:
    rally = (
        db.query(Rally)
        .join(GameSet, Rally.set_id == GameSet.id)
        .filter(Rally.id == rally_id, GameSet.match_id == match_id)
        .first()
    )
    if rally is None:
        raise HTTPException(status_code=404, detail="ラリーが見つかりません")
    return rally


def _new_decision_row(
    match_id: int, request: Request, *, start_sec, end_sec, action: str,
    rally_id: Optional[int], adopted: bool = False,
) -> tuple[MatchCVArtifact, dict]:
    """決定 1 件 = 成果物 1 行（INSERT のみ）。decided_by は認証済みユーザで、本文からは受けない。"""
    from backend.utils.auth import get_auth as _ga
    ctx = _ga(request)
    record = {
        "start_sec": start_sec,
        "end_sec": end_sec,
        "action": action,
        "rally_id": rally_id,
        "decided_by_user_id": ctx.user_id,
        "decided_at": datetime.utcnow().isoformat(),
    }
    if adopted:
        record["adopted"] = True  # 採用 API だけが付ける（decisions API の本文からは付けられない）
    row = MatchCVArtifact(
        match_id=match_id,
        artifact_type=ARTIFACT_TYPE_BOUNDARY_DECISIONS,
        summary=json.dumps({"action": action}, ensure_ascii=False),
        data=json.dumps(record, ensure_ascii=False),
    )
    return row, record


@router.post("/cv-candidates/{match_id}/segments/decisions")
def post_segment_decision(
    match_id: int,
    body: SegmentDecisionRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """区間への人の決定（reject / accept / assign）を追記する。operator 限定。

    rally_boundary_decisions に 1 行 INSERT するだけ。Rally / Stroke / GameSet には
    触れない。rally_boundaries の再ビルドでも消えない（別種別・CV は書かない）。
    """
    _require_match_team_scope(request, db, match_id)
    if body.rally_id is not None:
        _rally_of_match(db, match_id, body.rally_id)
    row, record = _new_decision_row(
        match_id, request, start_sec=body.start_sec, end_sec=body.end_sec,
        action=body.action, rally_id=body.rally_id,
    )
    db.add(row)
    db.commit()
    record["decision_id"] = row.id
    return {"success": True, "data": record}


# ────────────────────────────────────────────────────────────────────────────
# POST /cv-candidates/{match_id}/segments/adopt
# ────────────────────────────────────────────────────────────────────────────

class SegmentAdoptRequest(BaseModel):
    model_config = {"extra": "forbid"}
    start_sec: float = Field(..., ge=0, le=86400)
    end_sec: float = Field(..., ge=0, le=86400)
    rally_id: int = Field(..., ge=1, le=2_147_483_647)

    @model_validator(mode="after")
    def _check(self):
        _finite_sec(self.start_sec, "start_sec")
        _finite_sec(self.end_sec, "end_sec")
        if self.end_sec <= self.start_sec:
            raise ValueError("end_sec は start_sec より後にしてください")
        return self


def _adopt_refusal(db: Session, match_id: int, rally: Rally) -> Optional[str]:
    """採用してはいけない理由（無ければ None）。人が入れた時刻を上書きしないための検査。

    書いてよいのは次のどちらかだけ:
      - 対象ラリーの video_timestamp_start が None（未入力）
      - 対象ラリーが 0.0 で、試合の全ラリーが「0.0 / None / この API で採用済みの値のまま」
        （試合 32 型: 全ラリーが 0.0 で入っている。0.0 は「未入力」と「本当に 0 秒」を
        区別できないので、他に人が入れた時刻が 1 つでもあれば書かない）
    end は None または 0.0 のときだけ書く（非 0 の end は人の入力として残す）。
    """
    cur_start = rally.video_timestamp_start
    cur_end = rally.video_timestamp_end
    if cur_end is not None and cur_end != 0.0:
        return (
            f"ラリー {rally.id} の終了時刻が既に入力されています（{cur_end}）。人が入れた値は上書きしません"
        )
    if cur_start is None:
        return None
    if cur_start != 0.0:
        return (
            f"ラリー {rally.id} の開始時刻が既に入力されています（{cur_start}）。人が入れた値は上書きしません"
        )
    # cur_start == 0.0: 全ラリーが 0.0 / None / 採用済みのままのときだけ「未入力の 0.0」とみなす
    adopted: dict[int, float] = {}
    for d in _read_decisions(db, match_id):
        if d.get("adopted") and d.get("rally_id") is not None and d.get("start_sec") is not None:
            adopted[int(d["rally_id"])] = float(d["start_sec"])
    rallies = (
        db.query(Rally)
        .join(GameSet, Rally.set_id == GameSet.id)
        .filter(GameSet.match_id == match_id)
        .all()
    )
    for r in rallies:
        s = r.video_timestamp_start
        if s is None or s == 0.0:
            continue
        if r.id in adopted and abs(adopted[r.id] - s) < 1e-6:
            continue
        return (
            "この試合には人が入力した開始時刻を持つラリーがあるため、0.0 を未入力とみなせません"
            f"（ラリー {r.id} = {s}）。人が入れた値は上書きしません"
        )
    return None


@router.post("/cv-candidates/{match_id}/segments/adopt")
def adopt_segment(
    match_id: int,
    body: SegmentAdoptRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """人が押したときだけ、既存ラリーの video_timestamp_start/end を候補区間の時刻にする。

    PUT /rallies/{id} と同じコード（routers/rallies.update_rally）で書くので、
    sync メタデータ（updated_at / revision / content_hash）も同じ扱い。書く列は
    video_timestamp_start / video_timestamp_end の 2 つだけで、Stroke は変えず、
    Rally / GameSet 行は作らない。_adopt_refusal に当たれば 409。
    """
    _require_match_team_scope(request, db, match_id)
    rally = _rally_of_match(db, match_id, body.rally_id)

    data, why = _load_boundary_segments(db, match_id)
    wanted = _segment_key(body.start_sec, body.end_sec)
    found = False
    if data is not None and isinstance(data.get("segments"), list):
        found = any(
            seg.get("start_sec") is not None and seg.get("end_sec") is not None
            and _segment_key(seg["start_sec"], seg["end_sec"]) == wanted
            for seg in data["segments"]
        )
    if not found:
        raise HTTPException(
            status_code=404,
            detail="指定の区間は候補（rally_boundaries の segments、開始・終了が揃ったもの）にありません",
        )

    refusal = _adopt_refusal(db, match_id, rally)
    if refusal:
        raise HTTPException(status_code=409, detail=refusal)

    row, record = _new_decision_row(
        match_id, request, start_sec=body.start_sec, end_sec=body.end_sec,
        action="assign", rally_id=rally.id, adopted=True,
    )
    from backend.routers.rallies import RallyUpdate, update_rally
    try:
        db.add(row)
        db.flush()
        # 決定の行と時刻の更新は update_rally の commit で同時に確定する
        result = update_rally(
            rally.id,
            RallyUpdate(video_timestamp_start=body.start_sec, video_timestamp_end=body.end_sec),
            request,
            db,
        )
    except Exception:
        db.rollback()
        raise
    record["decision_id"] = row.id
    return {"success": True, "data": {"rally": result["data"], "decision": record}}


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


def _resolve_match_fps(
    db: Session, match_id: int, default: float = 60.0
) -> tuple[float, bool]:
    """ラリー境界検出の秒→frame 換算に使う FPS を解決する。

    Returns: (fps, known) — known=False なら **推定できず default を使った**。

    C-12: 旧実装は `except Exception: pass` のあと黙って 60.0 を返していた。
    30fps 素材では秒→フレーム換算が全て 2 倍ずれるのに、出力には
    「fps が分からなかった」という痕跡が一切残らない。
    DB エラーと「Recording が無い」も区別していなかった。
    呼び出し側が成果物に残せるよう、推定できたかどうかを返す。
    """
    from backend.db.models import Recording
    try:
        rec = (
            db.query(Recording)
            .filter(Recording.match_id == match_id, Recording.fps != None)  # noqa: E711
            .order_by(Recording.branch_no)
            .first()
        )
    except Exception as exc:
        logger.warning(
            "[cv_candidates] match=%s の fps 取得に失敗: %s — %.1f を仮定する",
            match_id, exc, default,
        )
        return default, False
    if rec and rec.fps and rec.fps > 0:
        return float(rec.fps), True
    logger.warning(
        "[cv_candidates] match=%s に fps を持つ Recording が無い — %.1f を仮定する。"
        " 素材が %.0ffps でなければ秒→フレーム換算がずれる",
        match_id, default, default,
    )
    return default, False


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
        "sample_fps":     rally_boundaries.get("sample_fps"),
        "time_axis":      rally_boundaries.get("time_axis"),
        "segment_count":  len(rally_boundaries.get("segments", []) or []),
        "segments_status": rally_boundaries.get("segments_status"),
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
    set_num_by_id = {s.id: s.set_num for s in sets}
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
            # CV ラベル (画面上の位置) を人に翻訳するのに要る。
            # エンド交替はセット単位、最終セットは 11 点でもう一度替わる。
            "set_num":               set_num_by_id.get(r.set_id),
            "score_a_before":        r.score_a_before,
            "score_b_before":        r.score_b_before,
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
