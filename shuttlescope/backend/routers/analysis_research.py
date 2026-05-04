"""analysis_research.py — research tier 解析エンドポイント"""
import logging
import math

logger = logging.getLogger(__name__)
from collections import defaultdict, Counter
from datetime import date as DateType
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.utils.auth import require_admin_or_analyst
from backend.db.models import Match, GameSet, Rally, Stroke, Player, PreMatchObservation
from backend.utils.confidence import check_confidence
from backend.analysis.router_helpers import (
    SHOT_TYPE_JA, SHOT_KEYS, SHOT_LABELS_JA, END_TYPE_JA, _shot_ja,
    _player_role_in_match, _get_player_matches, _fetch_matches_sets_rallies,
)
from backend.analysis.analysis_config import AnalysisConfig
from backend.analysis.markov import MarkovAnalyzer
from backend.analysis.shot_influence import ShotInfluenceAnalyzer
from backend.analysis.bayesian_rt import BayesianRealTimeAnalyzer
from backend.analysis.analysis_tiers import all_tiers_meta
from backend.analysis.recommendation_engine import (
    compute_player_baseline,
    compute_context_baselines,
    build_recommendation_item,
    rank_recommendations,
)
from backend.analysis.opponent_classifier import (
    classify_all_opponents,
    aggregate_affinity_by_axis,
)
from backend.analysis.counterfactual_engine import (
    collect_context_stats,
    build_comparisons,
    summarize_by_dimension,
)
from backend.analysis.epv_engine import (
    compute_state_epv,
    compute_state_influence,
    classify_score_state,
    classify_momentum,
)

# research tier は admin/analyst のみ。middleware (_PLAYER_FORBIDDEN_ANALYSIS_PATHS) は
# import 失敗時に silent に空集合化するため、router-level dependency でも明示ガードする。
router = APIRouter(dependencies=[Depends(require_admin_or_analyst)])


# ---------------------------------------------------------------------------
# G-001: マルコフEPV（期待パターン価値）
# ---------------------------------------------------------------------------

