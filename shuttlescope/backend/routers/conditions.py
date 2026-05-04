"""コンディション（体調）記録 API（/api/conditions）。

Phase 1: InBody / Hooper / RPE / 自由記述 CRUD（直接入力では採点列は触れない）。
Phase 2: 質問票マスター & 質問票 POST で採点・妥当性・本人内変動を算出して保存。

仕様書の質問文字列は FE i18n に集約し、backend コード/コメントには引用しない。
"""
from __future__ import annotations

import json
from datetime import date as _date, datetime
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.analysis.condition_questions import (
    PRE_MATCH_REQUIRED_IDS,
    WEEKLY_REQUIRED_IDS,
    get_master,
)
from backend.analysis.condition_scoring import (
    calc_deviation,
    calc_factor_scores,
    calc_pre_match_score,
    calc_validity,
    factor_label_from_z,
)
from backend.analysis.condition_analytics import (
    best_performance_profile,
    correlation_series,
    detect_discrepancy,
    player_growth_insights,
)
from backend.db.database import get_db
from backend.db.models import Condition, Match, Player

router = APIRouter(prefix="/api/conditions", tags=["conditions"])


ALLOWED_ROLES = {"player", "coach", "analyst", "admin"}


def resolve_role(
    request: Request,
    x_role: Optional[str] = Header(None, alias="X-Role"),
    role: Optional[str] = Query(None),
) -> str:
    """JWT → X-Role ヘッダ → ?role= の優先順でロールを解決する。
    JWT なし + 非ローカル接続は 401 を返す（ロールクエリパラ昇格防止）。
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        from backend.utils.jwt_utils import verify_token
        payload = verify_token(token)
        if payload:
            r = (payload.get("role") or "").strip().lower()
            if r == "admin":
                r = "analyst"
            if r in ALLOWED_ROLES:
                return r
    # JWT なし: loopback（Electron/テスト）のみ X-Role/クエリパラを受け付ける
    from backend.utils.control_plane import allow_legacy_header_auth
    if not allow_legacy_header_auth(request):
        raise HTTPException(status_code=401, detail="認証が必要です")
    r = (x_role or role or "analyst").strip().lower()
    if r == "admin":
        r = "analyst"
    if r not in ALLOWED_ROLES:
        raise HTTPException(status_code=400, detail=f"invalid role: {r}")
    return r


# ─── Pydantic Schemas ────────────────────────────────────────────────────────

class ConditionCreate(BaseModel):
    """直接入力（InBody/Hooper/RPE/補助）。
    f1-f5 / total / ccs / validity / deviation は質問票経由でのみ書き込み可。

    id / created_by / created_at / updated_at 等の内部フィールドを body で指定して
    mass assignment する攻撃を extra=forbid で 422 拒否する。
    各数値フィールドは人体として現実的な範囲に制限 (APT による偽データ捏造対策)。
    """
    model_config = {"extra": "forbid"}
    player_id: int
    measured_at: _date
    condition_type: str = "weekly"

    # InBody 体組成: 人体の現実的範囲
    weight_kg: Optional[float] = Field(default=None, ge=20, le=200)
    muscle_mass_kg: Optional[float] = Field(default=None, ge=0, le=150)
    body_fat_pct: Optional[float] = Field(default=None, ge=0, le=80)
    body_fat_mass_kg: Optional[float] = Field(default=None, ge=0, le=100)
    lean_mass_kg: Optional[float] = Field(default=None, ge=0, le=150)
    ecw_ratio: Optional[float] = Field(default=None, ge=0.3, le=0.5)
    arm_l_muscle_kg: Optional[float] = Field(default=None, ge=0, le=10)
    arm_r_muscle_kg: Optional[float] = Field(default=None, ge=0, le=10)
    leg_l_muscle_kg: Optional[float] = Field(default=None, ge=0, le=30)
    leg_r_muscle_kg: Optional[float] = Field(default=None, ge=0, le=30)
    trunk_muscle_kg: Optional[float] = Field(default=None, ge=0, le=40)
    bmr_kcal: Optional[float] = Field(default=None, ge=500, le=5000)

    # Hooper スケールは通常 1-7 (7 段階 Likert)
    hooper_sleep: Optional[int] = Field(default=None, ge=1, le=7)
    hooper_soreness: Optional[int] = Field(default=None, ge=1, le=7)
    hooper_stress: Optional[int] = Field(default=None, ge=1, le=7)
    hooper_fatigue: Optional[int] = Field(default=None, ge=1, le=7)

    # Session RPE は Borg CR-10 スケール (0-10)
    session_rpe: Optional[int] = Field(default=None, ge=0, le=10)
    # 1 セッション 0-480 分 (8 時間) まで
    session_duration_min: Optional[int] = Field(default=None, ge=0, le=480)

    # 睡眠時間 0-24 時間
    sleep_hours: Optional[float] = Field(default=None, ge=0, le=24)
    injury_notes: Optional[str] = Field(default=None, max_length=2000)
    general_comment: Optional[str] = Field(default=None, max_length=2000)
    match_id: Optional[int] = Field(default=None, ge=1, le=2**31 - 1)


class ConditionUpdate(BaseModel):
    # 未知フィールドの silent drop を禁止 (id/created_at/player_id 等の改竄を防ぐ)
    # 特に player_id 書換による tenant 越境/なりすましを 422 で明示拒否する
    model_config = {"extra": "forbid"}
    measured_at: Optional[_date] = None
    condition_type: Optional[str] = None

    # 各数値フィールドは人体として現実的な範囲 (ConditionCreate と同じ)
    weight_kg: Optional[float] = Field(default=None, ge=20, le=200)
    muscle_mass_kg: Optional[float] = Field(default=None, ge=0, le=150)
    body_fat_pct: Optional[float] = Field(default=None, ge=0, le=80)
    body_fat_mass_kg: Optional[float] = Field(default=None, ge=0, le=100)
    lean_mass_kg: Optional[float] = Field(default=None, ge=0, le=150)
    ecw_ratio: Optional[float] = Field(default=None, ge=0.3, le=0.5)
    arm_l_muscle_kg: Optional[float] = Field(default=None, ge=0, le=10)
    arm_r_muscle_kg: Optional[float] = Field(default=None, ge=0, le=10)
    leg_l_muscle_kg: Optional[float] = Field(default=None, ge=0, le=30)
    leg_r_muscle_kg: Optional[float] = Field(default=None, ge=0, le=30)
    trunk_muscle_kg: Optional[float] = Field(default=None, ge=0, le=40)
    bmr_kcal: Optional[float] = Field(default=None, ge=500, le=5000)

    hooper_sleep: Optional[int] = Field(default=None, ge=1, le=7)
    hooper_soreness: Optional[int] = Field(default=None, ge=1, le=7)
    hooper_stress: Optional[int] = Field(default=None, ge=1, le=7)
    hooper_fatigue: Optional[int] = Field(default=None, ge=1, le=7)

    session_rpe: Optional[int] = Field(default=None, ge=0, le=10)
    session_duration_min: Optional[int] = Field(default=None, ge=0, le=480)

    sleep_hours: Optional[float] = Field(default=None, ge=0, le=24)
    injury_notes: Optional[str] = Field(default=None, max_length=2000)
    general_comment: Optional[str] = Field(default=None, max_length=2000)
    match_id: Optional[int] = Field(default=None, ge=1, le=2**31 - 1)


class AuxiliaryInput(BaseModel):
    sleep_hours: Optional[float] = None
    injury_notes: Optional[str] = None
    general_comment: Optional[str] = None


class QuestionnaireSubmit(BaseModel):
    player_id: int
    measured_at: _date
    condition_type: str = Field(..., pattern="^(weekly|pre_match)$")
    responses: Dict[str, int]
    match_id: Optional[int] = None
    auxiliary: Optional[AuxiliaryInput] = None


# ─── 自動計算ヘルパ ──────────────────────────────────────────────────────────

def _compute_hooper_index(c: Condition) -> Optional[int]:
    parts = [c.hooper_sleep, c.hooper_soreness, c.hooper_stress, c.hooper_fatigue]
    if any(p is None for p in parts):
        return None
    return int(sum(parts))  # type: ignore[arg-type]


def _compute_session_load(c: Condition) -> Optional[int]:
    if c.session_rpe is None or c.session_duration_min is None:
        return None
    return int(c.session_rpe) * int(c.session_duration_min)


def _recompute(c: Condition) -> None:
    c.hooper_index = _compute_hooper_index(c)
    c.session_load = _compute_session_load(c)


# ─── role 別シリアライズ ─────────────────────────────────────────────────────

def _full_dict(c: Condition) -> dict:
    return {
        "id": c.id,
        "player_id": c.player_id,
        "measured_at": c.measured_at.isoformat() if c.measured_at else None,
        "condition_type": c.condition_type,
        "match_id": c.match_id,
        "weight_kg": c.weight_kg,
        "muscle_mass_kg": c.muscle_mass_kg,
        "body_fat_pct": c.body_fat_pct,
        "body_fat_mass_kg": c.body_fat_mass_kg,
        "lean_mass_kg": c.lean_mass_kg,
        "ecw_ratio": c.ecw_ratio,
        "arm_l_muscle_kg": c.arm_l_muscle_kg,
        "arm_r_muscle_kg": c.arm_r_muscle_kg,
        "leg_l_muscle_kg": c.leg_l_muscle_kg,
        "leg_r_muscle_kg": c.leg_r_muscle_kg,
        "trunk_muscle_kg": c.trunk_muscle_kg,
        "bmr_kcal": c.bmr_kcal,
        "hooper_sleep": c.hooper_sleep,
        "hooper_soreness": c.hooper_soreness,
        "hooper_stress": c.hooper_stress,
        "hooper_fatigue": c.hooper_fatigue,
        "hooper_index": c.hooper_index,
        "session_rpe": c.session_rpe,
        "session_duration_min": c.session_duration_min,
        "session_load": c.session_load,
        "questionnaire_json": c.questionnaire_json,
        "f1_physical": c.f1_physical,
        "f2_stress": c.f2_stress,
        "f3_mood": c.f3_mood,
        "f4_motivation": c.f4_motivation,
        "f5_sleep_life": c.f5_sleep_life,
        "total_score": c.total_score,
        "ccs_score": c.ccs_score,
        "delta_prev": c.delta_prev,
        "delta_3ma": c.delta_3ma,
        "delta_28ma": c.delta_28ma,
        "z_score": c.z_score,
        "validity_score": c.validity_score,
        "validity_flag": c.validity_flag,
        "validity_flags_json": c.validity_flags_json,
        "sleep_hours": c.sleep_hours,
        "injury_notes": c.injury_notes,
        "general_comment": c.general_comment,
        "created_at": c.created_at.isoformat() if c.created_at else None,
        "updated_at": c.updated_at.isoformat() if c.updated_at else None,
    }


def _factor_labels_from_cond(c: Condition) -> Dict[str, str]:
    """F1..F5 の「良好/少し注意/注意」ラベル。グローバル z の絶対値で簡易判定。
    Phase 2 ではグローバル z しか持たないため、F? の相対表示用に同じラベルを流用。
    """
    z = c.z_score
    label = factor_label_from_z(z)
    return {
        "f1_physical": label,
        "f2_stress": label,
        "f3_mood": label,
        "f4_motivation": label,
        "f5_sleep_life": label,
    }


def _player_view(c: Condition) -> dict:
    # Condition モデルには mean_28/sd_28 列は保存していないため、
    # ccs_score / delta_28ma / z_score から逆算する。
    mean_28 = None
    sd_28 = None
    if c.ccs_score is not None and c.delta_28ma is not None:
        mean_28 = float(c.ccs_score) - float(c.delta_28ma)
    if c.z_score is not None and c.delta_28ma is not None and c.z_score != 0:
        sd_28 = abs(float(c.delta_28ma) / float(c.z_score))

    personal_range = None
    if mean_28 is not None and sd_28 is not None:
        personal_range = {"low": mean_28 - sd_28, "high": mean_28 + sd_28}

    return {
        "id": c.id,
        "player_id": c.player_id,
        "measured_at": c.measured_at.isoformat() if c.measured_at else None,
        "condition_type": c.condition_type,
        "ccs_score": c.ccs_score,
        "delta_28ma": c.delta_28ma,
        "mean_28": mean_28,
        "sd_28": sd_28,
        "personal_range": personal_range,
        "factor_labels": _factor_labels_from_cond(c),
    }


def _coach_view(c: Condition) -> dict:
    base = _player_view(c)
    base.update({
        "f1_physical": c.f1_physical,
        "f2_stress": c.f2_stress,
        "f3_mood": c.f3_mood,
        "f4_motivation": c.f4_motivation,
        "f5_sleep_life": c.f5_sleep_life,
        "total_score": c.total_score,
        "validity_flag": c.validity_flag,
        "hooper_index": c.hooper_index,
        "session_load": c.session_load,
        "sleep_hours": c.sleep_hours,
        "match_id": c.match_id,
        "delta_prev": c.delta_prev,
        "delta_3ma": c.delta_3ma,
        "z_score": c.z_score,
    })
    return base


def _serialize(c: Condition, role: str) -> dict:
    if role == "player":
        return _player_view(c)
    if role == "coach":
        return _coach_view(c)
    return _full_dict(c)


# ─── マスター ────────────────────────────────────────────────────────────────

@router.get("/master")
def get_questionnaire_master(
    condition_type: str = Query("weekly", pattern="^(weekly|pre_match)$"),
):
    """質問票マスター（ID/因子/スケール/逆転フラグ + i18n キー）を返す。"""
    return {"success": True, "data": get_master(condition_type)}


# ─── 質問票 submit ───────────────────────────────────────────────────────────

@router.post("/questionnaire", status_code=201)
def submit_questionnaire(body: QuestionnaireSubmit, request: Request, db: Session = Depends(get_db)):
    from backend.utils.auth import get_auth as _ga_q
    from backend.utils.control_plane import allow_legacy_header_auth as _allow_q
    _ctx_q = _ga_q(request)
    if _ctx_q.role is None and not _allow_q(request):
        raise HTTPException(status_code=401, detail="認証が必要です")

    player = db.get(Player, body.player_id)
    if not player:
        raise HTTPException(status_code=404, detail="選手が見つかりません")

    # 必須 ID チェック
    required = (
        WEEKLY_REQUIRED_IDS if body.condition_type == "weekly" else PRE_MATCH_REQUIRED_IDS
    )
    missing = [q for q in required if q not in body.responses]
    if missing:
        raise HTTPException(
            status_code=422,
            detail={"error": "missing_responses", "missing_ids": missing},
        )

    # 値域チェック（1..5 int）
    for qid, v in body.responses.items():
        if not isinstance(v, int) or v < 1 or v > 5:
            raise HTTPException(
                status_code=422,
                detail={"error": "invalid_response_value", "id": qid, "value": v},
            )

    # match_id バリデーション
    if body.match_id is not None:
        if not db.get(Match, body.match_id):
            raise HTTPException(status_code=404, detail="試合が見つかりません")

    # 採点
    if body.condition_type == "weekly":
        scores = calc_factor_scores(body.responses)
    else:
        scores = {
            "f1_physical": None, "f2_stress": None, "f3_mood": None,
            "f4_motivation": None, "f5_sleep_life": None,
            "total_score": calc_pre_match_score(body.responses)["pre_match_total"],
            # pre_match では ccs は直接算出しない（10..50 点の単純合計を total に保存）
            "ccs_score": None,
        }

    # 履歴（同 player の既存 weekly CCS を古→新）
    history_rows = (
        db.query(Condition)
        .filter(
            Condition.player_id == body.player_id,
            Condition.condition_type == "weekly",
            Condition.ccs_score.isnot(None),
        )
        .order_by(Condition.measured_at.asc(), Condition.id.asc())
        .all()
    )
    history_ccs = [float(r.ccs_score) for r in history_rows if r.ccs_score is not None]

    # 妥当性
    current_ccs_for_validity = scores["ccs_score"] if body.condition_type == "weekly" else None
    validity = calc_validity(body.responses, history_ccs, current_ccs_for_validity)

    # 本人内変動（weekly のみ）
    if body.condition_type == "weekly" and scores["ccs_score"] is not None:
        dev = calc_deviation(float(scores["ccs_score"]), history_ccs)
    else:
        dev = {"delta_prev": None, "delta_3ma": None, "delta_28ma": None,
               "z_score": None, "mean_28": None, "sd_28": None}

    aux = body.auxiliary or AuxiliaryInput()

    cond = Condition(
        player_id=body.player_id,
        measured_at=body.measured_at,
        condition_type=body.condition_type,
        match_id=body.match_id,
        questionnaire_json=json.dumps(body.responses, ensure_ascii=False),
        f1_physical=scores["f1_physical"],
        f2_stress=scores["f2_stress"],
        f3_mood=scores["f3_mood"],
        f4_motivation=scores["f4_motivation"],
        f5_sleep_life=scores["f5_sleep_life"],
        total_score=scores["total_score"],
        ccs_score=scores["ccs_score"],
        delta_prev=dev["delta_prev"],
        delta_3ma=dev["delta_3ma"],
        delta_28ma=dev["delta_28ma"],
        z_score=dev["z_score"],
        validity_score=validity["validity_score"],
        validity_flag=validity["validity_flag"],
        validity_flags_json=json.dumps(validity["flags_list"], ensure_ascii=False),
        sleep_hours=aux.sleep_hours,
        injury_notes=aux.injury_notes,
        general_comment=aux.general_comment,
    )
    db.add(cond)
    db.commit()
    db.refresh(cond)
    # analyst ビュー（完全）で返却
    return {"success": True, "data": _full_dict(cond)}


# ─── 直接入力 CRUD ───────────────────────────────────────────────────────────

from backend.utils.access_log import log_access as _log_acc_cond


def _reject_xss_condition_text(value: Optional[str], field: str) -> None:
    """condition のテキストフィールドに HTML タグ / 制御文字を仕込まれるのを拒否。

    round130 Y-3: 元の deny-list (script/iframe/...) は `<%= ... %>` 等の非標準
    タグを通していた。任意の `<...>` を含む入力は全て reject に変更。
    """
    if value is None:
        return
    import re as _r
    if "<" in value or ">" in value:
        raise HTTPException(status_code=422, detail=f"{field} contains '<' or '>' (disallowed)")
    if _r.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", value):
        raise HTTPException(status_code=422, detail=f"{field} contains control characters")
    if len(value) > 2000:
        raise HTTPException(status_code=422, detail=f"{field} too long (max 2000)")


@router.post("", status_code=201)
def create_condition(body: ConditionCreate, request: Request, db: Session = Depends(get_db)):
    # XSS/制御文字/長さ検証 (stored XSS 対策・多層防御)
    _reject_xss_condition_text(body.injury_notes, "injury_notes")
    _reject_xss_condition_text(body.general_comment, "general_comment")
    # measured_at の範囲検証 (1900-01-01 / 3000-01-01 等の偽データ投入を防止)
    # 実測: 今日 ± 5 年の範囲に限定。未来/過去 100 年のデータ混入攻撃を遮断。
    from datetime import date as _date_cc, timedelta as _td_cc
    today = _date_cc.today()
    if body.measured_at > today + _td_cc(days=7):  # 1 週間先までは予定入力を許容
        raise HTTPException(status_code=422, detail="measured_at が未来すぎます")
    if body.measured_at < today - _td_cc(days=365 * 5):  # 5 年より古い日付は拒否
        raise HTTPException(status_code=422, detail="measured_at が過去すぎます (5 年以内)")
    # player ロールは自 player_id のコンディションのみ作成可能。
    # 他 player のコンディションをでっち上げる「偽データ混入」攻撃を遮断。
    from backend.utils.auth import get_auth
    from backend.utils.control_plane import allow_legacy_header_auth
    ctx = get_auth(request)
    if ctx.role is None and not allow_legacy_header_auth(request):
        raise HTTPException(status_code=401, detail="認証が必要です")
    if ctx.is_player:
        if not ctx.player_id or body.player_id != ctx.player_id:
            raise HTTPException(status_code=403, detail="自分のコンディションのみ登録できます")
    elif ctx.is_coach:
        # coach は自チーム選手のコンディションのみ登録可能
        team = (ctx.team_name or "").strip()
        if not team:
            raise HTTPException(status_code=403, detail="team_name 未設定のため登録できません")
        target_player = db.get(Player, body.player_id)
        if not target_player or (target_player.team or "").strip() != team:
            raise HTTPException(status_code=403, detail="自チーム選手のみ登録できます")
    # analyst / admin は全選手に登録可能

    player = db.get(Player, body.player_id)
    if not player:
        raise HTTPException(status_code=404, detail="選手が見つかりません")
    if body.match_id is not None and not db.get(Match, body.match_id):
        raise HTTPException(status_code=404, detail="試合が見つかりません")

    data = body.model_dump()
    cond = Condition(**data)
    _recompute(cond)
    db.add(cond)
    db.commit()
    db.refresh(cond)
    # audit log: 誰がどの player の condition を登録したか forensic 追跡用
    try:
        _log_acc_cond(
            db, "condition_created", user_id=ctx.user_id,
            resource_type="condition", resource_id=cond.id,
            details={"actor_role": ctx.role, "target_player_id": body.player_id,
                     "condition_type": body.condition_type},
        )
    except Exception:
        pass
    return {"success": True, "data": _full_dict(cond)}


@router.get("")
def list_conditions(
    request: Request,
    player_id: Optional[int] = Query(None, ge=1, le=2_147_483_647),
    limit: int = Query(100, ge=1, le=1000),
    since: Optional[_date] = Query(None),
    role: str = Depends(resolve_role),
    db: Session = Depends(get_db),
):
    # player ロールは自分の player_id のみ閲覧可能。他 player のコンディション生データ
    # (ccs_score / delta / personal_range 等) はプライバシー情報であり漏洩を防ぐ。
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if ctx.is_player:
        if not ctx.player_id:
            raise HTTPException(status_code=403, detail="player_id 未設定")
        if player_id is not None and player_id != ctx.player_id:
            raise HTTPException(status_code=403, detail="他選手のコンディションは参照できません")
        player_id = ctx.player_id

    q = db.query(Condition)
    # coach / analyst は自チーム選手の conditions のみ (cross-team 漏洩防止)
    if ctx.is_coach or ctx.is_analyst:
        team = (ctx.team_name or "").strip()
        if not team:
            from backend.utils.control_plane import allow_legacy_header_auth
            if not allow_legacy_header_auth(request):
                return {"success": True, "data": []}
            # loopback dev/test では全件
        else:
            # Phase B-15+: team 文字列撤去後は teams.name JOIN で解決
            from backend.db.models import Player as _P, Team as _Team
            team_player_ids = [
                p.id for p in db.query(_P.id)
                    .join(_Team, _Team.id == _P.team_id)
                    .filter(_Team.name == team, _Team.deleted_at.is_(None))
                    .all()
            ]
            if not team_player_ids:
                return {"success": True, "data": []}
            q = q.filter(Condition.player_id.in_(team_player_ids))
    if player_id is not None:
        q = q.filter(Condition.player_id == player_id)
    if since is not None:
        q = q.filter(Condition.measured_at >= since)
    rows = q.order_by(Condition.measured_at.desc(), Condition.id.desc()).limit(limit).all()
    return {"success": True, "data": [_serialize(c, role) for c in rows]}


@router.patch("/{condition_id}")
def update_condition(condition_id: int, body: ConditionUpdate, request: Request, db: Session = Depends(get_db)):
    cond = db.get(Condition, condition_id)
    if not cond:
        raise HTTPException(status_code=404, detail="コンディション記録が見つかりません")
    _require_condition_access(request, cond)
    # XSS/制御文字/長さ検証
    _reject_xss_condition_text(body.injury_notes, "injury_notes")
    _reject_xss_condition_text(body.general_comment, "general_comment")
    # audit log (forensic): 誰がどの player の condition を編集したか
    try:
        from backend.utils.auth import get_auth as _ga
        _ctx = _ga(request)
        _log_acc_cond(
            db, "condition_updated", user_id=_ctx.user_id,
            resource_type="condition", resource_id=condition_id,
            details={"actor_role": _ctx.role, "target_player_id": cond.player_id,
                     "fields": list(body.model_dump(exclude_unset=True).keys())},
        )
    except Exception:
        pass
    data = body.model_dump(exclude_unset=True)
    if "match_id" in data and data["match_id"] is not None:
        if not db.get(Match, data["match_id"]):
            raise HTTPException(status_code=404, detail="試合が見つかりません")
    from backend.utils.db_update import apply_update
    apply_update(cond, data)
    _recompute(cond)
    db.commit()
    db.refresh(cond)
    return {"success": True, "data": _full_dict(cond)}


# ─── Phase 3: 解析系エンドポイント ───────────────────────────────────────────

def _match_to_dict(m: Match) -> dict:
    return {
        "id": m.id,
        "date": m.date,
        "result": m.result,
        "player_a_id": m.player_a_id,
        "player_b_id": m.player_b_id,
        "partner_a_id": m.partner_a_id,
        "partner_b_id": m.partner_b_id,
    }


def _load_player_conditions(db: Session, player_id: int, since: Optional[_date]) -> List[dict]:
    q = db.query(Condition).filter(Condition.player_id == player_id)
    if since is not None:
        q = q.filter(Condition.measured_at >= since)
    rows = q.order_by(Condition.measured_at.asc(), Condition.id.asc()).all()
    return [_full_dict(c) for c in rows]


def _load_player_matches(db: Session, player_id: int, since: Optional[_date]) -> List[dict]:
    q = db.query(Match).filter(
        (Match.player_a_id == player_id)
        | (Match.player_b_id == player_id)
        | (Match.partner_a_id == player_id)
        | (Match.partner_b_id == player_id)
    )
    if since is not None:
        q = q.filter(Match.date >= since)
    rows = q.order_by(Match.date.asc()).all()
    return [_match_to_dict(m) for m in rows]


@router.get("/correlation")
def get_correlation(
    player_id: int = Query(...),
    x: str = Query(...),
    y: str = Query(...),
    since: Optional[_date] = Query(None),
    role: str = Depends(resolve_role),
    db: Session = Depends(get_db),
):
    """x=condition 指標、y=condition or 試合指標（win_rate）の相関。

    role filter: player には raw 条件配列は返さず point の (x, y) 集計のみ。
    """
    if not db.get(Player, player_id):
        raise HTTPException(status_code=404, detail="選手が見つかりません")
    conds = _load_player_conditions(db, player_id, since)
    mts = _load_player_matches(db, player_id, since)
    series = correlation_series(conds, mts, x_key=x, y_key=y)
    if role == "player":
        # 選手向けは散布図も非公開。r と note のみ。弱点暗示を避けるため
        # 負相関は「伸びしろ」方向の肯定コメントに置き換える i18n キーを併記。
        r = series.get("pearson_r")
        growth_frame = None
        if r is not None:
            growth_frame = (
                "condition.insight.positive_relation"
                if r >= 0
                else "condition.insight.focus_growth_area"
            )
        return {
            "success": True,
            "data": {
                "x_key": x,
                "y_key": y,
                "n": series["n"],
                "confidence_note": series["confidence_note"],
                "growth_frame": growth_frame,
            },
        }
    return {"success": True, "data": series}


@router.get("/best_profile")
def get_best_profile(
    player_id: int = Query(...),
    since: Optional[_date] = Query(None),
    role: str = Depends(resolve_role),
    db: Session = Depends(get_db),
):
    if not db.get(Player, player_id):
        raise HTTPException(status_code=404, detail="選手が見つかりません")
    conds = _load_player_conditions(db, player_id, since)
    mts = _load_player_matches(db, player_id, since)
    profile = best_performance_profile(conds, mts)
    if role == "player":
        # 選手向けは key_factors のみ growth 文脈で、生値分布は非公開。
        return {
            "success": True,
            "data": {
                "key_factors": [
                    {"key": k["key"], "direction": k["direction"],
                     "i18n_frame": "condition.insight.best_profile_positive"}
                    for k in profile["key_factors"]
                ],
                "confidence": profile["confidence"],
                "note": profile["note"],
            },
        }
    return {"success": True, "data": profile}


@router.get("/discrepancy")
def get_discrepancy(
    player_id: int = Query(...),
    limit: int = Query(50, ge=1, le=500),
    role: str = Depends(resolve_role),
    db: Session = Depends(get_db),
):
    """InBody × メンタル 乖離フラグ一覧。coach / analyst のみ閲覧可。"""
    if role == "player":
        raise HTTPException(status_code=403, detail="選手ロールは閲覧できません")
    if not db.get(Player, player_id):
        raise HTTPException(status_code=404, detail="選手が見つかりません")
    rows = (
        db.query(Condition)
        .filter(Condition.player_id == player_id)
        .order_by(Condition.measured_at.asc(), Condition.id.asc())
        .all()
    )
    dicts = [_full_dict(c) for c in rows]
    results: List[dict] = []
    prev: Optional[dict] = None
    for c in dicts:
        flags = detect_discrepancy(c, prev_condition=prev)
        if flags:
            results.append({
                "condition_id": c["id"],
                "measured_at": c["measured_at"],
                "flags": flags,
            })
        prev = c
    results = results[-limit:]
    return {"success": True, "data": {"items": results, "n": len(results)}}


@router.get("/insights")
def get_insights(
    player_id: int = Query(...),
    since: Optional[_date] = Query(None),
    role: str = Depends(resolve_role),
    db: Session = Depends(get_db),
):
    """選手ロール: growth_cards + 個人 CCS トレンドのみ。
    coach/analyst: 上記 + raw factor trends + validity 要約。
    """
    if not db.get(Player, player_id):
        raise HTTPException(status_code=404, detail="選手が見つかりません")
    conds = _load_player_conditions(db, player_id, since)
    mts = _load_player_matches(db, player_id, since)
    insights = player_growth_insights(conds, mts)

    ccs_trend = [
        {"measured_at": c["measured_at"], "ccs_score": c.get("ccs_score")}
        for c in conds if c.get("ccs_score") is not None
    ]

    if role == "player":
        return {
            "success": True,
            "data": {
                "growth_cards": insights["growth_cards"],
                "personal_trend": {"ccs": ccs_trend},
                "confidence_note": insights["confidence_note"],
            },
        }

    # coach / analyst: raw factor trends + validity summary
    factor_trends = {
        k: [
            {"measured_at": c["measured_at"], "value": c.get(k)}
            for c in conds if c.get(k) is not None
        ]
        for k in ("f1_physical", "f2_stress", "f3_mood", "f4_motivation", "f5_sleep_life")
    }
    validity_counts: Dict[str, int] = {"ok": 0, "caution": 0, "unreliable": 0}
    for c in conds:
        vf = c.get("validity_flag")
        if vf in validity_counts:
            validity_counts[vf] += 1
    return {
        "success": True,
        "data": {
            "growth_cards": insights["growth_cards"],
            "personal_trend": {"ccs": ccs_trend},
            "raw_factor_trends": factor_trends,
            "validity_summary": {
                "counts": validity_counts,
                "n": len([c for c in conds if c.get("validity_flag")]),
            },
            "confidence_note": insights["confidence_note"],
        },
    }


def _require_condition_access(request: Request, cond: Condition) -> None:
    """BOLA/IDOR 対策:
    - player は自 player_id の condition のみ参照/編集可能
    - analyst/coach は自チーム選手の condition のみ参照/編集可能 (cross-team 漏洩防止)
    - admin は全件
    - 未認証 (role=None) は 401
    """
    from backend.utils.auth import get_auth
    ctx = get_auth(request)
    if ctx.role is None:
        from backend.utils.control_plane import allow_legacy_header_auth
        if not allow_legacy_header_auth(request):
            raise HTTPException(status_code=401, detail="認証が必要です")
    if ctx.is_admin:
        return
    if ctx.is_player:
        if not ctx.player_id or cond.player_id != ctx.player_id:
            raise HTTPException(status_code=404, detail="コンディション記録が見つかりません")
        return
    if ctx.is_analyst or ctx.is_coach:
        team = (ctx.team_name or "").strip()
        if not team:
            from backend.utils.control_plane import allow_legacy_header_auth
            if not allow_legacy_header_auth(request):
                raise HTTPException(status_code=403, detail="team_name 未設定")
            return
        from backend.db.models import Player as _P
        from backend.db.database import SessionLocal
        with SessionLocal() as _db:
            p = _db.get(_P, cond.player_id)
            if not p or (p.team or "").strip() != team:
                raise HTTPException(status_code=404, detail="コンディション記録が見つかりません")
        return


@router.get("/{condition_id}")
def get_condition(
    condition_id: int,
    request: Request,
    role: str = Depends(resolve_role),
    db: Session = Depends(get_db),
):
    cond = db.get(Condition, condition_id)
    if not cond:
        raise HTTPException(status_code=404, detail="コンディション記録が見つかりません")
    _require_condition_access(request, cond)
    return {"success": True, "data": _serialize(cond, role)}


@router.delete("/{condition_id}")
def delete_condition(condition_id: int, request: Request, db: Session = Depends(get_db)):
    cond = db.get(Condition, condition_id)
    if not cond:
        raise HTTPException(status_code=404, detail="コンディション記録が見つかりません")
    _require_condition_access(request, cond)
    # audit log (forensic): 誰がどの player の condition を削除したか残す
    try:
        from backend.utils.auth import get_auth as _ga
        from backend.utils.access_log import log_access as _log
        _ctx = _ga(request)
        _log(db, "condition_deleted", user_id=_ctx.user_id,
             resource_type="condition", resource_id=condition_id,
             details={"actor_role": _ctx.role, "target_player_id": cond.player_id})
    except Exception:
        pass
    db.delete(cond)
    db.commit()
    return {"success": True, "data": {"id": condition_id}}
