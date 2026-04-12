"""analysis_spine.py — Research Spine エンドポイント

Research Spine RS-1〜RS-5 の新規 API を提供する:
  - /analysis/epv_state_table   (RS-1: 状態ベースEPVテーブル)
  - /analysis/epv_state_map     (RS-1: 状態マップ)
  - /analysis/state_action_values (RS-2: 状態-行動価値テーブル)
  - /analysis/state_best_actions  (RS-2: 状態ごとの最善手)
  - /analysis/counterfactual_v2   (RS-3: 反事実v2 + BootstrapCI)
  - /analysis/hazard_fatigue      (RS-3: ハザード・疲労モデル)
  - /analysis/bayes_matchup       (RS-4: ベイズ対戦予測)
  - /analysis/opponent_policy     (RS-4: 対戦相手ポリシー)
  - /analysis/doubles_role        (RS-5: ダブルスロール推定)
  - /analysis/meta/evidence       (メタ: evidence メタデータ一覧)
  - /analysis/meta/promotion_rules (メタ: 昇格基準一覧)
"""
from datetime import date as DateType
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, GameSet, Rally, Stroke
from backend.analysis.router_helpers import (
    _player_role_in_match, _get_player_matches, _fetch_matches_sets_rallies,
)
from backend.analysis.response_meta import build_response_meta
from backend.analysis.analysis_registry import list_registry_entries, get_tier as _registry_get_tier
from backend.analysis.analysis_meta import EVIDENCE_META
from backend.analysis.promotion_rules import all_criteria_as_dict, DEMOTION_CONDITIONS
from backend.analysis.epv_state_model import compute_rally_state_epv, compute_epv_state_map
from backend.analysis.q_value_model import compute_q_values, summarize_best_actions
from backend.analysis.counterfactual_v2 import compute_counterfactual_v2, compute_counterfactual_cf2, compute_counterfactual_cf3
from backend.analysis.hazard_fatigue import compute_hazard_model
from backend.analysis.bayes_matchup import compute_bayes_matchup
from backend.analysis.opponent_policy_engine import compute_opponent_policy
from backend.analysis.doubles_role_inference import (
    compute_doubles_role_inference,
    compute_doubles_role_db2,
    compute_doubles_role_stability,
)
from backend.analysis.shot_influence_v2 import compute_shot_influence_v2

router = APIRouter()


def _build_aux_maps(db: Session, matches: list, set_ids: list, rally_ids: list) -> tuple:
    """セット番号マップ・ストロークマップを構築するヘルパー。"""
    sets = db.query(GameSet).filter(GameSet.id.in_(set_ids)).all() if set_ids else []
    set_num_map = {s.id: s.set_num for s in sets}
    strokes_by_rally: dict[int, list] = {}
    if rally_ids:
        stks = db.query(Stroke).filter(Stroke.rally_id.in_(rally_ids)).all()
        for s in stks:
            strokes_by_rally.setdefault(s.rally_id, []).append(s)
    return set_num_map, strokes_by_rally


# ---------------------------------------------------------------------------
# RS-1: 状態ベース EPV テーブル
# ---------------------------------------------------------------------------

@router.get("/analysis/epv_state_table")
def get_epv_state_table(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)
    if not matches:
        meta = build_response_meta("epv_state", 0)
        return {"success": True, "data": {"state_table": [], "global_win_rate": 0.5, "total_rallies": 0}, "meta": meta}

    match_ids = [m.id for m in matches]
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in matches}

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_ids = [s.id for s in sets]
    set_to_match = {s.id: s.match_id for s in sets}
    set_num_map = {s.id: s.set_num for s in sets}

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    rally_ids = [r.id for r in rallies]

    _, strokes_by_rally = _build_aux_maps(db, matches, [], rally_ids)

    result_data = compute_rally_state_epv(
        rallies=rallies,
        strokes_by_rally=strokes_by_rally,
        role_by_match=role_by_match,
        set_to_match=set_to_match,
        set_num_by_set=set_num_map,
    )

    meta = build_response_meta("epv_state", len(rallies))
    return {"success": True, "data": result_data, "meta": meta}


