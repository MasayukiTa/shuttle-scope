"""Training data provenance records (admin only).

LEARNING_DATA_PROVENANCE.md / TERMS_OF_SERVICE.md Section 17.2 /
PRIVACY.md Article V-bis Section 5b.5 に基づく学習データ provenance
の入力 / 監査 endpoint。raw URL は受け取らず source_url_hash (SHA256) で
参照する設計 (PII 縮減)。
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, date
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import TrainingDatasetRecord
from backend.utils.auth import get_auth, require_admin

logger = logging.getLogger(__name__)
router = APIRouter()


# ─── allowed enum values ─────────────────────────────────────────────
_VALID_LICENSE_TYPES = {
    "granted",
    "public_domain",
    "appi_47_4",       # 著作権法第30条の4 / 47条の4 (情報解析利用)
    "appi_47_5",       # 著作権法第47条の5 (情報処理に伴う付随的利用)
    "beta_legacy_assumed_legal",
    "other",
}


class TrainingRecordCreate(BaseModel):
    """新規 provenance 記録の入力スキーマ。"""
    model_config = {"extra": "forbid"}

    dataset_id: str = Field(min_length=1, max_length=100)
    # raw URL を受け取り内部で hash 化する (URL 自体を保存しない)
    source_url: Optional[str] = Field(default=None, max_length=2000)
    acquisition_date: date
    license_type: str = Field(max_length=50)
    licensor_id: Optional[str] = Field(default=None, max_length=100)
    licensor_contact: Optional[str] = Field(default=None, max_length=255)
    scope_description: str = Field(min_length=1, max_length=500)
    verification_artefacts: Optional[str] = Field(default=None, max_length=500)
    beta_legacy_flag: bool = False
    notes: Optional[str] = Field(default=None, max_length=5000)


def _hash_source_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    return hashlib.sha256(url.encode("utf-8", errors="replace")).hexdigest()


@router.post("/admin/training_data/records", status_code=201)
def create_training_record(
    body: TrainingRecordCreate, request: Request, db: Session = Depends(get_db)
):
    """学習データ provenance 記録を作成する。admin 限定。

    LEARNING_DATA_PROVENANCE.md Section 4 (Recording Discipline) に従い、
    データを学習・fine-tuning・評価パイプラインに投入する **前または同時** に
    本 endpoint で記録する運用とする。
    """
    require_admin(request)
    ctx = get_auth(request)

    if body.license_type not in _VALID_LICENSE_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"invalid license_type: {body.license_type!r}",
        )

    rec = TrainingDatasetRecord(
        dataset_id=body.dataset_id.strip(),
        source_url_hash=_hash_source_url(body.source_url),
        acquisition_date=body.acquisition_date,
        license_type=body.license_type,
        licensor_id=(body.licensor_id or "").strip() or None,
        licensor_contact=(body.licensor_contact or "").strip() or None,
        scope_description=body.scope_description.strip(),
        verification_artefacts=(body.verification_artefacts or "").strip() or None,
        beta_legacy_flag=bool(body.beta_legacy_flag),
        recorded_by_user_id=ctx.user_id or 0,
        notes=(body.notes or "").strip() or None,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    try:
        from backend.utils.access_log import log_access
        log_access(
            db, "training_data_record_created",
            user_id=ctx.user_id,
            resource_type="training_dataset_record",
            resource_id=rec.id,
            details={
                "dataset_id": rec.dataset_id,
                "license_type": rec.license_type,
                "beta_legacy_flag": rec.beta_legacy_flag,
            },
        )
    except Exception:
        pass

    return {"success": True, "data": {"id": rec.id, "dataset_id": rec.dataset_id}}


@router.get("/admin/training_data/records")
def list_training_records(
    request: Request,
    db: Session = Depends(get_db),
    license_type: Optional[str] = Query(default=None),
    beta_legacy_flag: Optional[bool] = Query(default=None),
    dataset_id: Optional[str] = Query(default=None, max_length=100),
    limit: int = Query(default=100, ge=1, le=1000),
):
    """provenance 記録の一覧を返す。admin 限定。"""
    require_admin(request)
    q = db.query(TrainingDatasetRecord)
    if license_type is not None:
        if license_type not in _VALID_LICENSE_TYPES:
            raise HTTPException(
                status_code=422,
                detail=f"invalid license_type: {license_type!r}",
            )
        q = q.filter(TrainingDatasetRecord.license_type == license_type)
    if beta_legacy_flag is not None:
        q = q.filter(TrainingDatasetRecord.beta_legacy_flag == beta_legacy_flag)
    if dataset_id:
        q = q.filter(TrainingDatasetRecord.dataset_id == dataset_id)
    rows: List[TrainingDatasetRecord] = (
        q.order_by(TrainingDatasetRecord.recorded_at.desc()).limit(limit).all()
    )
    return {
        "success": True,
        "data": [
            {
                "id": r.id,
                "dataset_id": r.dataset_id,
                "source_url_hash": r.source_url_hash,
                "acquisition_date": (
                    r.acquisition_date.isoformat() if r.acquisition_date else None
                ),
                "license_type": r.license_type,
                "licensor_id": r.licensor_id,
                "licensor_contact": r.licensor_contact,
                "scope_description": r.scope_description,
                "verification_artefacts": r.verification_artefacts,
                "beta_legacy_flag": bool(r.beta_legacy_flag),
                "recorded_by_user_id": r.recorded_by_user_id,
                "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
                "notes": r.notes,
            }
            for r in rows
        ],
    }


@router.get("/admin/training_data/records/{record_id}")
def get_training_record(
    record_id: int, request: Request, db: Session = Depends(get_db)
):
    require_admin(request)
    r = db.get(TrainingDatasetRecord, record_id)
    if not r:
        raise HTTPException(status_code=404, detail="training_dataset_record not found")
    return {
        "success": True,
        "data": {
            "id": r.id,
            "dataset_id": r.dataset_id,
            "source_url_hash": r.source_url_hash,
            "acquisition_date": (
                r.acquisition_date.isoformat() if r.acquisition_date else None
            ),
            "license_type": r.license_type,
            "licensor_id": r.licensor_id,
            "licensor_contact": r.licensor_contact,
            "scope_description": r.scope_description,
            "verification_artefacts": r.verification_artefacts,
            "beta_legacy_flag": bool(r.beta_legacy_flag),
            "recorded_by_user_id": r.recorded_by_user_id,
            "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
            "notes": r.notes,
        },
    }