@router.get("/analysis/epv")
def get_epv(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """G-001: マルコフ連鎖に基づくショットパターンのEPVを計算する（アナリスト・コーチ向け）"""
    return _epv_impl(db, player_id, ctx=None,
                     result=result, tournament_level=tournament_level,
                     date_from=date_from, date_to=date_to)


def _epv_impl(db: Session, player_id: int, ctx=None,
              result=None, tournament_level=None,
              date_from=None, date_to=None):
    """G-001 EPV impl — ctx が渡されれば共有データを使う。"""
    if ctx is not None:
        matches = ctx.matches
        role_by_match = ctx.role_by_match
        set_to_match = ctx.set_to_match
        rallies = ctx.rallies
    else:
        matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    empty_confidence = check_confidence("shot_transition", 0)
    if not matches:
        return {
            "success": True,
            "data": {"top_patterns": [], "bottom_patterns": []},
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    if ctx is None:
        match_ids = [m.id for m in matches]
        role_by_match = {
            m.id: _player_role_in_match(m, player_id) for m in matches
        }
        sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
        set_to_match = {s.id: s.match_id for s in sets}
        set_ids = [s.id for s in sets]
        rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []

    rally_ids = [r.id for r in rallies]

    rally_player_won: dict[int, bool] = {}
    rally_to_role: dict[int, str] = {}
    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        role = role_by_match[match_id]
        rally_to_role[rally.id] = role
        rally_player_won[rally.id] = rally.winner == role

    if not rally_ids:
        return {
            "success": True,
            "data": {"top_patterns": [], "bottom_patterns": []},
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    if ctx is not None:
        # ctx.strokes は順序未保証なので rally_id, stroke_num で整列してから利用する
        strokes_by_rally: dict[int, list] = defaultdict(list)
        for stroke in ctx.strokes:
            strokes_by_rally[stroke.rally_id].append(stroke)
        for rid in strokes_by_rally:
            strokes_by_rally[rid].sort(key=lambda s: s.stroke_num)
    else:
        all_strokes = (
            db.query(Stroke)
            .filter(Stroke.rally_id.in_(rally_ids))
            .order_by(Stroke.rally_id, Stroke.stroke_num)
            .all()
        )

        # ラリーごとにストロークをグループ化してMarkovAnalyzer向けリストを構築
        strokes_by_rally = defaultdict(list)
        for stroke in all_strokes:
            strokes_by_rally[stroke.rally_id].append(stroke)

    strokes_list = []
    total_strokes = 0
    for rally in rallies:
        role = rally_to_role.get(rally.id)
        won = rally_player_won.get(rally.id, False)
        stks = strokes_by_rally.get(rally.id, [])
        player_strokes = [s for s in stks if s.player == role]
        total_strokes += len(player_strokes)

        rally_data = [
            {
                "shot_type": s.shot_type,
                "shot_quality": s.shot_quality,
                "stroke_num": s.stroke_num,
                "player_won": won,
                "id": s.id,
            }
            for s in player_strokes
        ]
        if rally_data:
            strokes_list.append(rally_data)

    analyzer = MarkovAnalyzer()
    # 全パターンを取得（min_count + ベイズ縮小済み）し、上位/下位を分離
    all_patterns = analyzer.get_top_patterns(strokes_list, top_k=None)

    top_patterns = [p for p in all_patterns if p["epv"] > 0][:10]
    bottom_patterns = sorted(
        [p for p in all_patterns if p["epv"] < 0],
        key=lambda x: x["epv"],
    )[:10]

    # S3-B: State-based EPV を追加
    state_epv_result = compute_state_epv(
        rallies, strokes_by_rally, role_by_match, set_to_match,
    )

    confidence = check_confidence("shot_transition", total_strokes)

    return {
        "success": True,
        "data": {
            "top_patterns": top_patterns,
            "bottom_patterns": bottom_patterns,
            "state_epv": state_epv_result.get("state_epv", {}),
            "global_epv": state_epv_result.get("global_epv", {}),
            "state_summary": state_epv_result.get("state_summary", {}),
        },
        "meta": {"sample_size": total_strokes, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# G-002: ショット影響度（アナリスト・コーチ向け）
# ---------------------------------------------------------------------------

@router.get("/analysis/shot_influence")
def get_shot_influence(match_id: int, db: Session = Depends(get_db)):
    """G-002: 試合内の各ショットの影響度スコアを返す（アナリスト・コーチ向け）"""
    match = db.get(Match, match_id)
    if not match:
        return {"success": False, "error": f"試合ID {match_id} が見つかりません"}

    sets = db.query(GameSet).filter(GameSet.match_id == match_id).all()
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    rally_ids = [r.id for r in rallies]

    if not rally_ids:
        return {
            "success": True,
            "data": {"rallies": [], "shot_type_summary": {}},
            "meta": {"sample_size": 0, "confidence": check_confidence("shot_transition", 0)},
        }

    all_strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(rally_ids))
        .order_by(Stroke.rally_id, Stroke.stroke_num)
        .all()
    )

    strokes_by_rally: dict[int, list] = defaultdict(list)
    for stroke in all_strokes:
        strokes_by_rally[stroke.rally_id].append(stroke)

    # player_a 基準でショット影響度を計算
    # S3-B: state-based influence を追加
    analyzer = ShotInfluenceAnalyzer()
    all_rally_data = []

    # セット内のラリー結果を時系列で追跡（モメンタム計算用）
    set_results: dict[int, list[bool]] = defaultdict(list)
    sorted_rallies = sorted(rallies, key=lambda r: (r.set_id, r.rally_num))
    rally_order = {r.id: i for i, r in enumerate(sorted_rallies)}
    # 先にモメンタムを計算するためラリーを一巡
    rally_momentum: dict[int, str] = {}
    for rally in sorted_rallies:
        won = rally.winner == "player_a"
        rally_momentum[rally.id] = classify_momentum(set_results[rally.set_id])
        set_results[rally.set_id].append(won)

    for rally in rallies:
        stks = strokes_by_rally.get(rally.id, [])
        player_a_strokes = [s for s in stks if s.player == "player_a"]
        won = rally.winner == "player_a"

        score_state = classify_score_state(
            rally.score_a_before, rally.score_b_before, True,
        )
        momentum = rally_momentum.get(rally.id, "neutral")

        stroke_dicts = [
            {
                "id": s.id,
                "shot_type": s.shot_type,
                "shot_quality": s.shot_quality,
                "stroke_num": s.stroke_num,
                "score_diff": rally.score_a_after - rally.score_b_after,
            }
            for s in player_a_strokes
        ]

        # 従来互換: ヒューリスティック影響度
        influences = analyzer.compute_heuristic_influence(stroke_dicts, won)

        # S3-B: state-aware 影響度
        state_influences = compute_state_influence(
            stroke_dicts, won,
            score_state=score_state,
            momentum=momentum,
        )

        # 従来データに state_factors を追加
        state_by_id = {si["stroke_id"]: si for si in state_influences}
        for inf in influences:
            si = state_by_id.get(inf.get("stroke_id"))
            if si:
                inf["influence_state"] = si["influence_score"]
                inf["state_factors"] = si["state_factors"]

        all_rally_data.append({
            "rally_id": rally.id,
            "rally_num": rally.rally_num,
            "won": won,
            "score_state": score_state,
            "momentum": momentum,
            "strokes": influences,
        })

    # ショット種別ごとの平均影響度（従来 + state）
    shot_scores: dict[str, list[float]] = defaultdict(list)
    shot_state_scores: dict[str, list[float]] = defaultdict(list)
    for rally_data in all_rally_data:
        for s in rally_data["strokes"]:
            shot_scores[s["shot_type"]].append(s["influence_score"])
            if "influence_state" in s:
                shot_state_scores[s["shot_type"]].append(s["influence_state"])

    shot_type_summary = {
        st: round(sum(scores) / len(scores), 4) if scores else 0.0
        for st, scores in sorted(shot_scores.items())
    }
    shot_type_state_summary = {
        st: round(sum(scores) / len(scores), 4) if scores else 0.0
        for st, scores in sorted(shot_state_scores.items())
    }

    total_strokes = sum(len(rd["strokes"]) for rd in all_rally_data)
    confidence = check_confidence("shot_transition", total_strokes)

    return {
        "success": True,
        "data": {
            "rallies": all_rally_data,
            "shot_type_summary": shot_type_summary,
            "shot_type_state_summary": shot_type_state_summary,
        },
        "meta": {"sample_size": total_strokes, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# H-001: ベイズリアルタイム速報レポート
# ---------------------------------------------------------------------------

@router.get("/analysis/interval_report")
def get_interval_report(
    match_id: int,
    completed_set_num: int = Query(1, ge=1),
    db: Session = Depends(get_db),
):
    """H-001: セット間速報レポートをベイズ推定で生成する"""
    analyzer = BayesianRealTimeAnalyzer()
    try:
        result = analyzer.generate_interval_report(match_id, completed_set_num, db)
    except Exception:
        logger.exception("interval_report generation failed")
        return {"success": False, "error": "レポート生成に失敗しました"}

    if not result.get("success"):
        # Stack-trace-exposure 防止: 内部エラー詳細は返さない
        logger.warning("interval_report returned failure")
        return {"success": False, "error": "レポート生成に失敗しました"}

    # sample_size を計算して meta に付与
    _sets = result.get("data", {}).get("sets", [])
    total_rallies = sum(s.get("rally_count", 0) for s in _sets)
    confidence = check_confidence("descriptive_basic", total_rallies)

    # Stack-trace-exposure 防止: 返却 data を必要フィールドのみに再構築
    _data = result.get("data", {})
    safe_data = {
        "sets": _sets,
        "summary": _data.get("summary"),
        "match_id": _data.get("match_id"),
        "completed_set_num": _data.get("completed_set_num"),
    }
    return {
        "success": True,
        "data": safe_data,
        "meta": {"sample_size": total_rallies, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# Research Roadmap R3: Rally Sequence Patterns (3.1)
# ---------------------------------------------------------------------------

@router.get("/analysis/rally_sequence_patterns")
def get_rally_sequence_patterns(
    player_id: int,
    db: Session = Depends(get_db),
):
    """ラリー3連ショットパターン — 勝ち/負けに関連する3ショット連続パターン"""
    return _rally_sequence_patterns_impl(db, player_id, None)


def _rally_sequence_patterns_impl(db: Session, player_id: int, ctx=None):
    if ctx is not None:
        matches = ctx.rs_matches
        role_by_match = ctx.rs_role_by_match
        sets = ctx.rs_sets
        set_to_match = ctx.rs_set_to_match
        rallies = ctx.rs_rallies
    else:
        matches, role_by_match, sets, set_to_match, rallies, _ = _fetch_matches_sets_rallies(player_id, db)
    if not rallies:
        return {"success": True, "data": {"win_sequences": [], "loss_sequences": [], "total_rallies": 0},
                "meta": {"sample_size": 0, "confidence": check_confidence("descriptive_basic", 0)}}

    rally_ids = [r.id for r in rallies]
    rally_by_id = {r.id: r for r in rallies}

    if ctx is not None:
        strokes = sorted(ctx.rs_strokes, key=lambda s: (s.rally_id, s.stroke_num))
    else:
        strokes = (
            db.query(Stroke)
            .filter(Stroke.rally_id.in_(rally_ids))
            .order_by(Stroke.rally_id, Stroke.stroke_num)
            .all()
        )
    strokes_by_rally: dict[int, list] = defaultdict(list)
    for s in strokes:
        strokes_by_rally[s.rally_id].append(s)

    # トライグラム集計: key=(t1,t2,t3) -> {"count":N,"wins":N}
    trigram_stats: dict[tuple, dict] = defaultdict(lambda: {"count": 0, "wins": 0})

    for rally in rallies:
        mid = set_to_match.get(rally.set_id)
        if not mid:
            continue
        role = role_by_match.get(mid)
        if not role:
            continue
        is_win = rally.winner == role
        rally_strokes = strokes_by_rally[rally.id]
        # プレイヤーのストロークのみ抽出 (shot_type必須)
        player_shots = [s.shot_type for s in rally_strokes if s.player == role and s.shot_type]
        # 3連続パターン
        for i in range(len(player_shots) - 2):
            key = (player_shots[i], player_shots[i + 1], player_shots[i + 2])
            trigram_stats[key]["count"] += 1
            if is_win:
                trigram_stats[key]["wins"] += 1

    # 最低5回以上出現のパターンのみ
    MIN_COUNT = AnalysisConfig.MIN_SEQUENCES_PATTERN
    filtered = {k: v for k, v in trigram_stats.items() if v["count"] >= MIN_COUNT}

    def to_entry(key, vals):
        wr = round(vals["wins"] / vals["count"], 3)
        return {
            "sequence": list(key),
            "labels": [SHOT_TYPE_JA.get(t, t) for t in key],
            "count": vals["count"],
            "win_rate": wr,
            "win_count": vals["wins"],
        }

    entries = [to_entry(k, v) for k, v in filtered.items()]
    win_seqs = sorted([e for e in entries if e["win_rate"] >= 0.5], key=lambda x: -x["win_rate"])[:8]
    loss_seqs = sorted([e for e in entries if e["win_rate"] < 0.5], key=lambda x: x["win_rate"])[:8]

    total_rallies = len(rallies)
    total_strokes = sum(len(v) for v in strokes_by_rally.values())
    return {
        "success": True,
        "data": {
            "win_sequences": win_seqs,
            "loss_sequences": loss_seqs,
            "total_rallies": total_rallies,
        },
        "meta": {"sample_size": total_strokes, "confidence": check_confidence("descriptive_basic", total_strokes)},
    }


# ---------------------------------------------------------------------------
# Research Roadmap R4: Confidence Calibration (3.5)
# ---------------------------------------------------------------------------

@router.get("/analysis/confidence_calibration")
def get_confidence_calibration(
    player_id: int,
    db: Session = Depends(get_db),
):
    """信頼度キャリブレーション — 各指標のサンプルサイズ分布"""
    matches, role_by_match, sets, set_to_match, rallies, _ = _fetch_matches_sets_rallies(player_id, db)

    match_count = len(matches)
    rally_count = len(rallies)
    rally_ids = [r.id for r in rallies]

    strokes = db.query(Stroke).filter(Stroke.rally_id.in_(rally_ids)).all() if rally_ids else []
    total_strokes = len(strokes)

    # ショット種別別サンプルサイズ
    shot_counts: dict[str, int] = defaultdict(int)
    for s in strokes:
        if s.shot_type:
            shot_counts[s.shot_type] += 1

    # 各指標のサンプルサイズを収集
    sample_sizes: list[int] = []
    # 試合数
    sample_sizes.append(match_count)
    # ラリー数
    sample_sizes.append(rally_count)
    # 総ストローク数
    sample_sizes.append(total_strokes)
    # ショット種別ごと
    for st in SHOT_KEYS:
        sample_sizes.append(shot_counts.get(st, 0))

    # バケット分類
    TIERS = [
        {"tier": "データ不足 (<30)",   "min": 0,   "max": 29,  "label_en": "insufficient"},
        {"tier": "低信頼 (30-100)",    "min": 30,  "max": 99,  "label_en": "low"},
        {"tier": "中信頼 (100-300)",   "min": 100, "max": 299, "label_en": "medium"},
        {"tier": "高信頼 (300+)",      "min": 300, "max": 10**9, "label_en": "high"},
    ]

    counts_by_tier = defaultdict(int)
    for n in sample_sizes:
        for t in TIERS:
            if t["min"] <= n <= t["max"]:
                counts_by_tier[t["tier"]] += 1
                break

    total_metrics = len(sample_sizes)
    distribution = [
        {
            "tier": t["tier"],
            "label_en": t["label_en"],
            "count": counts_by_tier[t["tier"]],
            "ratio": round(counts_by_tier[t["tier"]] / total_metrics, 3) if total_metrics > 0 else 0,
        }
        for t in TIERS
    ]

    # 全体品質判定
    high_ratio = distribution[3]["ratio"]
    med_ratio = distribution[2]["ratio"]
    if high_ratio >= 0.5:
        overall_quality = "高"
    elif high_ratio + med_ratio >= 0.5:
        overall_quality = "中"
    elif high_ratio + med_ratio >= 0.25:
        overall_quality = "低〜中"
    else:
        overall_quality = "低"

    MIN_MATCHES_FOR_HIGH = 20
    return {
        "success": True,
        "data": {
            "distribution": distribution,
            "total_metrics": total_metrics,
            "overall_quality": overall_quality,
            "min_matches_for_high": MIN_MATCHES_FOR_HIGH,
            "current_match_count": match_count,
        },
        "meta": {"sample_size": total_strokes, "confidence": check_confidence("descriptive_basic", total_strokes)},
    }


# ---------------------------------------------------------------------------
# Research Roadmap R5: Recommendation Ranking (3.7)
# ---------------------------------------------------------------------------

@router.get("/analysis/recommendation_ranking")
def get_recommendation_ranking(
    player_id: int,
    db: Session = Depends(get_db),
):
    """推奨アドバイスランキング — サンプルサイズと効果量に基づく優先度スコア順"""

    matches, role_by_match, sets, set_to_match, rallies, _ = _fetch_matches_sets_rallies(player_id, db)
    if not rallies:
        return {"success": True, "data": {"items": [], "baseline": 0.5},
                "meta": {"sample_size": 0, "confidence": check_confidence("descriptive_basic", 0)}}

    rally_ids = [r.id for r in rallies]
    rally_by_id = {r.id: r for r in rallies}
    strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(rally_ids))
        .all()
    )

    # 選手固有ベースライン（固定 0.5 の代わりに実際の勝率を使用）
    baseline = compute_player_baseline(rallies, role_by_match, set_to_match)

    # ショット種別勝率
    shot_win: dict[str, dict] = defaultdict(lambda: {"count": 0, "wins": 0})
    zone_win: dict[str, dict] = defaultdict(lambda: {"count": 0, "wins": 0})

    rally_to_set = {r.id: r.set_id for r in rallies}
    for s in strokes:
        if not s.shot_type:
            continue
        set_id = rally_to_set.get(s.rally_id)
        mid = set_to_match.get(set_id) if set_id is not None else None
        role = role_by_match.get(mid) if mid else None
        if not role or s.player != role:
            continue
        rally = rally_by_id.get(s.rally_id)
        if not rally:
            continue
        won = 1 if rally.winner == role else 0
        shot_win[s.shot_type]["count"] += 1
        shot_win[s.shot_type]["wins"] += won
        if s.hit_zone:
            zone_win[s.hit_zone]["count"] += 1
            zone_win[s.hit_zone]["wins"] += won

    ZONE_JA = {"BL": "左奥", "BC": "中央奥", "BR": "右奥", "ML": "左中", "MC": "中央", "MR": "右中", "NL": "左前", "NC": "ネット前", "NR": "右前"}

    raw_items = []

    # ショット種別シグナル
    for shot_type, v in shot_win.items():
        label = SHOT_TYPE_JA.get(shot_type, shot_type)
        item = build_recommendation_item(
            category="shot",
            key=shot_type,
            label=label,
            count=v["count"],
            wins=v["wins"],
            baseline=baseline,
            norm_n=AnalysisConfig.RECOMMENDATION_NORM_N,
            min_samples=AnalysisConfig.RECOMMENDATION_MIN_SAMPLES,
        )
        if item:
            raw_items.append(item)

    # ゾーン別シグナル
    for zone, v in zone_win.items():
        zone_name = ZONE_JA.get(zone, zone)
        item = build_recommendation_item(
            category="zone",
            key=zone,
            label=f"{zone_name}エリア",
            count=v["count"],
            wins=v["wins"],
            baseline=baseline,
            norm_n=AnalysisConfig.RECOMMENDATION_NORM_N,
            min_samples=AnalysisConfig.RECOMMENDATION_MIN_SAMPLES,
        )
        if item:
            raw_items.append(item)

    ranked = rank_recommendations(raw_items, top_n=7)

    total = sum(shot_win[k]["count"] for k in shot_win)
    return {
        "success": True,
        "data": {"items": ranked, "baseline": round(baseline, 3)},
        "meta": {"sample_size": total, "confidence": check_confidence("descriptive_basic", total)},
    }


# ---------------------------------------------------------------------------
# Research Roadmap R6: Counterfactual Shots (3.2)
# ---------------------------------------------------------------------------

@router.get("/analysis/counterfactual_shots")
def get_counterfactual_shots(
    player_id: int,
    db: Session = Depends(get_db),
):
    """反事実的ショット比較 — 同じ文脈で異なる返球選択の勝率比較（S3-A: 多次元文脈対応）"""
    return _counterfactual_shots_impl(db, player_id, ctx=None)


def _counterfactual_shots_impl(db: Session, player_id: int, ctx=None):
    """R6 counterfactual_shots impl — ctx があれば rs_* ビューを共有。"""
    if ctx is not None:
        role_by_match = ctx.rs_role_by_match
        set_to_match = ctx.rs_set_to_match
        rallies = ctx.rs_rallies
    else:
        matches, role_by_match, sets, set_to_match, rallies, _ = _fetch_matches_sets_rallies(player_id, db)
    if not rallies:
        return {"success": True, "data": {"comparisons": [], "extended_comparisons": [], "context_summary": {}},
                "meta": {"sample_size": 0, "confidence": check_confidence("descriptive_basic", 0)}}

    if ctx is not None:
        # ctx.rs_strokes_by_rally は順序未保証 → stroke_num で整列して使う
        strokes_by_rally: dict[int, list] = defaultdict(list)
        for rid, lst in ctx.rs_strokes_by_rally.items():
            strokes_by_rally[rid] = sorted(lst, key=lambda s: s.stroke_num)
    else:
        rally_ids = [r.id for r in rallies]
        strokes = (
            db.query(Stroke)
            .filter(Stroke.rally_id.in_(rally_ids))
            .order_by(Stroke.rally_id, Stroke.stroke_num)
            .all()
        )
        strokes_by_rally = defaultdict(list)
        for s in strokes:
            strokes_by_rally[s.rally_id].append(s)

    # S3-A: エンジンに委譲して多次元文脈 + 従来互換の両方を取得
    extended_stats, simple_stats = collect_context_stats(
        rallies, strokes_by_rally, role_by_match, set_to_match,
        use_extended_context=True,
    )

    # 従来互換: simple context (prev_shot のみ) → comparisons
    comparisons = build_comparisons(
        simple_stats,
        shot_labels=SHOT_TYPE_JA,
        min_obs=AnalysisConfig.MIN_OBS_SPATIAL,
        min_lift=0.05,
        top_n=5,
        include_context_features=False,
    )

    # S3-A 拡張: 多次元文脈 → extended_comparisons
    extended_comparisons = build_comparisons(
        extended_stats,
        shot_labels=SHOT_TYPE_JA,
        min_obs=AnalysisConfig.MIN_OBS_SPATIAL,
        min_lift=0.05,
        top_n=5,
        include_context_features=True,
    )

    # 次元別サマリ
    context_summary = summarize_by_dimension(extended_stats)

    total = sum(
        v["count"]
        for resp_map in simple_stats.values()
        for v in resp_map.values()
    )
    return {
        "success": True,
        "data": {
            "comparisons": comparisons,
            "extended_comparisons": extended_comparisons,
            "context_summary": context_summary,
        },
        "meta": {"sample_size": total, "confidence": check_confidence("descriptive_basic", total)},
    }


# ---------------------------------------------------------------------------
# Research Roadmap R7: Spatial Density Map (3.6)
# ---------------------------------------------------------------------------

@router.get("/analysis/spatial_density")
def get_spatial_density(
    player_id: int,
    db: Session = Depends(get_db),
):
    """コート密度ヒートマップ — ゾーン別ストローク数をガウシアンカーネルで連続化"""

    matches, role_by_match, sets, set_to_match, rallies, _ = _fetch_matches_sets_rallies(player_id, db)
    if not rallies:
        empty_grid = [[0.0] * 30 for _ in range(60)]
        return {
            "success": True,
            "data": {"grid": empty_grid, "grid_width": 30, "grid_height": 60, "zone_counts": {}},
            "meta": {"sample_size": 0, "confidence": check_confidence("descriptive_basic", 0)},
        }

    rally_ids = [r.id for r in rallies]
    # カラムを絞って取得（不要な BLOB/JSON を読まない）
    stroke_rows = (
        db.query(Stroke.rally_id, Stroke.player, Stroke.hit_zone, Stroke.land_zone)
        .filter(Stroke.rally_id.in_(rally_ids))
        .all()
    )

    # プレイヤーのストロークのみ（辞書化で O(N) 参照）
    rally_set_map = {r.id: r.set_id for r in rallies}

    GRID_W, GRID_H = 30, 60
    SIGMA = 4.0

    # ゾーン → グリッドセントロイド (col, row) マッピング (30×60グリッド)
    # コート: 横30, 縦60。近端=下(row高い), 遠端=上(row低い)
    ZONE_CENTROIDS = {
        "BL": (5,  10), "BC": (15, 10), "BR": (25, 10),
        "ML": (5,  30), "MC": (15, 30), "MR": (25, 30),
        "NL": (5,  50), "NC": (15, 50), "NR": (25, 50),
    }

    # ゾーンカウント
    zone_counts: dict[str, int] = defaultdict(int)
    player_stroke_total = 0

    for rally_id, s_player, hit_zone, land_zone in stroke_rows:
        mid = set_to_match.get(rally_set_map.get(rally_id, -1), -1)
        role = role_by_match.get(mid)
        if not role or s_player != role:
            continue
        player_stroke_total += 1
        zone = hit_zone or land_zone
        if not zone or zone not in ZONE_CENTROIDS:
            continue
        zone_counts[zone] += 1

    # numpy でガウシアンカーネル計算 (ゾーン単位でまとめて加算)
    try:
        import numpy as _np

        cols = _np.arange(GRID_W, dtype=_np.float32)
        rows = _np.arange(GRID_H, dtype=_np.float32)
        col_grid, row_grid = _np.meshgrid(cols, rows)
        grid_np = _np.zeros((GRID_H, GRID_W), dtype=_np.float32)
        two_sigma2 = 2.0 * SIGMA * SIGMA
        for zone_name, count in zone_counts.items():
            if count <= 0:
                continue
            cx, cy = ZONE_CENTROIDS[zone_name]
            dist2 = (col_grid - cx) ** 2 + (row_grid - cy) ** 2
            grid_np += count * _np.exp(-dist2 / two_sigma2)
        max_val = float(grid_np.max()) if grid_np.size else 0.0
        if max_val > 0:
            grid_np = _np.round(grid_np / max_val, 4)
        grid = grid_np.tolist()
    except Exception:
        # フォールバック: 既存の純 Python 実装
        grid = [[0.0] * GRID_W for _ in range(GRID_H)]
        for zone_name, count in zone_counts.items():
            if count <= 0:
                continue
            cx, cy = ZONE_CENTROIDS[zone_name]
            for row in range(GRID_H):
                for col in range(GRID_W):
                    dist2 = (col - cx) ** 2 + (row - cy) ** 2
                    grid[row][col] += count * math.exp(-dist2 / (2 * SIGMA * SIGMA))
        max_val = max(max(row) for row in grid) if any(any(row) for row in grid) else 1.0
        if max_val > 0:
            grid = [[round(v / max_val, 4) for v in row] for row in grid]

    total = player_stroke_total
    return {
        "success": True,
        "data": {
            "grid": grid,
            "grid_width": GRID_W,
            "grid_height": GRID_H,
            "zone_counts": dict(zone_counts),
        },
        "meta": {"sample_size": total, "confidence": check_confidence("descriptive_basic", total)},
    }


# ─── Phase 2: ダブルスペア両選手監視 ─────────────────────────────────────────

@router.get("/analysis/pair_combined")
def get_pair_combined(
    player_a_id: int,
    player_b_id: int,
    result: Optional[str] = None,
    tournament_level: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """ペア両選手が同一ダブルス試合に出場したラリーの合算解析。"""

    from collections import Counter

    # 両選手が出場したダブルス試合を抽出
    q = db.query(Match).filter(
        Match.format != "singles",
        or_(
            and_(Match.player_a_id == player_a_id, Match.player_b_id == player_b_id),
            and_(Match.player_a_id == player_b_id, Match.player_b_id == player_a_id),
            and_(Match.player_a_id == player_a_id, Match.partner_a_id == player_b_id),
            and_(Match.player_a_id == player_b_id, Match.partner_a_id == player_a_id),
            and_(Match.player_b_id == player_a_id, Match.partner_b_id == player_b_id),
            and_(Match.player_b_id == player_b_id, Match.partner_b_id == player_a_id),
        ),
    )
    if result:
        q = q.filter(Match.result == result)
    if tournament_level:
        q = q.filter(Match.tournament_level == tournament_level)
    if date_from:
        q = q.filter(Match.date >= date_from)
    if date_to:
        q = q.filter(Match.date <= date_to)

    matches = q.order_by(Match.date).all()
    if not matches:
        confidence = check_confidence("descriptive_basic", 0)
        return {"success": True, "data": {
            "pair_win_rate": None, "pair_match_count": 0, "shared_matches": [],
            "stroke_share": {"player_a": 0.5, "player_b": 0.5},
            "common_loss_pattern": None, "common_win_shot": None,
        }, "meta": {"sample_size": 0, "confidence": confidence}}

    shared_match_ids = [m.id for m in matches]
    set_ids_all = [
        s.id for s in db.query(GameSet).filter(GameSet.match_id.in_(shared_match_ids)).all()
    ]
    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids_all)).all() if set_ids_all else []
    all_strokes = (
        db.query(Stroke).filter(Stroke.rally_id.in_([r.id for r in rallies])).all()
        if rallies else []
    )

    # ペア勝率 (player_a_id 視点)
    pair_wins = 0
    for m in matches:
        if m.player_a_id == player_a_id or m.partner_a_id == player_a_id:
            if m.result == "win":
                pair_wins += 1
        else:
            if m.result == "loss":
                pair_wins += 1
    pair_win_rate = round(pair_wins / len(matches), 3) if matches else None

    # ストローク分担比率
    strokes_a = sum(
        1 for s in all_strokes
        if s.player in ("player_a",) and any(
            (m.player_a_id == player_a_id or m.partner_a_id == player_a_id)
            for m in matches
            if m.id == next((
                r.set_id for r in rallies if r.id == s.rally_id
            ), None)
        )
    )
    total_strokes = len(all_strokes)
    # シンプルに player ロール別カウント
    cnt_a_role = sum(1 for s in all_strokes if s.player == "player_a")
    cnt_b_role = sum(1 for s in all_strokes if s.player == "player_b")
    cnt_total = cnt_a_role + cnt_b_role or 1
    stroke_share = {
        "player_a": round(cnt_a_role / cnt_total, 3),
        "player_b": round(cnt_b_role / cnt_total, 3),
    }

    # 共通の失点前ショット
    rally_id_set = {r.id for r in rallies}
    # N+1 解消: set_id → match_id のマップを一度だけ構築し、matches も辞書化
    matches_by_id = {m.id: m for m in matches}
    sets_for_lookup = db.query(GameSet).filter(GameSet.match_id.in_(shared_match_ids)).all() if shared_match_ids else []
    set_to_match_id = {s.id: s.match_id for s in sets_for_lookup}
    win_rally_ids: set[int] = set()
    loss_rally_ids: set[int] = set()
    for r in rallies:
        mid = set_to_match_id.get(r.set_id)
        m = matches_by_id.get(mid) if mid is not None else None
        if m is None:
            continue
        player_role = "player_a" if (m.player_a_id == player_a_id or m.partner_a_id == player_a_id) else "player_b"
        if r.winner == player_role:
            win_rally_ids.add(r.id)
        else:
            loss_rally_ids.add(r.id)

    common_win_shot = None
    win_shots = [s.shot_type for s in all_strokes if s.rally_id in win_rally_ids and s.shot_type]
    if win_shots:
        common_win_shot = Counter(win_shots).most_common(1)[0][0]

    common_loss_pattern = None
    loss_shots = [s.shot_type for s in all_strokes if s.rally_id in loss_rally_ids and s.shot_type]
    if loss_shots:
        common_loss_pattern = Counter(loss_shots).most_common(1)[0][0]

    confidence = check_confidence("descriptive_basic", len(rallies))
    return {
        "success": True,
        "data": {
            "pair_win_rate": pair_win_rate,
            "pair_match_count": len(matches),
            "shared_matches": shared_match_ids,
            "stroke_share": stroke_share,
            "common_loss_pattern": common_loss_pattern,
            "common_win_shot": common_win_shot,
        },
        "meta": {"sample_size": len(rallies), "confidence": confidence},
    }


@router.get("/analysis/partner_timeline")
def get_partner_timeline(
    player_id: int,
    partner_id: int,
    db: Session = Depends(get_db),
):
    """ペア別試合ごとの勝率推移。"""

    q = db.query(Match).filter(
        Match.format != "singles",
        or_(
            and_(Match.player_a_id == player_id, Match.player_b_id == partner_id),
            and_(Match.player_a_id == partner_id, Match.player_b_id == player_id),
            and_(Match.player_a_id == player_id, Match.partner_a_id == partner_id),
            and_(Match.player_a_id == partner_id, Match.partner_a_id == player_id),
            and_(Match.player_b_id == player_id, Match.partner_b_id == partner_id),
            and_(Match.player_b_id == partner_id, Match.partner_b_id == player_id),
        ),
    ).order_by(Match.date)
    matches = q.all()

    if not matches:
        return {"success": True, "data": {"points": [], "overall_win_rate": None},
                "meta": {"sample_size": 0, "confidence": check_confidence("descriptive_basic", 0)}}

    points = []
    win_count = 0
    for i, m in enumerate(matches):
        is_a_side = m.player_a_id == player_id or m.partner_a_id == player_id
        won = (m.result == "win" and is_a_side) or (m.result == "loss" and not is_a_side)
        if won:
            win_count += 1
        points.append({
            "match_id": m.id,
            "date": str(m.date),
            "result": "win" if won else "loss",
            "cumulative_win_rate": round(win_count / (i + 1), 3),
            "tournament": m.tournament,
        })

    overall_win_rate = round(win_count / len(matches), 3)
    confidence = check_confidence("descriptive_basic", len(matches))
    return {
        "success": True,
        "data": {"points": points, "overall_win_rate": overall_win_rate},
        "meta": {"sample_size": len(matches), "confidence": confidence},
    }


# ─── Phase 3: 相手タイプ別相性 ────────────────────────────────────────────────

@router.get("/analysis/opponent_type_affinity")
def get_opponent_type_affinity(
    player_id: int,
    result: Optional[str] = None,
    tournament_level: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """相手プレイヤータイプ別（攻撃型/守備型/バランス型）の勝率を返す。

    相手タイプ判定ロジック:
    - 平均ラリー長 < 6 かつ スマッシュ率 >= 30% → 攻撃型
    - 平均ラリー長 >= 10 → 守備型
    - それ以外 → バランス型
    """
    from collections import defaultdict

    q = db.query(Match).filter(
        (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
    )
    if result:
        q = q.filter(Match.result == result)
    if tournament_level:
        q = q.filter(Match.tournament_level == tournament_level)
    if date_from:
        q = q.filter(Match.date >= date_from)
    if date_to:
        q = q.filter(Match.date <= date_to)
    matches = q.all()

    if not matches:
        confidence = check_confidence("descriptive_basic", 0)
        return {"success": True, "data": {"affinity": {}, "summary": [], "axes": {}},
                "meta": {"sample_size": 0, "confidence": confidence}}

    # 5軸分類（classify_all_opponents で全相手を一括分類）
    classified = classify_all_opponents(db, player_id, matches)

    # ── style 軸（後方互換: 従来の affinity / summary を維持）────────────────
    type_stats: dict[str, dict] = {
        "攻撃型":     {"wins": 0, "total": 0},
        "守備型":     {"wins": 0, "total": 0},
        "バランス型": {"wins": 0, "total": 0},
    }
    for m in matches:
        opp_id = m.player_b_id if m.player_a_id == player_id else m.player_a_id
        cls = classified.get(opp_id)
        if cls is None:
            continue
        opp_type = cls["axes"]["style"]
        player_role = "player_a" if m.player_a_id == player_id else "player_b"
        won = (player_role == "player_a" and m.result == "win") or \
              (player_role == "player_b" and m.result == "loss")
        if opp_type in type_stats:
            type_stats[opp_type]["total"] += 1
            if won:
                type_stats[opp_type]["wins"] += 1

    affinity = {}
    summary = []
    for opp_type, stats in type_stats.items():
        total = stats["total"]
        if total == 0:
            continue
        win_rate = round(stats["wins"] / total, 3)
        affinity[opp_type] = {"win_rate": win_rate, "match_count": total, "wins": stats["wins"]}
        summary.append({"opponent_type": opp_type, "win_rate": win_rate, "match_count": total, "wins": stats["wins"]})
    summary.sort(key=lambda x: x["win_rate"], reverse=True)

    # ── 5軸別集計（axes フィールドとして追加）────────────────────────────────
    axes: dict[str, list] = {}
    for axis in ("style", "pace", "rally_length", "handedness", "court_zone"):
        axes[axis] = aggregate_affinity_by_axis(axis, classified, matches, player_id)

    sample_size = sum(s["total"] for s in type_stats.values())
    confidence = check_confidence("descriptive_basic", sample_size)
    return {
        "success": True,
        "data": {"affinity": affinity, "summary": summary, "axes": axes},
        "meta": {"sample_size": sample_size, "confidence": confidence},
    }


# ─── Phase 3: ペア別プレースタイル分類 ──────────────────────────────────────

@router.get("/analysis/pair_playstyle")
def get_pair_playstyle(
    player_a_id: int,
    player_b_id: int,
    db: Session = Depends(get_db),
):
    """ペア別プレースタイル分類（前衛主体/後衛主体/バランス型）を返す。

    判定ロジック:
    - ネット前ゾーン（NL/NC/NR）への配球が40%以上 → 前衛主体
    - 奥ゾーン（BL/BC/BR）への配球が40%以上 → 後衛主体
    - それ以外 → バランス型
    """
    from collections import Counter

    # 両選手が出場したダブルス試合
    q = db.query(Match).filter(
        Match.format != "singles",
        or_(
            and_(Match.player_a_id == player_a_id, Match.player_b_id == player_b_id),
            and_(Match.player_a_id == player_b_id, Match.player_b_id == player_a_id),
            and_(Match.player_a_id == player_a_id, Match.partner_a_id == player_b_id),
            and_(Match.player_a_id == player_b_id, Match.partner_a_id == player_a_id),
            and_(Match.player_b_id == player_a_id, Match.partner_b_id == player_b_id),
            and_(Match.player_b_id == player_b_id, Match.partner_b_id == player_a_id),
        ),
    )
    matches = q.all()

    if not matches:
        confidence = check_confidence("descriptive_basic", 0)
        return {"success": True, "data": {
            "playstyle": "不明", "playstyle_en": "unknown",
            "zone_distribution": {}, "metrics": {},
        }, "meta": {"sample_size": 0, "confidence": confidence}}

    match_ids = [m.id for m in matches]
    set_ids = [
        s.id for s in db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    ]
    rally_ids = [
        r.id for r in (db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else [])
    ]
    strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(rally_ids), Stroke.land_zone != None)
        .all()
        if rally_ids else []
    )

    total_strokes = len(strokes)
    if total_strokes == 0:
        confidence = check_confidence("descriptive_basic", 0)
        return {"success": True, "data": {
            "playstyle": "不明", "playstyle_en": "unknown",
            "zone_distribution": {}, "metrics": {},
        }, "meta": {"sample_size": 0, "confidence": confidence}}

    zone_counts = Counter(s.land_zone for s in strokes if s.land_zone)
    zone_dist = {z: round(cnt / total_strokes, 3) for z, cnt in zone_counts.items()}

    net_rate = sum(zone_dist.get(z, 0) for z in ("NL", "NC", "NR"))
    back_rate = sum(zone_dist.get(z, 0) for z in ("BL", "BC", "BR"))
    mid_rate = sum(zone_dist.get(z, 0) for z in ("ML", "MC", "MR"))

    # ショット種別比率
    shot_counts = Counter(s.shot_type for s in strokes if s.shot_type)
    shot_total = sum(shot_counts.values()) or 1
    smash_rate = round(shot_counts.get("smash", 0) / shot_total, 3)
    net_shot_rate = round((shot_counts.get("net_shot", 0) + shot_counts.get("hair_pin", 0)) / shot_total, 3)

    # プレースタイル判定
    if net_rate >= 0.40:
        playstyle = "前衛主体"
        playstyle_en = "net_dominant"
    elif back_rate >= 0.40:
        playstyle = "後衛主体"
        playstyle_en = "back_dominant"
    else:
        playstyle = "バランス型"
        playstyle_en = "balanced"

    metrics = {
        "net_zone_rate":   round(net_rate, 3),
        "back_zone_rate":  round(back_rate, 3),
        "mid_zone_rate":   round(mid_rate, 3),
        "smash_rate":      smash_rate,
        "net_shot_rate":   net_shot_rate,
        "match_count":     len(matches),
    }

    confidence = check_confidence("descriptive_basic", total_strokes)
    return {
        "success": True,
        "data": {
            "playstyle": playstyle,
            "playstyle_en": playstyle_en,
            "zone_distribution": zone_dist,
            "metrics": metrics,
        },
        "meta": {"sample_size": total_strokes, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# Research Roadmap R1: Opponent-Adaptive Shots (3.3)
# ---------------------------------------------------------------------------

@router.get("/analysis/opponent_adaptive_shots")
def get_opponent_adaptive_shots(
    player_id: int,
    db: Session = Depends(get_db),
):
    """対戦相手別ショット有効性 — 各対戦相手に対するショット種別勝率"""
    matches = (
        db.query(Match)
        .filter((Match.player_a_id == player_id) | (Match.player_b_id == player_id))
        .all()
    )
    if not matches:
        return {"success": True, "data": {"global_shot_winrates": {}, "opponents": []},
                "meta": {"sample_size": 0, "confidence": check_confidence("descriptive_basic", 0)}}

    # ラリーIDとロールのマッピング
    match_ids = [m.id for m in matches]
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in matches}
    # O(N*M) 解消: ストロークループ内の線形検索を潰すため matches を辞書化
    matches_by_id = {m.id: m for m in matches}

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids), Rally.is_skipped == False).all()  # noqa: E712
    rally_ids = [r.id for r in rallies]
    rally_by_id = {r.id: r for r in rallies}
    set_by_id = {s.id: s for s in sets}

    strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(rally_ids))
        .order_by(Stroke.rally_id, Stroke.stroke_num)
        .all()
    )

    # ショット別グローバル勝率
    global_counts: dict[str, int] = defaultdict(int)
    global_wins: dict[str, int] = defaultdict(int)

    # 対戦相手IDごと: {opp_id: {shot_type: {"count": N, "wins": N}}}
    opp_shot: dict[int, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"count": 0, "wins": 0}))
    opp_match_ids: dict[int, set] = defaultdict(set)

    for s in strokes:
        rally = rally_by_id.get(s.rally_id)
        if not rally or not s.shot_type:
            continue
        mid = set_to_match.get(rally.set_id)
        if not mid:
            continue
        role = role_by_match.get(mid)
        if not role:
            continue
        # このストロークはプレイヤーが打ったか
        if s.player != role:
            continue

        match = matches_by_id.get(mid)  # O(1) 辞書引き
        if not match:
            continue

        # 対戦相手ID
        opp_id = match.player_b_id if match.player_a_id == player_id else match.player_a_id
        won = 1 if rally.winner == role else 0

        global_counts[s.shot_type] += 1
        global_wins[s.shot_type] += won
        opp_shot[opp_id][s.shot_type]["count"] += 1
        opp_shot[opp_id][s.shot_type]["wins"] += won
        opp_match_ids[opp_id].add(mid)

    # グローバル勝率
    global_winrates = {
        st: round(global_wins[st] / global_counts[st], 3)
        for st in global_counts if global_counts[st] > 0
    }

    # 対戦相手リスト（試合数上位順）
    opp_players = {p.id: p for p in db.query(Player).filter(Player.id.in_(list(opp_shot.keys()))).all()}

    opponents = []
    for opp_id, shot_data in sorted(opp_shot.items(), key=lambda x: -len(opp_match_ids[x[0]])):
        opp = opp_players.get(opp_id)
        effectiveness = []
        for shot_type, vals in shot_data.items():
            if vals["count"] < 3:
                continue
            wr = round(vals["wins"] / vals["count"], 3)
            global_wr = global_winrates.get(shot_type, 0.5)
            effectiveness.append({
                "shot_type": shot_type,
                "shot_label": SHOT_TYPE_JA.get(shot_type, shot_type),
                "count": vals["count"],
                "win_rate": wr,
                "lift": round(wr - global_wr, 3),
            })
        effectiveness.sort(key=lambda x: -x["count"])
        opponents.append({
            "opponent_id": opp_id,
            "opponent_name": opp.name if opp else str(opp_id),
            "match_count": len(opp_match_ids[opp_id]),
            "shot_effectiveness": effectiveness,
        })

    total = sum(global_counts.values())
    return {
        "success": True,
        "data": {"global_shot_winrates": global_winrates, "opponents": opponents},
        "meta": {"sample_size": total, "confidence": check_confidence("descriptive_basic", total)},
    }