# ---------------------------------------------------------------------------
# RS-1: 状態マップ
# ---------------------------------------------------------------------------

@router.get("/analysis/epv_state_map")
def get_epv_state_map(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)
    if not matches:
        return {"success": True, "data": [], "meta": build_response_meta("epv_state", 0)}

    match_ids = [m.id for m in matches]
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in matches}

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_ids = [s.id for s in sets]
    set_to_match = {s.id: s.match_id for s in sets}
    set_num_map = {s.id: s.set_num for s in sets}

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    rally_ids = [r.id for r in rallies]
    _, strokes_by_rally = _build_aux_maps(db, matches, [], rally_ids)

    state_result = compute_rally_state_epv(
        rallies=rallies,
        strokes_by_rally=strokes_by_rally,
        role_by_match=role_by_match,
        set_to_match=set_to_match,
        set_num_by_set=set_num_map,
    )
    state_map = compute_epv_state_map(state_result["state_table"])
    meta = build_response_meta("epv_state", len(rallies))
    return {"success": True, "data": state_map, "meta": meta}


# ---------------------------------------------------------------------------
# RS-2: 状態-行動価値テーブル
# ---------------------------------------------------------------------------

@router.get("/analysis/state_action_values")
def get_state_action_values(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)
    if not matches:
        return {"success": True, "data": {"q_table": [], "best_actions": {}, "total_states": 0, "total_reliable_cells": 0}, "meta": build_response_meta("state_action", 0)}

    match_ids = [m.id for m in matches]
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in matches}

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match = {s.id: s.match_id for s in sets}
    set_num_map = {s.id: s.set_num for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    rally_ids = [r.id for r in rallies]
    _, strokes_by_rally = _build_aux_maps(db, matches, [], rally_ids)

    result_data = compute_q_values(
        rallies=rallies,
        strokes_by_rally=strokes_by_rally,
        role_by_match=role_by_match,
        set_to_match=set_to_match,
        set_num_by_set=set_num_map,
    )
    meta = build_response_meta("state_action", len(rallies))
    return {"success": True, "data": result_data, "meta": meta}


# ---------------------------------------------------------------------------
# RS-2: 状態ごとの最善手
# ---------------------------------------------------------------------------

@router.get("/analysis/state_best_actions")
def get_state_best_actions(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)
    if not matches:
        return {"success": True, "data": [], "meta": build_response_meta("state_action", 0)}

    match_ids = [m.id for m in matches]
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in matches}

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match = {s.id: s.match_id for s in sets}
    set_num_map = {s.id: s.set_num for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    rally_ids = [r.id for r in rallies]
    _, strokes_by_rally = _build_aux_maps(db, matches, [], rally_ids)

    result_data = compute_q_values(
        rallies=rallies,
        strokes_by_rally=strokes_by_rally,
        role_by_match=role_by_match,
        set_to_match=set_to_match,
        set_num_by_set=set_num_map,
    )
    best_list = summarize_best_actions(result_data["best_actions"])
    meta = build_response_meta("state_action", len(rallies))
    return {"success": True, "data": best_list, "meta": meta}


# ---------------------------------------------------------------------------
# RS-3: 反事実的ショット v2 (Bootstrap CI)
# ---------------------------------------------------------------------------

@router.get("/analysis/counterfactual_v2")
def get_counterfactual_v2(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)
    if not matches:
        return {"success": True, "data": {"comparisons": [], "total_contexts": 0, "usable_contexts": 0}, "meta": build_response_meta("counterfactual_v2", 0)}

    match_ids = [m.id for m in matches]
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in matches}

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match = {s.id: s.match_id for s in sets}
    set_num_map = {s.id: s.set_num for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    rally_ids = [r.id for r in rallies]
    _, strokes_by_rally = _build_aux_maps(db, matches, [], rally_ids)

    result_data = compute_counterfactual_v2(
        rallies=rallies,
        strokes_by_rally=strokes_by_rally,
        role_by_match=role_by_match,
        set_to_match=set_to_match,
        set_num_by_set=set_num_map,
    )
    meta = build_response_meta("counterfactual_v2", len(rallies))
    return {"success": True, "data": result_data, "meta": meta}


# ---------------------------------------------------------------------------
# RS-3: ハザード・疲労モデル
# ---------------------------------------------------------------------------

@router.get("/analysis/hazard_fatigue")
def get_hazard_fatigue(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)
    if not matches:
        return {"success": True, "data": {}, "meta": build_response_meta("hazard_fatigue", 0)}

    match_ids = [m.id for m in matches]
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in matches}

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match = {s.id: s.match_id for s in sets}
    set_num_map = {s.id: s.set_num for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []

    result_data = compute_hazard_model(
        rallies=rallies,
        role_by_match=role_by_match,
        set_to_match=set_to_match,
        set_num_by_set=set_num_map,
    )
    meta = build_response_meta("hazard_fatigue", len(rallies))
    return {"success": True, "data": result_data, "meta": meta}


# ---------------------------------------------------------------------------
# RS-4: ベイズ対戦予測
# ---------------------------------------------------------------------------

@router.get("/analysis/bayes_matchup")
def get_bayes_matchup(
    player_id: int,
    format: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    matches = _get_player_matches(db, player_id)
    if not matches:
        return {"success": True, "data": {}, "meta": build_response_meta("bayes_matchup", 0)}

    result_data = compute_bayes_matchup(
        matches=matches,
        player_id=player_id,
        format_filter=format,
    )
    meta = build_response_meta("bayes_matchup", result_data.get("total_matches", 0))
    return {"success": True, "data": result_data, "meta": meta}


# ---------------------------------------------------------------------------
# RS-4: 対戦相手ポリシー
# ---------------------------------------------------------------------------

@router.get("/analysis/opponent_policy")
def get_opponent_policy(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)
    if not matches:
        return {"success": True, "data": {"global_policy": {}, "context_policies": [], "total_opponent_shots": 0, "usable_contexts": 0}, "meta": build_response_meta("opponent_policy", 0)}

    match_ids = [m.id for m in matches]
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in matches}

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match = {s.id: s.match_id for s in sets}
    set_num_map = {s.id: s.set_num for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    rally_ids = [r.id for r in rallies]
    _, strokes_by_rally = _build_aux_maps(db, matches, [], rally_ids)

    result_data = compute_opponent_policy(
        rallies=rallies,
        strokes_by_rally=strokes_by_rally,
        role_by_match=role_by_match,
        set_to_match=set_to_match,
        set_num_by_set=set_num_map,
    )
    meta = build_response_meta("opponent_policy", result_data.get("total_opponent_shots", 0))
    return {"success": True, "data": result_data, "meta": meta}


# ---------------------------------------------------------------------------
# RS-5: ダブルスロール推定
# ---------------------------------------------------------------------------

@router.get("/analysis/doubles_role")
def get_doubles_role(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    # ダブルス試合のみに絞る
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)
    doubles_matches = [m for m in matches if getattr(m, 'format', None) in ('womens_doubles', 'mixed_doubles')]
    if not doubles_matches:
        return {"success": True, "data": {"inferred_role": "unknown", "confidence_score": 0.0, "total_shots": 0}, "meta": build_response_meta("doubles_role", 0)}

    match_ids = [m.id for m in doubles_matches]
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in doubles_matches}

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    rally_ids = [r.id for r in rallies]
    _, strokes_by_rally = _build_aux_maps(db, doubles_matches, [], rally_ids)

    result_data = compute_doubles_role_inference(
        rallies=rallies,
        strokes_by_rally=strokes_by_rally,
        role_by_match=role_by_match,
        set_to_match=set_to_match,
    )
    meta = build_response_meta("doubles_role", result_data.get("total_shots", 0))
    return {"success": True, "data": result_data, "meta": meta}


# ---------------------------------------------------------------------------
# RS-5 DB-2: HMM ロール推定
# ---------------------------------------------------------------------------

@router.get("/analysis/doubles_role_db2")
def get_doubles_role_db2(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    from backend.db.models import Player
    player = db.query(Player).filter(Player.id == player_id).first()
    if not player:
        return {"success": True, "data": {}, "meta": build_response_meta("doubles_role", 0)}

    all_matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)
    doubles_matches = [m for m in all_matches if getattr(m, 'format', None) in ('womens_doubles', 'mixed_doubles')]

    if not doubles_matches:
        meta = build_response_meta("doubles_role", 0)
        return {"success": True, "data": {"inferred_role": "unknown", "confidence_score": 0.0, "total_shots": 0, "db_phase": "db2"}, "meta": meta}

    match_ids = [m.id for m in doubles_matches]
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in doubles_matches}

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    rally_ids = [r.id for r in rallies]
    _, strokes_by_rally = _build_aux_maps(db, doubles_matches, [], rally_ids)

    result_data = compute_doubles_role_db2(
        rallies=rallies,
        strokes_by_rally=strokes_by_rally,
        role_by_match=role_by_match,
        set_to_match=set_to_match,
    )
    meta = build_response_meta("doubles_role", result_data.get("total_shots", 0))
    return {"success": True, "data": result_data, "meta": meta}


