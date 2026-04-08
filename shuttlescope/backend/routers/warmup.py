"""G3: 試合前ウォームアップ観察 API（/api/warmup）"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import PreMatchObservation, Match, Player
from backend.utils.sync_meta import touch_sync_metadata, get_device_id

router = APIRouter()

# G3 許可観察タイプ（ライブ操作で現実的に収集可能な第1波 + 自コンディション）
ALLOWED_TYPES = frozenset([
    # 相手観察
    "handedness",          # 利き手
    "physical_caution",    # テーピング・サポーター等の身体的注意
    "tactical_style",      # 戦術スタイル大まかな印象
    "court_preference",    # コート位置の好み（前衛/後衛傾向）
    # 自コンディション（player_a 自己申告）
    "self_condition",      # 身体的コンディション全般（great/normal/heavy/poor）
    "self_timing",         # ショットタイミング感覚（sharp/normal/off）
])

# 自コンディション専用タイプ（分析時に分離する）
SELF_CONDITION_TYPES = frozenset(["self_condition", "self_timing"])

ALLOWED_CONFIDENCE = frozenset(["unknown", "tentative", "likely", "confirmed"])


class ObservationIn(BaseModel):
    player_id: int
    observation_type: str
    observation_value: str
    confidence_level: str = "tentative"
    note: Optional[str] = None
    created_by: Optional[str] = None


class BatchObservationsIn(BaseModel):
    observations: list[ObservationIn]


def obs_to_dict(o: PreMatchObservation) -> dict:
    return {
        "id": o.id,
        "match_id": o.match_id,
        "player_id": o.player_id,
        "observation_type": o.observation_type,
        "observation_value": o.observation_value,
        "confidence_level": o.confidence_level,
        "source": o.source,
        "note": o.note,
        "created_at": o.created_at.isoformat(),
        "created_by": o.created_by,
    }


@router.get("/warmup/observations/{match_id}")
def get_warmup_observations(match_id: int, db: Session = Depends(get_db)):
    """試合の全ウォームアップ観察を取得"""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")
    obs = (
        db.query(PreMatchObservation)
        .filter(PreMatchObservation.match_id == match_id)
        .order_by(PreMatchObservation.created_at)
        .all()
    )
    return {"success": True, "data": [obs_to_dict(o) for o in obs]}


@router.post("/warmup/observations/{match_id}", status_code=201)
def save_warmup_observations(
    match_id: int,
    body: BatchObservationsIn,
    db: Session = Depends(get_db),
):
    """ウォームアップ観察を一括保存（既存データは observation_type + player_id 単位で上書き）"""
    match = db.get(Match, match_id)
    if not match:
        raise HTTPException(status_code=404, detail="試合が見つかりません")

    saved = []
    for item in body.observations:
        # 観察タイプと信頼度の値チェック
        if item.observation_type not in ALLOWED_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"無効な観察タイプ: {item.observation_type}",
            )
        if item.confidence_level not in ALLOWED_CONFIDENCE:
            raise HTTPException(
                status_code=422,
                detail=f"無効な信頼度: {item.confidence_level}",
            )

        device_id = get_device_id(db)
        # 既存エントリを上書き
        existing = (
            db.query(PreMatchObservation)
            .filter(
                PreMatchObservation.match_id == match_id,
                PreMatchObservation.player_id == item.player_id,
                PreMatchObservation.observation_type == item.observation_type,
            )
            .first()
        )
        payload = {
            "match_id": match_id,
            "player_id": item.player_id,
            "observation_type": item.observation_type,
            "observation_value": item.observation_value,
            "confidence_level": item.confidence_level,
        }
        if existing:
            existing.observation_value = item.observation_value
            existing.confidence_level = item.confidence_level
            existing.note = item.note
            existing.created_by = item.created_by
            touch_sync_metadata(existing, payload_like=payload, device_id=device_id)
            saved.append(existing)
        else:
            obs = PreMatchObservation(
                match_id=match_id,
                player_id=item.player_id,
                observation_type=item.observation_type,
                observation_value=item.observation_value,
                confidence_level=item.confidence_level,
                source="warmup",
                note=item.note,
                created_by=item.created_by,
            )
            db.add(obs)
            touch_sync_metadata(obs, payload_like=payload, device_id=device_id)
            saved.append(obs)

    db.commit()
    return {"success": True, "data": {"saved_count": len(saved)}}