# ---------------------------------------------------------------------------
# Research Roadmap R2: Pair Synergy (3.4)
# ---------------------------------------------------------------------------

@router.get("/analysis/pair_synergy")
def get_pair_synergy(
    player_id: int,
    db: Session = Depends(get_db),
):
    """ペアシナジースコア — ダブルスペアごとの相性指標"""
    # 全試合（シングルス含む）でプレイヤー勝率を計算
    all_matches = (
        db.query(Match)
        .filter((Match.player_a_id == player_id) | (Match.player_b_id == player_id))
        .all()
    )
    if not all_matches:
        return {"success": True, "data": {"player_avg_win_rate": 0.0, "pairs": []},
                "meta": {"sample_size": 0, "confidence": check_confidence("descriptive_basic", 0)}}

    total_matches = len(all_matches)
    win_count = sum(
        1 for m in all_matches
        if (m.player_a_id == player_id and m.result == "win")
        or (m.player_b_id == player_id and m.result == "loss")
    )
    player_avg_win_rate = round(win_count / total_matches, 3) if total_matches > 0 else 0.0

    # ダブルス試合のみ抽出
    doubles_matches = [m for m in all_matches if m.format in ("womens_doubles", "mixed_doubles", "mens_doubles")]
    if not doubles_matches:
        return {
            "success": True,
            "data": {"player_avg_win_rate": player_avg_win_rate, "pairs": []},
            "meta": {"sample_size": total_matches, "confidence": check_confidence("descriptive_basic", total_matches)},
        }

    # ペアIDごとに集計
    pair_data: dict[int, dict] = defaultdict(lambda: {
        "match_ids": [], "wins": 0, "total_rally_length": 0, "rally_count": 0,
        "player_strokes": 0, "total_strokes": 0,
    })

    match_ids = [m.id for m in doubles_matches]
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]
    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids), Rally.is_skipped == False).all()  # noqa: E712
    rally_ids = [r.id for r in rallies]

    strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(rally_ids))
        .all()
    )
    strokes_by_rally: dict[int, list] = defaultdict(list)
    for s in strokes:
        strokes_by_rally[s.rally_id].append(s)

    for m in doubles_matches:
        role = _player_role_in_match(m, player_id)
        if not role:
            continue
        partner_id = m.partner_a_id if role == "player_a" else m.partner_b_id
        if not partner_id:
            continue

        is_win = (role == "player_a" and m.result == "win") or (role == "player_b" and m.result == "loss")
        pair_data[partner_id]["match_ids"].append(m.id)
        if is_win:
            pair_data[partner_id]["wins"] += 1

        # このマッチのラリーでストローク統計を収集
        match_set_ids = {s.id for s in sets if s.match_id == m.id}
        for rally in rallies:
            if set_to_match.get(rally.set_id) != m.id:
                continue
            pair_data[partner_id]["total_rally_length"] += rally.rally_length
            pair_data[partner_id]["rally_count"] += 1
            for st in strokes_by_rally[rally.id]:
                pair_data[partner_id]["total_strokes"] += 1
                if st.player == role:
                    pair_data[partner_id]["player_strokes"] += 1

    # パートナー名を取得
    partner_players = {p.id: p for p in db.query(Player).filter(Player.id.in_(list(pair_data.keys()))).all()}

    pairs = []
    for partner_id, pd in sorted(pair_data.items(), key=lambda x: -len(x[1]["match_ids"])):
        mc = len(pd["match_ids"])
        if mc == 0:
            continue
        wr = round(pd["wins"] / mc, 3)
        synergy = round(wr - player_avg_win_rate, 3)
        avg_rally = round(pd["total_rally_length"] / pd["rally_count"], 2) if pd["rally_count"] > 0 else 0.0
        stroke_share = round(pd["player_strokes"] / pd["total_strokes"], 3) if pd["total_strokes"] > 0 else 0.0
        partner = partner_players.get(partner_id)
        pairs.append({
            "partner_id": partner_id,
            "partner_name": partner.name if partner else str(partner_id),
            "match_count": mc,
            "win_rate": wr,
            "synergy_score": synergy,
            "avg_rally_length": avg_rally,
            "stroke_share": stroke_share,
        })

    pairs.sort(key=lambda x: -x["synergy_score"])

    return {
        "success": True,
        "data": {"player_avg_win_rate": player_avg_win_rate, "pairs": pairs},
        "meta": {"sample_size": total_matches, "confidence": check_confidence("descriptive_basic", total_matches)},
    }


# ---------------------------------------------------------------------------
# Meta: 解析 tier 分類エンドポイント
# ---------------------------------------------------------------------------

@router.get("/analysis/meta/tiers")
def get_analysis_tiers():
    """
    解析種別の stable / advanced / research 分類を返す。
    フロントエンドがこれを使い、デフォルト表示範囲・confidence 要件を制御する。
    """
    return {"success": True, "data": all_tiers_meta()}