# ---------------------------------------------------------------------------
# CF-2: 傾向スコア重み付き反事実推定
# ---------------------------------------------------------------------------

@router.get("/analysis/counterfactual_cf2")
def get_counterfactual_cf2(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)
    if not matches:
        return {"success": True, "data": {"comparisons": [], "total_contexts": 0, "usable_contexts": 0, "cf_phase": "cf2"}, "meta": build_response_meta("counterfactual_v2", 0)}

    match_ids = [m.id for m in matches]
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in matches}

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match = {s.id: s.match_id for s in sets}
    set_num_map = {s.id: s.set_num for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    rally_ids = [r.id for r in rallies]
    _, strokes_by_rally = _build_aux_maps(db, matches, [], rally_ids)

    result_data = compute_counterfactual_cf2(
        rallies=rallies,
        strokes_by_rally=strokes_by_rally,
        role_by_match=role_by_match,
        set_to_match=set_to_match,
        set_num_by_set=set_num_map,
    )
    meta = build_response_meta("counterfactual_v2", len(rallies))
    return {"success": True, "data": result_data, "meta": meta}


# ---------------------------------------------------------------------------
# CF-3: 対戦相手タイプ条件付き反事実推定
# ---------------------------------------------------------------------------

@router.get("/analysis/counterfactual_cf3")
def get_counterfactual_cf3(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    from backend.analysis.bayes_matchup import compute_bayes_matchup

    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)
    if not matches:
        return {"success": True, "data": {"comparisons": [], "total_contexts": 0, "usable_contexts": 0, "cf_phase": "cf3"}, "meta": build_response_meta("counterfactual_v2", 0)}

    match_ids = [m.id for m in matches]
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in matches}

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match = {s.id: s.match_id for s in sets}
    set_num_map = {s.id: s.set_num for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    rally_ids = [r.id for r in rallies]
    _, strokes_by_rally = _build_aux_maps(db, matches, [], rally_ids)

    # 対戦相手タイプをベイズ推定から取得
    bayes_result = compute_bayes_matchup(matches, player_id)
    opponent_type_by_opponent: dict = {
        est["opponent_id"]: est["opponent_type"]
        for est in bayes_result.get("opponent_estimates", [])
        if "opponent_id" in est
    }
    # match_id → opponent_type マッピング
    opponent_type_by_match: dict[int, str] = {}
    for m in matches:
        opp_id = None
        if hasattr(m, 'player_a_id') and m.player_a_id == player_id:
            opp_id = getattr(m, 'player_b_id', None)
        elif hasattr(m, 'player_b_id') and m.player_b_id == player_id:
            opp_id = getattr(m, 'player_a_id', None)
        if opp_id is not None:
            opponent_type_by_match[m.id] = opponent_type_by_opponent.get(opp_id, "all")

    result_data = compute_counterfactual_cf3(
        rallies=rallies,
        strokes_by_rally=strokes_by_rally,
        role_by_match=role_by_match,
        set_to_match=set_to_match,
        set_num_by_set=set_num_map,
        opponent_type_by_match=opponent_type_by_match,
    )
    meta = build_response_meta("counterfactual_v2", len(rallies))
    return {"success": True, "data": result_data, "meta": meta}


# ---------------------------------------------------------------------------
# Spine 4: ショット影響度 v2（状態条件付き）
# ---------------------------------------------------------------------------

@router.get("/analysis/shot_influence_v2")
def get_shot_influence_v2(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)
    if not matches:
        meta = build_response_meta("shot_influence", 0)
        return {"success": True, "data": {"per_shot_type": {}, "state_breakdown": [], "total_rallies": 0, "usable_rallies": 0}, "meta": meta}

    match_ids = [m.id for m in matches]
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in matches}

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match = {s.id: s.match_id for s in sets}
    set_num_map = {s.id: s.set_num for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    rally_ids = [r.id for r in rallies]
    _, strokes_by_rally = _build_aux_maps(db, matches, [], rally_ids)

    result_data = compute_shot_influence_v2(
        rallies=rallies,
        strokes_by_rally=strokes_by_rally,
        role_by_match=role_by_match,
        set_to_match=set_to_match,
        set_num_by_set=set_num_map,
    )
    # rally_details は dataclass のリストなので dict 変換
    result_data["rally_details"] = [
        {
            "rally_id": rv.rally_id,
            "state_key": rv.state_key,
            "state_epv": rv.state_epv,
            "outcome": rv.outcome,
        }
        for rv in result_data["rally_details"]
    ]
    meta = build_response_meta("shot_influence", len(rallies))
    return {"success": True, "data": result_data, "meta": meta}


# ---------------------------------------------------------------------------
# メタデータ: evidence 一覧
# ---------------------------------------------------------------------------

@router.get("/analysis/meta/evidence")
def get_evidence_meta():
    """各 analysis_type の evidence メタデータ一覧をリスト形式で返す。

    レジストリが全 analysis_type の正規ソースとなっているため、
    以前の EVIDENCE_META / _infer_tier() ベースの実装を置き換えた。
    """
    entries = [
        {
            "analysis_type": e["analysis_type"],
            "tier": e["tier"],
            "evidence_level": e["evidence_level"],
            "min_recommended_sample": e["min_recommended_sample"],
            "caution": e["caution"],
            "assumptions": e["assumptions"],
            "promotion_criteria": e["promotion_criteria"],
            "page": e["page"],
            "section": e["section"],
        }
        for e in list_registry_entries()
    ]
    return {
        "success": True,
        "data": entries,
    }


# ---------------------------------------------------------------------------
# メタデータ: 昇格基準
# ---------------------------------------------------------------------------

@router.get("/analysis/meta/promotion_rules")
def get_promotion_rules():
    """tier 昇格基準一覧と降格条件を返す。"""
    return {
        "success": True,
        "data": {
            "promotion_criteria": all_criteria_as_dict(),
            "demotion_conditions": DEMOTION_CONDITIONS,
        },
    }


# ---------------------------------------------------------------------------
# メタデータ: 昇格評価（player_id ごとの現在状況）
# ---------------------------------------------------------------------------

@router.get("/analysis/meta/promotion_evaluation")
def get_promotion_evaluation(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """
    各 analysis_type の現在の昇格評価を返す。
    実際のサンプルサイズ (rally/match 数) を基準値と比較し、
    各昇格チェックリスト項目の達成状況を概算で示す。
    """
    from backend.analysis.promotion_rules import PROMOTION_CRITERIA, DEMOTION_CONDITIONS, get_criteria_for
    from backend.analysis.analysis_tiers import get_tier

    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)
    match_ids = [m.id for m in matches]
    n_matches = len(matches)

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all() if match_ids else []
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    n_rallies = len(rallies)

    # ダブルス試合数
    doubles_matches = [m for m in matches if getattr(m, 'format', None) in ('womens_doubles', 'mixed_doubles')]
    n_doubles_matches = len(doubles_matches)

    # 対戦相手数
    opponents: set = set()
    for m in matches:
        if hasattr(m, 'player_a_id') and m.player_a_id != player_id:
            opponents.add(m.player_a_id)
        if hasattr(m, 'player_b_id') and m.player_b_id != player_id:
            opponents.add(m.player_b_id)
    n_opponents = len(opponents)

    def _get_sample_count(analysis_type: str) -> int:
        """analysis_type に適したサンプル数の代理値を返す。"""
        match_based = {"bayes_matchup", "opponent_policy", "doubles_role"}
        doubles_based = {"doubles_role"}
        if analysis_type in doubles_based:
            return n_doubles_matches
        if analysis_type in match_based:
            return n_matches
        return n_rallies

    evaluations = []
    for crit in PROMOTION_CRITERIA:
        sample_count = _get_sample_count(crit.analysis_type)
        sample_met = sample_count >= crit.min_sample_size

        # チェックリスト
        checklist = [
            {
                "item": f"サンプル数 ≥ {crit.min_sample_size}",
                "met": sample_met,
                "current": sample_count,
                "required": crit.min_sample_size,
            },
            {
                "item": f"安定性要件: {crit.required_stability}",
                "met": None,  # データなしでは判定不能
                "current": None,
                "required": crit.required_stability,
            },
        ]
        if crit.ci_width_threshold is not None:
            checklist.append({
                "item": f"CI 幅 ≤ {crit.ci_width_threshold}",
                "met": None,
                "current": None,
                "required": crit.ci_width_threshold,
            })
        if crit.calibration_required:
            checklist.append({
                "item": "校正品質確認済み",
                "met": None,
                "current": None,
                "required": "required",
            })
        if crit.coach_usefulness_test_required:
            checklist.append({
                "item": "コーチ有用性テスト実施済み",
                "met": None,
                "current": None,
                "required": "required",
            })

        met_count = sum(1 for c in checklist if c["met"] is True)
        total_count = len(checklist)

        # サンプル数が満たされていない場合は未準備
        # その他は "requires_review" (手動確認が必要)
        if not sample_met:
            status = "insufficient_data"
        elif met_count == total_count:
            status = "promotion_ready"
        else:
            status = "requires_review"

        evaluations.append({
            "analysis_type": crit.analysis_type,
            "from_tier": crit.from_tier,
            "to_tier": crit.to_tier,
            "current_tier": get_tier(crit.analysis_type),
            "sample_count": sample_count,
            "status": status,
            "checklist": checklist,
            "met_count": met_count,
            "total_count": total_count,
            "additional_notes": crit.additional_notes,
        })

    return {
        "success": True,
        "data": {
            "evaluations": evaluations,
            "summary": {
                "n_rallies": n_rallies,
                "n_matches": n_matches,
                "n_opponents": n_opponents,
                "n_doubles_matches": n_doubles_matches,
                "promotion_ready_count": sum(1 for e in evaluations if e["status"] == "promotion_ready"),
                "requires_review_count": sum(1 for e in evaluations if e["status"] == "requires_review"),
                "insufficient_data_count": sum(1 for e in evaluations if e["status"] == "insufficient_data"),
            },
            "demotion_conditions": DEMOTION_CONDITIONS,
        },
    }


# ---------------------------------------------------------------------------
# DB-3: ダブルスロール安定性（試合・シーズン単位）
# ---------------------------------------------------------------------------

@router.get("/analysis/doubles_role_stability")
def get_doubles_role_stability(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """DB-3: 試合ごとのロール推定から安定性スコアを計算する。"""
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)
    doubles_matches = [m for m in matches if getattr(m, "format", None) in ("womens_doubles", "mixed_doubles")]
    if not doubles_matches:
        meta = build_response_meta("doubles_role", 0)
        return {
            "success": True,
            "data": {
                "role_stability_score": 0.0,
                "dominant_role": "unknown",
                "n_matches_analyzed": 0,
                "per_match_roles": [],
                "season_variation": [],
                "consistency_label": "insufficient_data",
                "note": "ダブルスデータが不足しています。",
            },
            "meta": meta,
        }

    match_ids = [m.id for m in doubles_matches]
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in doubles_matches}

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    rally_ids = [r.id for r in rallies]
    _, strokes_by_rally = _build_aux_maps(db, doubles_matches, [], rally_ids)

    result_data = compute_doubles_role_stability(
        matches=doubles_matches,
        rallies=rallies,
        strokes_by_rally=strokes_by_rally,
        role_by_match=role_by_match,
        set_to_match=set_to_match,
    )
    meta = build_response_meta("doubles_role", result_data.get("n_matches_analyzed", 0))
    return {"success": True, "data": result_data, "meta": meta}


