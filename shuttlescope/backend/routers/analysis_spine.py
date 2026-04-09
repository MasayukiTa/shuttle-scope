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

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, GameSet, Rally, Stroke
from backend.analysis.router_helpers import (
    _player_role_in_match, _get_player_matches, _fetch_matches_sets_rallies,
)
from backend.analysis.response_meta import build_response_meta
from backend.analysis.analysis_meta import EVIDENCE_META
from backend.analysis.promotion_rules import all_criteria_as_dict, DEMOTION_CONDITIONS
from backend.analysis.epv_state_model import compute_rally_state_epv, compute_epv_state_map
from backend.analysis.q_value_model import compute_q_values, summarize_best_actions
from backend.analysis.counterfactual_v2 import compute_counterfactual_v2, compute_counterfactual_cf2
from backend.analysis.hazard_fatigue import compute_hazard_model
from backend.analysis.bayes_matchup import compute_bayes_matchup
from backend.analysis.opponent_policy_engine import compute_opponent_policy
from backend.analysis.doubles_role_inference import compute_doubles_role_inference, compute_doubles_role_db2
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
    doubles_matches = [m for m in matches if getattr(m, 'format', None) == 'doubles']
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
    doubles_matches = [m for m in all_matches if getattr(m, 'match_type', None) in ('doubles', 'mixed_doubles')]

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
    """各 analysis_type の evidence メタデータ一覧をリスト形式で返す。"""
    from backend.analysis.analysis_tiers import get_min_samples
    entries = []
    for analysis_type, meta in EVIDENCE_META.items():
        entries.append({
            "analysis_type": analysis_type,
            "tier": _infer_tier(analysis_type),
            "evidence_level": meta.get("evidence_level", "exploratory"),
            "min_recommended_sample": get_min_samples(analysis_type),
            "caution": meta.get("caution"),
            "assumptions": meta.get("assumptions"),
            "promotion_criteria": meta.get("promotion_criteria"),
        })
    return {
        "success": True,
        "data": entries,
    }


def _infer_tier(analysis_type: str) -> str:
    """analysis_type から tier を推定する。"""
    stable_types = {"descriptive", "heatmap", "score_progression", "first_return", "set_summary"}
    research_types = {
        "counterfactual", "opponent_affinity", "pair_synergy", "epv",
        "shot_influence", "spatial_density",
        "epv_state", "state_action", "hazard_fatigue", "counterfactual_v2",
        "bayes_matchup", "opponent_policy", "doubles_role",
    }
    if analysis_type in stable_types:
        return "stable"
    if analysis_type in research_types:
        return "research"
    return "advanced"


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
