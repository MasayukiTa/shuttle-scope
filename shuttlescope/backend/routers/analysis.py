"""解析API（/api/analysis）— router 登録シェル

実装は各 sub-router ファイルに分割:
  analysis_stable.py   — stable tier（基礎統計）
  analysis_advanced.py — advanced tier（詳細解析）
  analysis_research.py — research tier（研究・実験）
  analysis_spine.py    — research spine（RS-1〜RS-5）
"""
from fastapi import APIRouter

from backend.analysis.router_helpers import (
    SHOT_TYPE_JA, SHOT_KEYS, SHOT_LABELS_JA,
    _player_role_in_match, _get_player_matches, _fetch_matches_sets_rallies,
)
from backend.routers.analysis_stable import router as stable_router
from backend.routers.analysis_advanced import router as advanced_router
from backend.routers.analysis_research import router as research_router
from backend.routers.analysis_spine import router as spine_router
from backend.routers.analysis_bundle import router as bundle_router

router = APIRouter()
router.include_router(stable_router)
router.include_router(advanced_router)
router.include_router(research_router)
router.include_router(spine_router)
router.include_router(bundle_router)
