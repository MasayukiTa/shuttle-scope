"""analysis_bundle.py — 振り返りタブ向け bundle エンドポイント

ShuttleScope の振り返りタブ（DashboardReviewPage）で使う 6 つの解析エンドポイントを
1 リクエスト・1 DB セッション・1 回のデータロードに集約する。

目的:
- 初回ロードで 15 並列リクエスト → SQLite 競合を避ける
- Match/Set/Rally/Stroke を 1 回だけロードして 6 カード関数で共有
- フロントエンドの往復回数を 7+ → 1 に削減
- レスポンスキャッシュは `/api/analysis/*` 全体に適用されるため bundle も自動キャッシュされる

方針:
- `load_context()` で Match/Set/Rally/Stroke を 1 回だけロードし、各 `_xxx_impl()` に渡す
- 個別エンドポイントの計算ロジックは一切触らず、データロード部分のみ差し替え
- 各カードは独立した try/except で囲み、1 つの計算失敗が全体を潰さないようにする
"""
import logging
from datetime import date as DateType
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.analysis.bundle_context import load_context
from backend.analysis.research_bundle_context import load_research_context
from backend.routers.analysis_stable import (
    _pre_loss_patterns_impl,
    _pre_win_patterns_impl,
    _effective_distribution_map_impl,
    _received_vulnerability_impl,
    _set_comparison_impl,
)
from backend.routers.analysis_research import (
    _rally_sequence_patterns_impl,
    _epv_impl,
    _counterfactual_shots_impl,
)
from backend.routers.analysis_spine import (
    _epv_state_table_impl,
    _state_action_values_impl,
    _counterfactual_v2_impl,
    _bayes_matchup_impl,
    _opponent_policy_impl,
    _doubles_role_impl,
    _shot_influence_v2_impl,
    _hazard_fatigue_impl,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/analysis/bundle/review")
def get_review_bundle(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """振り返りタブ一括取得エンドポイント

    1 回だけ Match/Set/Rally/Stroke をロードして 6 個のカード用データを計算する。
    個別エンドポイントと同一のレスポンス形状を各キーの値として保持する。
    ScoreProgression は match_id が必要なので bundle には含めない。
    """
    filters = {
        "result": result,
        "tournament_level": tournament_level,
        "date_from": date_from,
        "date_to": date_to,
    }

    ctx = load_context(db, player_id, filters)

    bundle: dict[str, object] = {}
    errors: dict[str, str] = {}

    jobs = [
        ("pre_loss_patterns", lambda: _pre_loss_patterns_impl(db, player_id, ctx=ctx)),
        ("pre_win_patterns", lambda: _pre_win_patterns_impl(db, player_id, ctx=ctx)),
        ("effective_distribution_map", lambda: _effective_distribution_map_impl(db, player_id, ctx=ctx)),
        ("received_vulnerability", lambda: _received_vulnerability_impl(db, player_id, ctx=ctx)),
        ("set_comparison", lambda: _set_comparison_impl(db, player_id, ctx=ctx)),
        ("rally_sequence_patterns", lambda: _rally_sequence_patterns_impl(db, player_id, ctx=ctx)),
    ]

    sample_size = 0
    for key, fn in jobs:
        try:
            value = fn()
            bundle[key] = value
            if isinstance(value, dict):
                meta = value.get("meta") or {}
                ss = meta.get("sample_size")
                if isinstance(ss, int) and ss > sample_size:
                    sample_size = ss
        except Exception as exc:
            logger.exception("bundle card failed: %s", key)
            bundle[key] = None
            errors[key] = str(exc)[:200]

    return {
        "success": True,
        "data": bundle,
        "meta": {
            "player_id": player_id,
            "sample_size": sample_size,
            "errors": errors if errors else None,
        },
    }


@router.get("/analysis/bundle/research")
def get_research_bundle(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """研究タブ一括取得エンドポイント

    1 回だけ Match/Set/Rally/Stroke をロードして 10 個のカード用データを計算する。
    各キーの値は個別エンドポイントと同一形状。
    bayes_matchup は format 別呼び出しがフロントに必要だが、bundle では
    format=None (全試合) のデフォルト挙動のみを返す。
    """
    filters = {
        "result": result,
        "tournament_level": tournament_level,
        "date_from": date_from,
        "date_to": date_to,
    }

    ctx = load_research_context(db, player_id, filters)

    bundle: dict[str, object] = {}
    errors: dict[str, str] = {}

    jobs = [
        ("epv", lambda: _epv_impl(db, player_id, ctx=ctx)),
        ("epv_state_table", lambda: _epv_state_table_impl(db, player_id, ctx=ctx)),
        ("state_action_values", lambda: _state_action_values_impl(db, player_id, ctx=ctx)),
        ("counterfactual_shots", lambda: _counterfactual_shots_impl(db, player_id, ctx=ctx)),
        ("counterfactual_v2", lambda: _counterfactual_v2_impl(db, player_id, ctx=ctx)),
        ("bayes_matchup", lambda: _bayes_matchup_impl(db, player_id, ctx=ctx)),
        ("opponent_policy", lambda: _opponent_policy_impl(db, player_id, ctx=ctx)),
        ("doubles_role", lambda: _doubles_role_impl(db, player_id, ctx=ctx)),
        ("shot_influence_v2", lambda: _shot_influence_v2_impl(db, player_id, ctx=ctx)),
        ("hazard_fatigue", lambda: _hazard_fatigue_impl(db, player_id, ctx=ctx)),
    ]

    sample_size = 0
    for key, fn in jobs:
        try:
            value = fn()
            bundle[key] = value
            if isinstance(value, dict):
                meta = value.get("meta") or {}
                ss = meta.get("sample_size")
                if isinstance(ss, int) and ss > sample_size:
                    sample_size = ss
        except Exception as exc:
            logger.exception("research bundle card failed: %s", key)
            bundle[key] = None
            errors[key] = f"{type(exc).__name__}: {str(exc)[:200]}"

    return {
        "success": True,
        "data": bundle,
        "meta": {
            "player_id": player_id,
            "sample_size": sample_size,
            "errors": errors if errors else None,
        },
    }
