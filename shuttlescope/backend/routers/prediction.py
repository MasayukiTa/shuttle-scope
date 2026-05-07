"""予測 API エンドポイント — Phase A + B + Phase 1 Rebuild"""
from typing import Optional
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

import json
from backend.db.database import get_db
from backend.utils.auth import require_non_player, get_auth
from backend.db.models import Player, Match, PrematchPrediction
from backend.analysis.prediction_engine import (
    get_matches_for_player,
    get_pair_matches,
    compute_win_probability,
    compute_set_distribution,
    compute_score_bands,
    compute_most_likely_scorelines,
    compute_calibrated_scorelines,
    compute_fatigue_risk,
    compute_prediction_drivers,
    get_observation_context,
    build_tactical_notes,
    build_caution_flags,
    compute_confidence_score,
    confidence_meta,
    # Phase 1 Rebuild
    compute_recent_form,
    compute_growth_trend,
    compute_feature_win_prob,
    compute_set_model_v2,
    compute_brier_score,
    find_nearest_matches,
    # Phase S3/S4
    compute_score_volatility,
    compute_lineup_scores,
    compute_match_narrative,
)

# 全 prediction ルートは player ロール禁止。
# PlayerAccessControlMiddleware._PLAYER_FORBIDDEN_ANALYSIS_PATHS は analysis_* ルーター
# からしか自動収集されないため、prediction エンドポイントは middleware だけだと素通りする。
# router-level dependency で確実にガードする。
router = APIRouter(dependencies=[Depends(require_non_player)])


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
    - Phase 1 Rebuild: 多特徴量キャリブレーション済み勝率を追加
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

    # 観察コンテキストを先に取得（compute_feature_win_prob で必要）
    obs_context = get_observation_context(db, player_id, opponent_id, match_id)

    # 使用データ優先順: H2H(≥3) > 同レベル(≥3) > 全試合
    if len(h2h_matches) >= 3:
        primary = h2h_matches
    elif tournament_level and len(level_matches) >= 3:
        primary = level_matches
    else:
        primary = all_matches

    # v1: 既存 Laplace 勝率（後方互換）
    win_prob, sample_size = compute_win_probability(primary, player_id)

    # Phase S4: スコアボラティリティ
    score_volatility = compute_score_volatility(primary, player_id)

    recent_form = compute_recent_form(all_matches, player_id)
    win_prob_v2, feature_breakdown = compute_feature_win_prob(
        all_matches, player_id, h2h_matches, recent_form, obs_context
    )

    # Phase 1: モメンタムセットモデル
    # 実測 ≥5 試合ある場合は observed を渡す
    observed_set_count = sum(1 for m in primary if len(m.sets or []) >= 2)
    raw_set_dist = compute_set_distribution(primary, player_id, win_prob_v2)
    set_model = compute_set_model_v2(
        win_prob_v2,
        raw_set_dist if observed_set_count >= 5 else None,
    )
    set_dist = set_model['dist']

    score_bands = compute_score_bands(primary, player_id)
    scorelines = compute_most_likely_scorelines(set_dist, score_bands)
    calibrated_scorelines = compute_calibrated_scorelines(primary, player_id)
    # Perf: 既に取得済みの matches/obs を渡して再クエリを回避
    prediction_drivers = compute_prediction_drivers(
        db, player_id, opponent_id, tournament_level,
        all_matches=all_matches,
        h2h_matches=h2h_matches,
        level_matches=level_matches if tournament_level else [],
        obs_context=obs_context,
    )

    opponent_player = db.get(Player, opponent_id) if opponent_id else None
    tactical_notes = build_tactical_notes(win_prob_v2, sample_size, obs_context, opponent_player)
    caution_flags = build_caution_flags(win_prob_v2, sample_size, obs_context)

    similar_count = len(h2h_matches)
    confidence = compute_confidence_score(sample_size, similar_count)

    # 試合前サマリーナレーション（決め手・ぐだり局面・スコア予測を統合）
    player_obj = db.get(Player, player_id)
    match_narrative = compute_match_narrative(
        player_name=player_obj.name if player_obj else '自分',
        opponent_name=opponent_player.name if opponent_player else '相手',
        win_prob=win_prob_v2,
        sample_size=sample_size,
        set_distribution=set_dist,
        most_likely_scorelines=scorelines,
        score_volatility=score_volatility,
        recent_form=recent_form,
        obs_context=obs_context,
        h2h_count=len(h2h_matches),
        tournament_level=tournament_level,
    )

    return {
        "success": True,
        "data": {
            # 後方互換: v1 勝率を win_probability として維持
            "win_probability": win_prob,
            "win_probability_v2": win_prob_v2,
            "feature_breakdown": feature_breakdown,
            "recent_form": recent_form,
            "set_distribution": set_dist,
            "set_model_type": set_model['model_type'],
            "score_bands": score_bands,
            "most_likely_scorelines": scorelines,
            "confidence": confidence,
            "sample_size": sample_size,
            "similar_matches": similar_count,
            "observation_context": obs_context,
            "tactical_notes": tactical_notes,
            "caution_flags": caution_flags,
            "calibrated_scorelines": calibrated_scorelines,
            "prediction_drivers": prediction_drivers,
            "score_volatility": score_volatility,
            "match_narrative": match_narrative,
        },
        "meta": {
            "sample_size": sample_size,
            "confidence": confidence_meta(confidence, sample_size),
        },
    }


