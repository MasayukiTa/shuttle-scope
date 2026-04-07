"""予測 API エンドポイント — Phase A + B"""
from typing import Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Player
from backend.analysis.prediction_engine import (
    get_matches_for_player,
    get_pair_matches,
    compute_win_probability,
    compute_set_distribution,
    compute_score_bands,
    compute_most_likely_scorelines,
    compute_calibrated_scorelines,
    compute_fatigue_risk,
    get_observation_context,
    build_tactical_notes,
    build_caution_flags,
    compute_confidence_score,
    confidence_meta,
)

router = APIRouter()


@router.get("/prediction/match_preview")
def get_match_preview(
    player_id: int,
    opponent_id: Optional[int] = None,
    tournament_level: Optional[str] = None,
    match_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """
    試合プレビュー予測。
    - H2H データがある場合は優先使用
    - なければ全試合統計にフォールバック
    """
    all_matches = get_matches_for_player(db, player_id)
    h2h_matches = (
        get_matches_for_player(db, player_id, opponent_id=opponent_id)
        if opponent_id else []
    )
    level_matches = (
        get_matches_for_player(db, player_id, tournament_level=tournament_level)
        if tournament_level else []
    )

    # 使用データ優先順: H2H(≥3) > 同レベル(≥3) > 全試合
    if len(h2h_matches) >= 3:
        primary = h2h_matches
    elif tournament_level and len(level_matches) >= 3:
        primary = level_matches
    else:
        primary = all_matches

    win_prob, sample_size = compute_win_probability(primary, player_id)
    set_dist = compute_set_distribution(primary, player_id, win_prob)
    score_bands = compute_score_bands(primary, player_id)
    scorelines = compute_most_likely_scorelines(set_dist, score_bands)
    calibrated_scorelines = compute_calibrated_scorelines(primary, player_id)

    obs_context = get_observation_context(db, player_id, opponent_id, match_id)
    opponent_player = db.get(Player, opponent_id) if opponent_id else None
    tactical_notes = build_tactical_notes(win_prob, sample_size, obs_context, opponent_player)
    caution_flags = build_caution_flags(win_prob, sample_size, obs_context)

    similar_count = len(h2h_matches)
    confidence = compute_confidence_score(sample_size, similar_count)

    return {
        "success": True,
        "data": {
            "win_probability": win_prob,
            "set_distribution": set_dist,
            "score_bands": score_bands,
            "most_likely_scorelines": scorelines,
            "confidence": confidence,
            "sample_size": sample_size,
            "similar_matches": similar_count,
            "observation_context": obs_context,
            "tactical_notes": tactical_notes,
            "caution_flags": caution_flags,
            "calibrated_scorelines": calibrated_scorelines,
        },
        "meta": {
            "sample_size": sample_size,
            "confidence": confidence_meta(confidence, sample_size),
        },
    }


@router.get("/prediction/fatigue_risk")
def get_fatigue_risk(
    player_id: int,
    tournament_level: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    疲労・崩壊リスク予測 (Phase C)
    序盤/終盤の勝率差・長ラリー後ペナルティ・デュース時勝率低下から推定。
    """
    result = compute_fatigue_risk(db, player_id, tournament_level=tournament_level)
    return {
        "success": True,
        "data": result,
        "meta": {
            "confidence": confidence_meta(result["confidence"], result["breakdown"]["total_rallies"]),
        },
    }

@router.get("/prediction/pair_simulation")
def get_pair_simulation(
    player_id_1: int,
    player_id_2: int,
    tournament_level: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    ペアシミュレーション。
    player_id_1 / player_id_2 のペアとしての過去試合を集計。
    """
    pair_matches = get_pair_matches(db, player_id_1, player_id_2, tournament_level)

    win_prob, sample_size = compute_win_probability(pair_matches, player_id_1)
    set_dist = compute_set_distribution(pair_matches, player_id_1, win_prob)
    score_bands = compute_score_bands(pair_matches, player_id_1)

    confidence = compute_confidence_score(sample_size, sample_size)

    p1 = db.get(Player, player_id_1)
    p2 = db.get(Player, player_id_2)
    pair_name = f"{p1.name if p1 else '?'} / {p2.name if p2 else '?'}"

    strengths: list[str] = []
    cautions: list[str] = []
    if sample_size == 0:
        cautions.append('ペアとしての対戦データなし — 個人成績から予測できません')
    elif sample_size < 5:
        cautions.append(f'少数サンプル（{sample_size}試合） — 推定精度が低め')
    if win_prob >= 0.60 and sample_size >= 3:
        strengths.append(f'このペアの過去勝率は {int(win_prob * 100)}%（{sample_size}試合）')

    return {
        "success": True,
        "data": {
            "pair_name": pair_name,
            "win_probability": win_prob,
            "set_distribution": set_dist,
            "score_bands": score_bands,
            "pair_strengths": strengths,
            "pair_cautions": cautions,
            "tactical_notes": [],
            "confidence": confidence,
            "sample_size": sample_size,
        },
        "meta": {
            "sample_size": sample_size,
            "confidence": confidence_meta(confidence, sample_size),
        },
    }