# ---------------------------------------------------------------------------
# 昇格 Override: アナリストによる手動判断記録
# ---------------------------------------------------------------------------

class PromotionOverrideBody(BaseModel):
    analysis_type: str
    status: str  # "promotion_ready" | "requires_review" | "insufficient_data" | "hold"
    note: str = ""
    analyst: str = "analyst"


@router.get("/analysis/meta/promotion_overrides")
def get_promotion_overrides():
    """現在の昇格 override 一覧を返す。"""
    from backend.analysis.promotion_override_store import load_all_overrides
    return {"success": True, "data": load_all_overrides()}


@router.post("/analysis/meta/promotion_override")
def set_promotion_override(body: PromotionOverrideBody):
    """昇格 override を保存する（既存は上書き）。"""
    from backend.analysis.promotion_override_store import save_override, VALID_STATUSES
    if body.status not in VALID_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")
    entry = save_override(
        analysis_type=body.analysis_type,
        status=body.status,
        note=body.note,
        analyst=body.analyst,
    )
    return {"success": True, "data": entry}


@router.delete("/analysis/meta/promotion_override/{analysis_type}")
def delete_promotion_override(analysis_type: str, analyst: str = Query(default="analyst")):
    """昇格 override を削除する。analyst パラメータで操作者を記録。"""
    from backend.analysis.promotion_override_store import delete_override
    deleted = delete_override(analysis_type, analyst=analyst)
    return {"success": True, "deleted": deleted}


@router.get("/analysis/meta/promotion_override/{analysis_type}/history")
def get_override_history(analysis_type: str):
    """
    指定 analysis_type の override 操作履歴を返す（新しい順）。
    エントリが削除済みでも audit_log.json から参照可能。
    """
    from backend.analysis.promotion_override_store import get_audit_log
    history = get_audit_log(analysis_type=analysis_type)
    return {"success": True, "data": history}


@router.get("/analysis/meta/promotion_overrides/audit_log")
def get_all_override_audit_log():
    """全 override 操作の監査ログを返す（新しい順）。analyst/coach 向け。"""
    from backend.analysis.promotion_override_store import get_audit_log
    history = get_audit_log()
    return {"success": True, "data": history}