@router.get("/prediction/lineup_optimizer")
def get_lineup_optimizer(
    player_ids: str,
    opponent_id: Optional[int] = None,
    tournament_level: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Phase S3: ラインナップ最適化。
    複数の候補選手を対象相手・大会レベルで評価し、勝率の高い順にランク付けする。
    player_ids: カンマ区切りの player_id リスト例 "1,2,3"
    """
    try:
        ids = [int(x.strip()) for x in player_ids.split(',') if x.strip()]
    except ValueError:
        return {"success": False, "error": "player_ids must be comma-separated integers"}

    if not ids:
        return {"success": False, "error": "player_ids is empty"}

    ranked = compute_lineup_scores(db, ids, opponent_id, tournament_level)

    return {
        "success": True,
        "data": {
            "ranked_players": ranked,
            "opponent_id": opponent_id,
            "tournament_level": tournament_level,
            "recommendation": ranked[0]['player_name'] if ranked else None,
        },
    }


@router.get("/prediction/analyst_depth")
def get_analyst_depth(
    player_id: int,
    opponent_id: Optional[int] = None,
    tournament_level: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    アナリスト向け深掘り予測データ。
    - 直近フォームトレンド
    - 成長トレンド（時系列バケット）
    - ブライアスコア（予測キャリブレーション）
    - 最近傍試合エビデンス
    - 多特徴量ブレンド内訳
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
    obs_context = get_observation_context(db, player_id, opponent_id)

    recent_form = compute_recent_form(all_matches, player_id)
    growth_trend = compute_growth_trend(all_matches, player_id)
    brier_score = compute_brier_score(all_matches, player_id)
    nearest_evidence = find_nearest_matches(
        all_matches, player_id,
        current_level=tournament_level or '',
        n=5,
    )

    win_prob_v1, _ = compute_win_probability(all_matches, player_id)
    win_prob_v2, feature_breakdown = compute_feature_win_prob(
        all_matches, player_id, h2h_matches, recent_form, obs_context
    )

    # セットモデルタイプ
    if len(h2h_matches) >= 3:
        primary = h2h_matches
    elif tournament_level and len(level_matches) >= 3:
        primary = level_matches
    else:
        primary = all_matches
    observed_set_count = sum(1 for m in primary if len(m.sets or []) >= 2)
    set_model_type = 'observed' if observed_set_count >= 5 else 'momentum'

    return {
        "success": True,
        "data": {
            "recent_form": recent_form,
            "growth_trend": growth_trend,
            "brier_score": brier_score,
            "nearest_match_evidence": nearest_evidence,
            "set_model_type": set_model_type,
            "feature_breakdown": feature_breakdown,
            "win_prob_v1": win_prob_v1,
            "win_prob_v2": win_prob_v2,
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

@router.get("/prediction/prematch_by_match")
def get_prematch_by_match(
    match_id: int,
    player_id: int,
    request: Request,
    force: bool = False,
    db: Session = Depends(get_db),
):
    """
    試合前統計予測 — 特定の試合を基準に、その試合日より前のデータのみで予測を行う。
    - 対戦相手は試合レコードから確定
    - データカットオフ = 試合日（当日含まず）
    - 一度算出した結果は DB に保存し、以降は再算出しない（スナップショット）
    - force=true で強制再計算・上書き保存
    """
    # rereview NEW-N3 fix: actor の team_id を取得して _upsert_prematch_prediction に渡す。
    # 旧コードは team_id=None で呼び出され、prematch_predictions テーブルが
    # 全スコープ書き込みになっていた (他チームの prediction を上書きできる経路あり)。
    _actor_ctx = get_auth(request)
    _actor_team_id = getattr(_actor_ctx, "team_id", None)
    match = db.get(Match, match_id)
    if not match:
        return {"success": False, "error": "Match not found"}

    # 対戦相手を確定
    if match.player_a_id == player_id:
        opponent_id = match.player_b_id
    elif match.player_b_id == player_id:
        opponent_id = match.player_a_id
    else:
        return {"success": False, "error": "Player not in this match"}

    # ── DB キャッシュ確認 ──────────────────────────────────────────────────────
    if not force:
        cached = (
            db.query(PrematchPrediction)
            .filter_by(match_id=match_id, player_id=player_id)
            .first()
        )
        if cached:
            opponent_obj = db.get(Player, cached.opponent_id)
            return {
                "success": True,
                "cached": True,
                "data": {
                    "match_date": str(cached.cutoff_date),
                    "opponent_id": cached.opponent_id,
                    "opponent_name": opponent_obj.name if opponent_obj else "?",
                    "tournament_level": cached.tournament_level,
                    "cutoff_date": str(cached.cutoff_date),
                    "sample_size": cached.sample_size,
                    "h2h_count": cached.h2h_count,
                    "win_probability": cached.win_probability,
                    "set_distribution": json.loads(cached.set_distribution) if cached.set_distribution else None,
                    "most_likely_scorelines": json.loads(cached.most_likely_scorelines) if cached.most_likely_scorelines else [],
                    "score_volatility": json.loads(cached.score_volatility) if cached.score_volatility else None,
                    "confidence": cached.confidence,
                    "confidence_meta": confidence_meta(cached.confidence, cached.sample_size) if cached.confidence else None,
                    "match_narrative": json.loads(cached.match_narrative) if cached.match_narrative else None,
                    "computed_at": cached.computed_at.isoformat() if cached.computed_at else None,
                }
            }

    # ── 新規算出 ──────────────────────────────────────────────────────────────
    cutoff_date = match.date
    tournament_level = match.tournament_level

    all_matches = get_matches_for_player(db, player_id, before_date=cutoff_date)
    h2h_matches = get_matches_for_player(db, player_id, opponent_id=opponent_id, before_date=cutoff_date)
    level_matches = get_matches_for_player(db, player_id, tournament_level=tournament_level, before_date=cutoff_date)

    obs_context = get_observation_context(db, player_id, opponent_id, match_id)

    if len(h2h_matches) >= 3:
        primary = h2h_matches
    elif len(level_matches) >= 3:
        primary = level_matches
    else:
        primary = all_matches

    sample_size = len(primary)
    h2h_count = len(h2h_matches)
    player_obj = db.get(Player, player_id)
    opponent_obj = db.get(Player, opponent_id)

    if sample_size == 0:
        # データなしでも保存しておく（毎回計算しないため）
        _upsert_prematch_prediction(db, match_id, player_id, opponent_id, cutoff_date, tournament_level,
                                    sample_size=0, h2h_count=0,
                                    win_probability=None, set_dist=None,
                                    scorelines=None, score_volatility=None,
                                    confidence=None, match_narrative=None,
                                    team_id=_actor_team_id)
        return {
            "success": True,
            "cached": False,
            "data": {
                "match_date": str(cutoff_date),
                "opponent_id": opponent_id,
                "opponent_name": opponent_obj.name if opponent_obj else "?",
                "tournament_level": tournament_level,
                "cutoff_date": str(cutoff_date),
                "sample_size": 0,
                "h2h_count": 0,
                "win_probability": None,
                "set_distribution": None,
                "most_likely_scorelines": [],
                "score_volatility": None,
                "confidence": None,
                "confidence_meta": None,
                "match_narrative": None,
            }
        }

    recent_form = compute_recent_form(all_matches, player_id)
    win_prob_v2, _ = compute_feature_win_prob(all_matches, player_id, h2h_matches, recent_form, obs_context)

    score_volatility = compute_score_volatility(primary, player_id)

    observed_set_count = sum(1 for m in primary if len(m.sets or []) >= 2)
    raw_set_dist = compute_set_distribution(primary, player_id, win_prob_v2)
    set_model = compute_set_model_v2(
        win_prob_v2,
        raw_set_dist if observed_set_count >= 5 else None,
    )
    set_dist = set_model['dist']

    score_bands = compute_score_bands(primary, player_id)
    scorelines = compute_most_likely_scorelines(set_dist, score_bands)
    confidence_val = compute_confidence_score(sample_size, h2h_count)

    match_narrative = compute_match_narrative(
        player_name=player_obj.name if player_obj else '自分',
        opponent_name=opponent_obj.name if opponent_obj else '相手',
        win_prob=win_prob_v2,
        sample_size=sample_size,
        set_distribution=set_dist,
        most_likely_scorelines=scorelines,
        score_volatility=score_volatility,
        recent_form=recent_form,
        obs_context=obs_context,
        h2h_count=h2h_count,
        tournament_level=tournament_level,
    )

    # ── DB に保存 ─────────────────────────────────────────────────────────────
    _upsert_prematch_prediction(db, match_id, player_id, opponent_id, cutoff_date, tournament_level,
                                sample_size=sample_size, h2h_count=h2h_count,
                                win_probability=win_prob_v2, set_dist=set_dist,
                                scorelines=scorelines, score_volatility=score_volatility,
                                confidence=confidence_val, match_narrative=match_narrative,
                                team_id=_actor_team_id)

    return {
        "success": True,
        "cached": False,
        "data": {
            "match_date": str(cutoff_date),
            "opponent_id": opponent_id,
            "opponent_name": opponent_obj.name if opponent_obj else "?",
            "tournament_level": tournament_level,
            "cutoff_date": str(cutoff_date),
            "sample_size": sample_size,
            "h2h_count": h2h_count,
            "win_probability": win_prob_v2,
            "set_distribution": set_dist,
            "most_likely_scorelines": scorelines,
            "score_volatility": score_volatility,
            "confidence": confidence_val,
            "confidence_meta": confidence_meta(confidence_val, sample_size),
            "match_narrative": match_narrative,
        }
    }


def _upsert_prematch_prediction(
    db: Session, match_id: int, player_id: int, opponent_id: int,
    cutoff_date, tournament_level: str,
    sample_size: int, h2h_count: int,
    win_probability, set_dist, scorelines, score_volatility,
    confidence, match_narrative,
    team_id: Optional[int] = None,
) -> None:
    """prematch_predictions に upsert する（既存あれば上書き）

    Phase B-12: team_id を受け取り、既存行のチームスコープを指定してフィルタする。
    team_id=None の場合は admin 互換扱い（全スコープ更新）。
    """
    from datetime import datetime as _dt
    from sqlalchemy import or_ as _or
    q = db.query(PrematchPrediction).filter_by(match_id=match_id, player_id=player_id)
    if team_id is not None:
        q = q.filter(_or(PrematchPrediction.team_id.is_(None), PrematchPrediction.team_id == team_id))
    existing = q.first()
    if existing:
        existing.opponent_id          = opponent_id
        existing.cutoff_date          = cutoff_date
        existing.tournament_level     = tournament_level
        existing.sample_size          = sample_size
        existing.h2h_count            = h2h_count
        existing.win_probability      = win_probability
        existing.set_distribution     = json.dumps(set_dist)     if set_dist     else None
        existing.most_likely_scorelines = json.dumps(scorelines) if scorelines   else None
        existing.score_volatility     = json.dumps(score_volatility) if score_volatility else None
        existing.confidence           = confidence
        existing.match_narrative      = json.dumps(match_narrative) if match_narrative else None
        existing.computed_at          = _dt.utcnow()
        if existing.team_id is None and team_id is not None:
            existing.team_id = team_id
    else:
        rec = PrematchPrediction(
            match_id=match_id, player_id=player_id, opponent_id=opponent_id,
            cutoff_date=cutoff_date, tournament_level=tournament_level,
            sample_size=sample_size, h2h_count=h2h_count,
            win_probability=win_probability,
            set_distribution=json.dumps(set_dist)     if set_dist     else None,
            most_likely_scorelines=json.dumps(scorelines) if scorelines else None,
            score_volatility=json.dumps(score_volatility) if score_volatility else None,
            confidence=confidence,
            match_narrative=json.dumps(match_narrative) if match_narrative else None,
            computed_at=_dt.utcnow(),
            team_id=team_id,
        )
        db.add(rec)
    db.commit()


@router.get("/prediction/pair_ranking")
def get_pair_ranking(
    anchor_player_id: int,
    tournament_level: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    【アナリスト専用】anchor_player_id に対して最良パートナー候補をランキング形式で返す。
    全選手を候補としてペア試合実績から勝率を計算し、降順でソートする。
    コーチ・選手には返してはいけないエンドポイント（フロントエンド側で RoleGuard 必須）。
    """
    all_players = db.query(Player).order_by(Player.name).all()
    anchor = db.get(Player, anchor_player_id)

    # Perf: anchor を含むペア試合を一括取得し、候補 partner_id でグルーピング。
    # 旧実装は候補選手ごとに `get_pair_matches` を発行していたため N+1。
    from sqlalchemy.orm import selectinload as _selectinload
    from sqlalchemy import or_ as _or_, and_ as _and_
    _pair_q = (
        db.query(Match)
        .options(_selectinload(Match.sets))
        .filter(Match.result.in_(['win', 'loss']))
        .filter(
            _or_(
                _and_(Match.player_a_id == anchor_player_id, Match.partner_a_id.isnot(None)),
                _and_(Match.player_b_id == anchor_player_id, Match.partner_b_id.isnot(None)),
                Match.partner_a_id == anchor_player_id,
                Match.partner_b_id == anchor_player_id,
            )
        )
    )
    if tournament_level:
        _pair_q = _pair_q.filter(Match.tournament_level == tournament_level)
    _all_pair_matches = _pair_q.all()
    _pair_by_partner: dict[int, list[Match]] = {}
    for _m in _all_pair_matches:
        # anchor のパートナー ID を特定
        if _m.player_a_id == anchor_player_id:
            _partner = _m.partner_a_id
        elif _m.partner_a_id == anchor_player_id:
            _partner = _m.player_a_id
        elif _m.player_b_id == anchor_player_id:
            _partner = _m.partner_b_id
        elif _m.partner_b_id == anchor_player_id:
            _partner = _m.player_b_id
        else:
            continue
        if _partner is None:
            continue
        _pair_by_partner.setdefault(_partner, []).append(_m)

    results = []
    for candidate in all_players:
        if candidate.id == anchor_player_id:
            continue
        pair_matches = _pair_by_partner.get(candidate.id, [])
        win_prob, sample_size = compute_win_probability(pair_matches, anchor_player_id)
        confidence = compute_confidence_score(sample_size, sample_size)
        results.append({
            "partner_id": candidate.id,
            "partner_name": candidate.name,
            "partner_team": getattr(candidate, "team", None),
            "win_probability": win_prob,
            "sample_size": sample_size,
            "confidence": confidence,
            "confidence_meta": confidence_meta(confidence, sample_size),
        })

    # 勝率降順 → サンプル数降順でソート
    results.sort(key=lambda x: (-x["win_probability"], -x["sample_size"]))
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return {
        "success": True,
        "data": {
            "anchor_player": {
                "id": anchor_player_id,
                "name": anchor.name if anchor else "?",
            },
            "ranked_partners": results,
            "tournament_level": tournament_level,
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
