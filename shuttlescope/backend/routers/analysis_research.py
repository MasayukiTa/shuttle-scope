"""analysis_research.py — research tier 解析エンドポイント"""
import logging
import math

logger = logging.getLogger(__name__)
from collections import defaultdict, Counter
from datetime import date as DateType
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.analysis.role_view import own_slot, team_side, perspective
from backend.analysis.player_context import (
    involves_player, opponent_player_id, player_wins_match, partner_player_id, player_result_filter,
)
from backend.analysis.match_filter import (
    MatchFilter, match_filter_params, select_population, stamps_population, declare_filter_scope,
)
from backend.utils.auth import (
    require_admin_or_analyst, require_query_scope, get_auth, apply_match_team_scope, AuthCtx,
)
from backend.db.models import Match, GameSet, Rally, Stroke, Player, PreMatchObservation
from backend.utils.confidence import check_confidence, VERDICT_MIN_SAMPLE, wilson_ci
from backend.analysis.router_helpers import (
    SHOT_TYPE_JA, SHOT_KEYS, SHOT_LABELS_JA, END_TYPE_JA, _shot_ja,
    _player_role_in_match, _get_player_matches, _fetch_matches_sets_rallies,
    validate_date_range,
)
from backend.analysis.analysis_config import AnalysisConfig
from backend.analysis.analysis_registry import get_analysis_meta
from backend.analysis.response_meta import build_input_provenance
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
    UNCLASSIFIED,
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
from backend.analysis.exploitability_engine import analyze_state as _exploitability_analyze_state
from backend.analysis.exploitability_loader import load_exploitability_records
from backend.analysis.conformal_engine import (
    fit_group_winrates,
    predict_p_win,
    split_conformal,
    prediction_set as _conformal_prediction_set,
    evaluate_coverage,
)
from backend.analysis.conformal_loader import load_rally_outcome_samples
# ② DR-OPE / ④ 最適輸送 / ③ 階層ベイズ
from backend.analysis.dr_ope_engine import evaluate_state as _dr_evaluate_state
from backend.analysis.dr_ope_loader import load_policy_records
from backend.analysis.optimal_transport_engine import (
    pairwise_distance_matrix as _ot_pairwise,
    classical_mds as _ot_mds,
)
from backend.analysis.optimal_transport_loader import (
    load_zone_histograms,
    build_cost_matrix as _ot_build_cost_matrix,
    ZONE_LABELS as _OT_ZONE_LABELS,
)
from backend.analysis.hier_bayes_engine import fit_bradley_terry, predict_matchup
from backend.analysis.hier_bayes_loader import load_match_pairs

# research tier は admin/analyst のみ。middleware (_PLAYER_FORBIDDEN_ANALYSIS_PATHS) は
# import 失敗時に silent に空集合化するため、router-level dependency でも明示ガードする。
router = APIRouter(dependencies=[Depends(require_admin_or_analyst), Depends(require_query_scope)])


def _research_confidence(analysis_type: str, sample_size: int, **kwargs) -> dict:
    """このルータの解析はすべて research tier。信頼度は check_confidence の 1 関数で決め、
    標本数が多くても「高信頼（実用レベル）」は付けない。unit_n / interval_width は
    表示単位 (ペア・対戦相手・対戦) ごとの値を渡す。"""
    return check_confidence(analysis_type, sample_size, tier="research", **kwargs)


def _median_n(values: list[int], fallback: int) -> int:
    """表示単位ごとの n の中央値 (小さい側)。単位が無ければ fallback。"""
    if not values:
        return fallback
    ordered = sorted(values)
    return ordered[(len(ordered) - 1) // 2]


def _with_input_provenance(
    meta: dict,
    *,
    rallies: list | tuple | None = None,
    strokes: list | tuple | None = None,
    strokes_by_rally: dict | None = None,
    uses_hit_zone: bool = False,
) -> dict:
    """Attach declared sample unit and provenance for analysis responses."""
    enriched = dict(meta)
    analysis_type = enriched.get("analysis_type")
    if analysis_type and "sample_unit" not in enriched:
        enriched["sample_unit"] = get_analysis_meta(str(analysis_type)).get("sample_unit")

    if rallies is None and strokes is None and strokes_by_rally is None:
        return enriched

    enriched["input_provenance"] = build_input_provenance(
        rallies=rallies or [],
        strokes_by_rally=strokes_by_rally or {},
        strokes=strokes,
        uses_hit_zone=uses_hit_zone,
    )
    return enriched

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


def _epv_registry_meta() -> dict:
    """registry の caution / assumptions を meta に載せる。

    D-5: `/analysis/epv` は meta を手で組み立てており、
    `build_response_meta` を通していなかったので **registry の caution が
    エンドポイントの返り値に一度も入っていなかった**。
    描く側 (MarkovEPV) が受け取れないので、注意書きは存在しないのと同じだった。

    EPV の大きさは `epv_engine._SHOT_ATTACK_WEIGHT` という **手置きの定数表**で
    決まる。それを伏せたまま数値を出すのは、このリポジトリの
    「不確実性を必ず開示する」規約に反する。
    """
    from backend.analysis.analysis_registry import get_analysis_meta
    entry = get_analysis_meta("epv")
    return {
        "tier": entry["tier"],
        "evidence_level": entry["evidence_level"],
        "caution": entry["caution"],
        "assumptions": entry["assumptions"],
    }


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

    empty_confidence = _research_confidence("shot_transition", 0)
    if not matches:
        return {
            "success": True,
            "data": {"top_patterns": [], "bottom_patterns": []},
            "meta": _with_input_provenance(
                {"sample_size": 0, "confidence": empty_confidence, **_epv_registry_meta()},
                rallies=[],
                strokes_by_rally={},
            ),
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
            "meta": _with_input_provenance(
                {"sample_size": 0, "confidence": empty_confidence, **_epv_registry_meta()},
                rallies=rallies,
                strokes_by_rally={},
            ),
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
        player_strokes = [s for s in stks if s.player == own_slot(role)]
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

    confidence = _research_confidence("shot_transition", total_strokes)

    return {
        "success": True,
        "data": {
            "top_patterns": top_patterns,
            "bottom_patterns": bottom_patterns,
            "state_epv": state_epv_result.get("state_epv", {}),
            "global_epv": state_epv_result.get("global_epv", {}),
            "state_summary": state_epv_result.get("state_summary", {}),
        },
        "meta": _with_input_provenance(
            {"sample_size": total_strokes, "confidence": confidence, **_epv_registry_meta()},
            rallies=rallies,
            strokes_by_rally=strokes_by_rally,
        ),
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
            "meta": _with_input_provenance(
                {"sample_size": 0, "confidence": _research_confidence("shot_transition", 0)},
                rallies=rallies,
                strokes=[],
            ),
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
    confidence = _research_confidence("shot_transition", total_strokes)

    return {
        "success": True,
        "data": {
            "rallies": all_rally_data,
            "shot_type_summary": shot_type_summary,
            "shot_type_state_summary": shot_type_state_summary,
        },
        "meta": _with_input_provenance(
            {"sample_size": total_strokes, "confidence": confidence},
            rallies=rallies,
            strokes=all_strokes,
        ),
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
    provenance_rows: dict[str, list] = {"rallies": []}
    try:
        result = analyzer.generate_interval_report(
            match_id,
            completed_set_num,
            db,
            provenance_rows=provenance_rows,
        )
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
    confidence = _research_confidence("descriptive_basic", total_rallies)

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
        "meta": _with_input_provenance(
            {"sample_size": total_rallies, "confidence": confidence},
            rallies=list({r.id: r for r in provenance_rows["rallies"]}.values()),
        ),
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
    """絞り込みを使わない解析 (registry: global_only)。応答の meta にそれを書く。
    単体エンドポイントとバンドルが同じ応答を返すよう、書き込みはここで 1 回だけ行う。"""
    resp = _rally_sequence_patterns_core(db, player_id, ctx)
    declare_filter_scope(resp["meta"], "rally_sequence_patterns")
    return resp


def _rally_sequence_patterns_core(db: Session, player_id: int, ctx=None):
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
                "meta": _with_input_provenance(
                    {"sample_size": 0, "confidence": _research_confidence("descriptive_basic", 0)},
                    rallies=[],
                    strokes=[],
                )}

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
    # count / wins の単位は「そのパターンを含むラリー数」。同じラリーの中で同じ並びが
    # 何度出ても 1 回と数える (長いラリーが 1 本で件数と勝率を水増ししないため。監査 #40)。
    trigram_stats: dict[tuple, dict] = defaultdict(lambda: {"count": 0, "wins": 0})
    eligible_rallies = 0  # 自分の打球が 3 球以上あり、パターンを取り出せたラリー
    eligible_wins = 0

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
        player_shots = [s.shot_type for s in rally_strokes if s.player == own_slot(role) and s.shot_type]
        # 3連続パターン (ラリー内で重複する並びは 1 回だけ数える)
        keys_in_rally = {
            (player_shots[i], player_shots[i + 1], player_shots[i + 2])
            for i in range(len(player_shots) - 2)
        }
        if keys_in_rally:
            eligible_rallies += 1
            if is_win:
                eligible_wins += 1
        for key in keys_in_rally:
            trigram_stats[key]["count"] += 1
            if is_win:
                trigram_stats[key]["wins"] += 1

    # 最低5回以上出現のパターンのみ
    MIN_COUNT = AnalysisConfig.MIN_SEQUENCES_PATTERN
    filtered = {k: v for k, v in trigram_stats.items() if v["count"] >= MIN_COUNT}

    def to_entry(key, vals):
        wr = round(vals["wins"] / vals["count"], 3)
        ci_low, ci_high = wilson_ci(vals["wins"], vals["count"])
        return {
            "sequence": list(key),
            "labels": [SHOT_TYPE_JA.get(t, t) for t in key],
            # count = そのパターンを含むラリー数 (打球数ではない)。win_rate = そのうち自分が取ったラリーの割合
            "count": vals["count"],
            "win_rate": wr,
            "win_count": vals["wins"],
            "ci_low": ci_low,
            "ci_high": ci_high,
        }

    entries = [to_entry(k, v) for k, v in filtered.items()]
    # 並び順は点推定でなく区間で決める。勝ち側は下限が高い順、負け側は上限が低い順。
    # 100% でも件数が少なければ下限が低く、上位に来ない。
    win_seqs = sorted([e for e in entries if e["win_rate"] >= 0.5], key=lambda x: (-x["ci_low"], -x["count"]))[:8]
    loss_seqs = sorted([e for e in entries if e["win_rate"] < 0.5], key=lambda x: (x["ci_high"], -x["count"]))[:8]
    # 比較の基準: パターンを取り出せたラリー全体の勝率。基準そのものが極端なら
    # 個々のパターンの勝率は差を表さないので、画面で並べて見せる。
    baseline_win_rate = round(eligible_wins / eligible_rallies, 3) if eligible_rallies > 0 else None

    total_rallies = len(rallies)
    total_strokes = sum(len(v) for v in strokes_by_rally.values())
    return {
        "success": True,
        "data": {
            "win_sequences": win_seqs,
            "loss_sequences": loss_seqs,
            "total_rallies": total_rallies,
            "eligible_rallies": eligible_rallies,
            "baseline_win_rate": baseline_win_rate,
        },
        "meta": _with_input_provenance(
            {"sample_size": total_strokes, "confidence": _research_confidence("descriptive_basic", total_strokes)},
            rallies=rallies,
            strokes=strokes,
        ),
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
        "meta": _with_input_provenance(
            {"sample_size": total_strokes, "confidence": _research_confidence("descriptive_basic", total_strokes)},
            rallies=rallies,
            strokes=strokes,
        ),
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
                "meta": _with_input_provenance(
                    {"sample_size": 0, "confidence": _research_confidence("descriptive_basic", 0)},
                    rallies=[],
                    strokes=[],
                )}

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
        if not role or s.player != own_slot(role):
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
        "meta": _with_input_provenance(
            {"sample_size": total, "confidence": _research_confidence("descriptive_basic", total)},
            rallies=rallies,
            strokes=strokes,
            uses_hit_zone=True,
        ),
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
                "meta": _with_input_provenance(
                    {"sample_size": 0, "confidence": _research_confidence("descriptive_basic", 0)},
                    rallies=[],
                    strokes_by_rally={},
                )}

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
        "meta": _with_input_provenance(
            {"sample_size": total, "confidence": _research_confidence("descriptive_basic", total)},
            rallies=rallies,
            strokes_by_rally=strokes_by_rally,
        ),
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
            "meta": _with_input_provenance(
                {"sample_size": 0, "confidence": _research_confidence("descriptive_basic", 0)},
                rallies=[],
                strokes=[],
            ),
        }

    rally_ids = [r.id for r in rallies]
    # カラムを絞って取得（不要な BLOB/JSON を読まない）
    stroke_rows = (
        db.query(
            Stroke.rally_id,
            Stroke.player,
            Stroke.hit_zone,
            Stroke.land_zone,
            Stroke.source_method,
            Stroke.hit_zone_source,
        )
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
    used_strokes = []

    for row in stroke_rows:
        rally_id, s_player, hit_zone, land_zone, _source_method, _hit_zone_source = row
        mid = set_to_match.get(rally_set_map.get(rally_id, -1), -1)
        role = role_by_match.get(mid)
        if not role or s_player != own_slot(role):
            continue
        player_stroke_total += 1
        used_strokes.append(row)
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
        "meta": _with_input_provenance(
            {"sample_size": total, "confidence": _research_confidence("descriptive_basic", total)},
            rallies=rallies,
            strokes=used_strokes,
            uses_hit_zone=True,
        ),
    }


# ─── Phase 2: ダブルスペア両選手監視 ─────────────────────────────────────────

def _same_side_pair_matches(
    db: Session,
    player_a_id: int,
    player_b_id: int,
    result: Optional[str] = None,
    tournament_level: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
) -> list[Match]:
    """2 人が同じ側 (player_a + partner_a、または player_b + partner_b) で出たダブルス試合。

    防ぐ事象: 対戦相手同士 (player_a と player_b) を「同一ペア」として取り込み、
    相手側の打球と勝敗をペアの値に混ぜる (監査 #740)。
    result は 2 人から見た勝敗 ("win" / "loss") で、Match.result (A 側視点) の値そのものではない。
    """
    validate_date_range(date_from, date_to)
    if player_a_id == player_b_id:
        return []
    q = db.query(Match).filter(
        Match.format != "singles",
        or_(
            and_(Match.player_a_id == player_a_id, Match.partner_a_id == player_b_id),
            and_(Match.player_a_id == player_b_id, Match.partner_a_id == player_a_id),
            and_(Match.player_b_id == player_a_id, Match.partner_b_id == player_b_id),
            and_(Match.player_b_id == player_b_id, Match.partner_b_id == player_a_id),
        ),
    )
    if result in ("win", "loss"):
        q = q.filter(player_result_filter(player_a_id, result))
    if tournament_level:
        q = q.filter(Match.tournament_level == tournament_level)
    if date_from:
        q = q.filter(Match.date >= date_from)
    if date_to:
        q = q.filter(Match.date <= date_to)
    return q.order_by(Match.date).all()


def _pair_strokes(
    db: Session,
    matches: list[Match],
    player_a_id: int,
    player_b_id: int,
    require_land_zone: bool = False,
):
    """ペアの試合のラリーと、ペア 2 人の個人枠の打球だけ。

    返り値: (rallies, pair_strokes, rally_team, owner) 。rally_team は rally.id -> ペアのチーム側。
    owner は id(打球) -> "a" (player_a_id の打球) / "b" (player_b_id の打球)。
    打球は Stroke.player (個人の枠) が試合ごとの 2 人の枠と一致するものに限る
    (相手側の打球、相方以外の枠は入れない)。
    """
    if not matches:
        return [], [], {}, {}
    slots: dict[int, tuple[str, str, str]] = {}
    for m in matches:
        va = perspective(m, player_a_id)
        vb = perspective(m, player_b_id)
        if va is None or vb is None:
            continue
        slots[m.id] = (str(va), va.slot, vb.slot)
    match_ids = list(slots)
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all() if match_ids else []
    set_to_match = {s.id: s.match_id for s in sets}
    rallies = db.query(Rally).filter(Rally.set_id.in_(list(set_to_match))).all() if set_to_match else []
    rally_match = {r.id: set_to_match[r.set_id] for r in rallies}
    rally_team = {rid: slots[mid][0] for rid, mid in rally_match.items()}
    sq = db.query(Stroke).filter(Stroke.rally_id.in_(list(rally_match))) if rally_match else None
    if sq is not None and require_land_zone:
        sq = sq.filter(Stroke.land_zone != None)  # noqa: E711
    all_strokes = sq.all() if sq is not None else []
    pair_strokes = []
    owner: dict[int, str] = {}
    for s in all_strokes:
        _side, slot_a, slot_b = slots[rally_match[s.rally_id]]
        if s.player == slot_a:
            owner[id(s)] = "a"
        elif s.player == slot_b:
            owner[id(s)] = "b"
        else:
            continue
        pair_strokes.append(s)
    return rallies, pair_strokes, rally_team, owner


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
    """ペア両選手が同じ側で出場したダブルス試合のラリーの合算解析。"""

    from collections import Counter

    matches = _same_side_pair_matches(
        db, player_a_id, player_b_id, result, tournament_level, date_from, date_to,
    )
    filter_applied = bool(result in ("win", "loss") or tournament_level or date_from or date_to)
    if not matches:
        confidence = _research_confidence("descriptive_basic", 0)
        return {"success": True, "data": {
            "pair_win_rate": None, "pair_match_count": 0, "shared_matches": [],
            "stroke_share": {"player_a": None, "player_b": None},
            "common_loss_pattern": None, "common_win_shot": None,
        }, "meta": _with_input_provenance(
            {"sample_size": 0, "confidence": confidence,
             "population": {"n_matches": 0, "filter_applied": filter_applied}},
            rallies=[],
            strokes=[],
        )}

    shared_match_ids = [m.id for m in matches]
    rallies, pair_strokes, rally_team, owner = _pair_strokes(db, matches, player_a_id, player_b_id)

    # ペア勝率 (勝敗が確定した試合だけ。確定が 0 件なら None)
    decided = [player_wins_match(m, player_a_id) for m in matches]
    decided = [w for w in decided if w is not None]
    pair_win_rate = round(sum(1 for w in decided if w) / len(decided), 3) if decided else None

    # ストローク分担比率: 試合ごとの 2 人の個人枠の打球数
    cnt_a = sum(1 for s in pair_strokes if owner[id(s)] == "a")
    cnt_b = sum(1 for s in pair_strokes if owner[id(s)] == "b")
    cnt_total = cnt_a + cnt_b
    # ストローク 0 件の分担比率は 0.0 ではなく None (統計規則 R1)。件数は meta.sample_size 側
    stroke_share = {
        "player_a": round(cnt_a / cnt_total, 3) if cnt_total else None,
        "player_b": round(cnt_b / cnt_total, 3) if cnt_total else None,
    }

    # 共通の得点前・失点前ショット (ペア 2 人の打球だけ)
    win_rally_ids: set[int] = set()
    loss_rally_ids: set[int] = set()
    for r in rallies:
        team = rally_team.get(r.id)
        if team is None:
            continue
        if r.winner == team:
            win_rally_ids.add(r.id)
        else:
            loss_rally_ids.add(r.id)

    common_win_shot = None
    win_shots = [s.shot_type for s in pair_strokes if s.rally_id in win_rally_ids and s.shot_type]
    if win_shots:
        common_win_shot = Counter(win_shots).most_common(1)[0][0]

    common_loss_pattern = None
    loss_shots = [s.shot_type for s in pair_strokes if s.rally_id in loss_rally_ids and s.shot_type]
    if loss_shots:
        common_loss_pattern = Counter(loss_shots).most_common(1)[0][0]

    confidence = _research_confidence("descriptive_basic", len(rallies))
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
        "meta": _with_input_provenance(
            {"sample_size": len(rallies), "confidence": confidence,
             "population": {"n_matches": len(matches), "filter_applied": filter_applied}},
            rallies=rallies,
            strokes=pair_strokes,
        ),
    }


@router.get("/analysis/partner_timeline")
def get_partner_timeline(
    player_id: int,
    partner_id: int,
    result: Optional[str] = None,
    tournament_level: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """ペア別試合ごとの勝率推移。pair_combined と同じ試合の選び方・同じ絞り込みを使う (監査 #740 / #741)。"""

    matches = _same_side_pair_matches(
        db, player_id, partner_id, result, tournament_level, date_from, date_to,
    )
    filter_applied = bool(result in ("win", "loss") or tournament_level or date_from or date_to)
    population = {"n_matches": len(matches), "filter_applied": filter_applied}

    if not matches:
        return {"success": True, "data": {"points": [], "overall_win_rate": None},
                "meta": {"sample_size": 0, "confidence": _research_confidence("descriptive_basic", 0),
                         "population": population}}

    points = []
    win_count = 0
    decided_count = 0
    for m in matches:
        won = player_wins_match(m, player_id)
        if won is None:
            continue
        decided_count += 1
        if won:
            win_count += 1
        points.append({
            "match_id": m.id,
            "date": str(m.date),
            "result": "win" if won else "loss",
            "cumulative_win_rate": round(win_count / decided_count, 3),
            "tournament": m.tournament,
        })

    overall_win_rate = round(win_count / decided_count, 3) if decided_count else None
    confidence = _research_confidence("descriptive_basic", decided_count)
    return {
        "success": True,
        "data": {"points": points, "overall_win_rate": overall_win_rate},
        "meta": {"sample_size": decided_count, "confidence": confidence, "population": population},
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

    validate_date_range(date_from, date_to)
    q = db.query(Match).filter(
        involves_player(player_id)
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
        confidence = _research_confidence("descriptive_basic", 0)
        return {"success": True, "data": {"affinity": {}, "summary": [], "axes": {}},
                "meta": {"sample_size": 0, "confidence": confidence}}

    # 5軸分類（classify_all_opponents で全相手を一括分類）
    provenance_rows: dict[str, list] = {}
    classified = classify_all_opponents(
        db,
        player_id,
        matches,
        provenance_rows=provenance_rows,
    )

    # ── style 軸（後方互換: 従来の affinity / summary を維持）────────────────
    type_stats: dict[str, dict] = {
        "攻撃型":     {"wins": 0, "total": 0},
        "守備型":     {"wins": 0, "total": 0},
        "バランス型": {"wins": 0, "total": 0},
    }
    unclassified_matches = 0  # 相手の打球データが無く型を判定できなかった試合
    for m in matches:
        opp_id = opponent_player_id(m, player_id)
        cls = classified.get(opp_id)
        if cls is None:
            continue
        opp_type = cls["axes"]["style"]
        if opp_type == UNCLASSIFIED:
            unclassified_matches += 1
            continue
        player_role = team_side(m, player_id)
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
    confidence = _research_confidence("descriptive_basic", sample_size)
    return {
        "success": True,
        "data": {
            "affinity": affinity,
            "summary": summary,
            "axes": axes,
            "unclassified_matches": unclassified_matches,
        },
        "meta": _with_input_provenance(
            {"sample_size": sample_size, "confidence": confidence},
            rallies=provenance_rows.get("rallies", []),
            strokes=provenance_rows.get("strokes", []),
            uses_hit_zone=True,
        ),
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

    # 両選手が同じ側で出場したダブルス試合 (対戦相手同士は含めない、監査 #740)
    matches = _same_side_pair_matches(db, player_a_id, player_b_id)

    if not matches:
        confidence = _research_confidence("descriptive_basic", 0)
        return {"success": True, "data": {
            "playstyle": "不明", "playstyle_en": "unknown",
            "zone_distribution": {}, "metrics": {},
        }, "meta": _with_input_provenance(
            {"sample_size": 0, "confidence": confidence},
            rallies=[],
            strokes=[],
        )}

    # 集計する打球はペア 2 人の個人枠のものだけ (相手側の配球・着地点は混ぜない)
    rallies, strokes, _rally_team, _owner = _pair_strokes(
        db, matches, player_a_id, player_b_id, require_land_zone=True,
    )

    total_strokes = len(strokes)
    if total_strokes == 0:
        confidence = _research_confidence("descriptive_basic", 0)
        return {"success": True, "data": {
            "playstyle": "不明", "playstyle_en": "unknown",
            "zone_distribution": {}, "metrics": {},
        }, "meta": _with_input_provenance(
            {"sample_size": 0, "confidence": confidence},
            rallies=rallies,
            strokes=strokes,
        )}

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

    confidence = _research_confidence("descriptive_basic", total_strokes)
    return {
        "success": True,
        "data": {
            "playstyle": playstyle,
            "playstyle_en": playstyle_en,
            "zone_distribution": zone_dist,
            "metrics": metrics,
        },
        "meta": _with_input_provenance(
            {"sample_size": total_strokes, "confidence": confidence},
            rallies=rallies,
            strokes=strokes,
        ),
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
        .filter(involves_player(player_id))
        .all()
    )
    if not matches:
        return {"success": True, "data": {"global_shot_winrates": {}, "opponents": []},
                "meta": _with_input_provenance(
                    {"sample_size": 0, "confidence": _research_confidence("descriptive_basic", 0)},
                    rallies=[],
                    strokes=[],
                )}

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
    used_strokes = []

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
        if s.player != own_slot(role):
            continue

        match = matches_by_id.get(mid)  # O(1) 辞書引き
        if not match:
            continue

        # 対戦相手ID
        opp_id = opponent_player_id(match, player_id)
        won = 1 if rally.winner == role else 0
        used_strokes.append(s)

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

    total_strokes_all = sum(global_counts.values())
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
            # 相手自身の試合数で判定する (全体の打球数ではない)
            "confidence": _research_confidence(
                "descriptive_basic", total_strokes_all, unit_n=len(opp_match_ids[opp_id]),
            ),
            "shot_effectiveness": effectiveness,
        })

    total = total_strokes_all
    return {
        "success": True,
        "data": {"global_shot_winrates": global_winrates, "opponents": opponents},
        "meta": _with_input_provenance(
            {
                "sample_size": total,
                "confidence": _research_confidence(
                    "descriptive_basic", total,
                    unit_n=_median_n([o["match_count"] for o in opponents], total),
                ),
            },
            rallies=rallies,
            strokes=used_strokes,
        ),
    }


# ---------------------------------------------------------------------------
# Research Roadmap R2: Pair Synergy (3.4)
# ---------------------------------------------------------------------------

@router.get("/analysis/pair_synergy")
@stamps_population("pair_synergy")
def get_pair_synergy(
    player_id: int,
    mf: MatchFilter = Depends(match_filter_params),
    db: Session = Depends(get_db),
):
    """ペアシナジースコア — ダブルスペアごとの相性指標"""
    # 全試合（シングルス含む）でプレイヤー勝率を計算
    # 勝敗確定かつラリー有りの試合だけを数える (analysis_population)。除外件数は meta.excluded
    all_matches, excluded = select_population(db, player_id, mf)
    if not all_matches:
        return {"success": True, "data": {"player_avg_win_rate": None, "pairs": []},
                "meta": {"sample_size": 0, "confidence": _research_confidence("descriptive_basic", 0),
                         "excluded": excluded}}

    total_matches = len(all_matches)
    win_count = sum(1 for m in all_matches if player_wins_match(m, player_id))
    # total_matches=0 は上で早期 return 済み。0.0 を値として返さない (統計規則 R1)
    player_avg_win_rate = round(win_count / total_matches, 3) if total_matches > 0 else None

    # ダブルス試合のみ抽出
    doubles_matches = [m for m in all_matches if m.format in ("womens_doubles", "mixed_doubles", "mens_doubles")]
    if not doubles_matches:
        return {
            "success": True,
            "data": {"player_avg_win_rate": player_avg_win_rate, "pairs": []},
            "meta": {"sample_size": total_matches, "confidence": _research_confidence("descriptive_basic", total_matches),
                     "excluded": excluded},
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
        partner_id = partner_player_id(m, player_id)
        if not partner_id:
            continue

        is_win = bool(player_wins_match(m, player_id))
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
                if st.player == own_slot(role):
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
        # ラリー / ストロークが 0 件 (未アノテーション試合) の平均・割合は 0 ではなく None (統計規則 R1)
        avg_rally = round(pd["total_rally_length"] / pd["rally_count"], 2) if pd["rally_count"] > 0 else None
        stroke_share = round(pd["player_strokes"] / pd["total_strokes"], 3) if pd["total_strokes"] > 0 else None
        partner = partner_players.get(partner_id)
        pairs.append({
            "partner_id": partner_id,
            "partner_name": partner.name if partner else str(partner_id),
            "match_count": mc,
            # ペア自身の試合数で判定する (全体の試合数ではない)
            "confidence": _research_confidence("descriptive_basic", total_matches, unit_n=mc),
            "win_rate": wr,
            "synergy_score": synergy,
            "avg_rally_length": avg_rally,
            "stroke_share": stroke_share,
        })

    pairs.sort(key=lambda x: -x["synergy_score"])

    return {
        "success": True,
        "data": {"player_avg_win_rate": player_avg_win_rate, "pairs": pairs},
        "meta": _with_input_provenance(
            {
                "sample_size": total_matches,
                "confidence": _research_confidence(
                    "descriptive_basic", total_matches,
                    unit_n=_median_n([p["match_count"] for p in pairs], total_matches),
                ),
                "excluded": excluded,
            },
            rallies=rallies,
            strokes=strokes,
        ),
    }


# ---------------------------------------------------------------------------
# Research: エクスプロイタビリティ / ナッシュ均衡 (NE-001)
# ---------------------------------------------------------------------------

@router.get("/analysis/exploitability")
@stamps_population("exploitability")
def get_exploitability(
    player_id: int,
    coarse: bool = Query(True),
    mf: MatchFilter = Depends(match_filter_params),
    db: Session = Depends(get_db),
):
    """NE-001: ゲーム状態別ナッシュ均衡・エクスプロイタビリティ解析（アナリスト専用 research tier）

    各ゲーム状態を 2 人ゼロ和ゲームとして fictitious play で解き、
    実戦略と均衡戦略のギャップ（エクスプロイタビリティ）を返す。
    """
    # レコードを状態別に収集
    provenance_rows: dict[str, list] = {}
    try:
        records_by_state = load_exploitability_records(
            db,
            player_id,
            coarse=coarse,
            provenance_rows=provenance_rows,
            match_filter=mf,
        )
    except Exception:
        logger.exception("exploitability_loader failed for player_id=%s", player_id)
        records_by_state = {}

    states_ok: list[dict] = []
    states_insufficient: list[dict] = []
    total_records = 0

    for state_key, recs in records_by_state.items():
        total_records += len(recs)
        result = _exploitability_analyze_state(recs)
        if result is None:
            states_insufficient.append({
                "state_key": state_key,
                "status": "insufficient",
                "n": len(recs),
            })
        else:
            states_ok.append({
                "state_key": state_key,
                "status": "ok",
                **result,
            })

    # サマリ計算
    exploitability_values = [s["exploitability"] for s in states_ok]
    mean_exploitability: Optional[float] = None
    most_exploitable: Optional[dict] = None
    largest_gap: Optional[dict] = None

    if exploitability_values:
        mean_exploitability = round(sum(exploitability_values) / len(exploitability_values), 4)
        top_state = max(states_ok, key=lambda s: s["exploitability"])
        most_exploitable = {
            "state_key": top_state["state_key"],
            "exploitability": top_state["exploitability"],
        }
        # largest_gap: 最もエクスプロイタビリティが高い状態で、均衡との差が最大の行動。
        # この解析は推奨非対応 (research / exploratory) なので観察値として返し、
        # 「増やす / 減らす」という処方の形にはしない (監査 #141)。
        best_shift = top_state.get("best_shift", {})
        if best_shift:
            top_action = max(best_shift, key=lambda a: abs(best_shift[a]))
            largest_gap = {
                "state_key": top_state["state_key"],
                "action": top_action,
                "shift": best_shift[top_action],
            }

    confidence = _research_confidence("descriptive_basic", total_records)

    return {
        "success": True,
        "data": {
            "states": states_ok + states_insufficient,
            "summary": {
                "states_analyzed": len(states_ok),
                "states_insufficient": len(states_insufficient),
                "mean_exploitability": mean_exploitability,
                "most_exploitable": most_exploitable,
                "largest_gap": largest_gap,
            },
        },
        "meta": _with_input_provenance(
            {
                "sample_size": total_records,
                "confidence": confidence,
                "analysis_type": "exploitability",
                "tier": "research",
                "evidence_level": "exploratory",
            },
            rallies=provenance_rows.get("rallies", []),
            strokes=provenance_rows.get("strokes", []),
        ),
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


# ---------------------------------------------------------------------------
# Research: コンフォーマル予測 (CP-001) — 分布フリー保証付き不確実性定量化
# ---------------------------------------------------------------------------

# グループ別の行に結論 (勝率・勝敗チップ) を出してよい最小の n。
# 言い切りに近い表示を出してよい最低試合数 VERDICT_MIN_SAMPLE (utils/confidence.py) と同じ値を使う。
# 防ぐ事象: n=1〜3 のグループに「勝ち寄り / 負け寄り」が出た (監査 #50)。
# 全体の被覆保証はグループ別の被覆を保証しない (registry の caution 参照)。
CONFORMAL_MIN_GROUP_N = VERDICT_MIN_SAMPLE


@router.get("/analysis/conformal")
@stamps_population("conformal")
def get_conformal(
    player_id: int,
    alpha: float = Query(0.1, ge=0.01, le=0.5),
    coarse: bool = Query(True),
    mf: MatchFilter = Depends(match_filter_params),
    db: Session = Depends(get_db),
):
    """CP-001: split-conformal 予測によるラリー勝敗の分布フリー被覆保証解析
    （アナリスト専用 research tier）

    決定論的 50/50 分割 (インデックス偶数 = 校正、奇数 = テスト) で
    コンフォーマル分位点を推定し、テスト集合での経験的被覆率を検証する。
    """
    # ── データ収集 ──────────────────────────────────────────────────────────
    provenance_rows: dict[str, list] = {}
    try:
        samples = load_rally_outcome_samples(
            db,
            player_id,
            coarse=coarse,
            provenance_rows=provenance_rows,
            match_filter=mf,
        )
    except Exception:
        logger.exception("conformal_loader failed for player_id=%s", player_id)
        samples = []

    n_total = len(samples)
    MIN_SAMPLES = 40  # 校正用 20 + テスト用 20 の最小要件

    if n_total < MIN_SAMPLES:
        confidence = _research_confidence("descriptive_basic", n_total)
        return {
            "success": True,
            "data": {
                "status": "insufficient",
                "alpha": alpha,
                "target_coverage": round(1.0 - alpha, 4),
                "n_total": n_total,
                "n_calibration": 0,
                "n_test": 0,
                "empirical_coverage": None,
                "avg_set_size": None,
                "per_group": [],
                "validation": {"coverage_guarantee_met": None},
            },
            "meta": _with_input_provenance(
                {
                    "sample_size": n_total,
                    "confidence": confidence,
                    "analysis_type": "conformal",
                    "tier": "research",
                    "evidence_level": "exploratory",
                },
                rallies=provenance_rows.get("rallies", []),
                strokes=provenance_rows.get("strokes", []),
            ),
        }

    # ── 決定論的分割: 偶数インデックス=校正、奇数インデックス=テスト ───────
    cal_samples = [s for i, s in enumerate(samples) if i % 2 == 0]
    test_samples = [s for i, s in enumerate(samples) if i % 2 == 1]

    cal_groups = [s["group"] for s in cal_samples]
    cal_wins = [s["win"] for s in cal_samples]
    test_groups = [s["group"] for s in test_samples]
    test_wins = [s["win"] for s in test_samples]

    # ── ベーススコアラー: 校正集合で Laplace 平滑化勝率を推定 ───────────────
    winrate_map = fit_group_winrates(cal_groups, cal_wins)

    # 校正集合の P(win) 予測値
    import numpy as _np
    p_hat_cal = _np.array([predict_p_win(g, winrate_map) for g in cal_groups])
    y_cal = _np.array(cal_wins, dtype=float)

    # ── コンフォーマル分位点 q ──────────────────────────────────────────────
    q = split_conformal(p_hat_cal, y_cal, alpha)

    # ── テスト集合での被覆率検証 ────────────────────────────────────────────
    p_hat_test = _np.array([predict_p_win(g, winrate_map) for g in test_groups])
    y_test = _np.array(test_wins, dtype=float)

    coverage_result = evaluate_coverage(p_hat_test, y_test, q)

    target_coverage = round(1.0 - alpha, 4)
    empirical_coverage = coverage_result["empirical_coverage"]
    avg_set_size = coverage_result["avg_set_size"]

    # 保証判定: 実測被覆率が目標に届いたかを許容幅なしで比べる。
    # 以前は 0.05 の許容幅があり、目標 90% に対し 85% でも「保証成立」と出ていた。
    # コード内にこの値の根拠 (測定・導出) が無かったので外した。
    # 有限の検証集合 (n_test) による揺らぎは、n_test を一緒に返して利用者が読む。
    coverage_guarantee_met: Optional[bool] = None
    if empirical_coverage is not None:
        coverage_guarantee_met = bool(empirical_coverage >= target_coverage)

    # ── グループ別予測集合 (全サンプルのグループを対象) ────────────────────
    # グループ別集計 (全サンプル)
    group_counts: dict[str, int] = {}
    group_wins: dict[str, int] = {}
    for s in samples:
        g = s["group"]
        group_counts[g] = group_counts.get(g, 0) + 1
        group_wins[g] = group_wins.get(g, 0) + s["win"]

    per_group: list[dict] = []
    for g in sorted(group_counts.keys()):
        n_g = group_counts[g]
        if n_g < CONFORMAL_MIN_GROUP_N:
            # n が少ないグループは勝率も勝敗チップも出さない (n=0 を 0.5 にしない規則と同じ扱い)
            per_group.append({
                "group": g, "p_win": None, "prediction_set": None,
                "n": n_g, "n_win": group_wins.get(g, 0), "insufficient": True,
            })
            continue
        p_win = winrate_map.get(g, 0.5)
        pset = _conformal_prediction_set(p_win, q)
        per_group.append({
            "group": g,
            "p_win": round(p_win, 4),
            "prediction_set": pset,
            "n": n_g,
            "n_win": group_wins.get(g, 0),
            "insufficient": False,
        })

    confidence = _research_confidence("descriptive_basic", n_total)

    return {
        "success": True,
        "data": {
            "alpha": alpha,
            "target_coverage": target_coverage,
            "n_total": n_total,
            "n_calibration": len(cal_samples),
            "n_test": len(test_samples),
            "conformal_quantile": round(q, 4),
            "empirical_coverage": empirical_coverage,
            "avg_set_size": avg_set_size,
            "per_group": per_group,
            "validation": {
                "coverage_guarantee_met": coverage_guarantee_met,
            },
        },
        "meta": _with_input_provenance(
            {
                "sample_size": n_total,
                "confidence": confidence,
                "analysis_type": "conformal",
                "tier": "research",
                "evidence_level": "exploratory",
            },
            rallies=provenance_rows.get("rallies", []),
            strokes=provenance_rows.get("strokes", []),
        ),
    }


# ---------------------------------------------------------------------------
# ② DR-OPE: 代替方策のオフポリシー価値評価 (POL-001)
# ---------------------------------------------------------------------------

@router.get("/analysis/policy_eval")
@stamps_population("policy_eval")
def get_policy_eval(
    player_id: int,
    temp: float = Query(0.25, ge=0.01, le=2.0),
    mf: MatchFilter = Depends(match_filter_params),
    db: Session = Depends(get_db),
):
    """POL-001: 状態別に「高価値行動へシフトした方策」の価値を二重頑健 (DR) で
    オフポリシー評価し、bootstrap 信頼区間付きで実方策との差 (uplift) を返す。
    player_id は router の require_query_scope で team 検証済み。"""
    provenance_rows: dict[str, list] = {}
    try:
        records_by_state = load_policy_records(
            db,
            player_id,
            coarse=True,
            provenance_rows=provenance_rows,
            match_filter=mf,
        )
    except Exception:
        logger.exception("dr_ope_loader failed for player_id=%s", player_id)
        records_by_state = {}

    states_ok: list[dict] = []
    states_insuf: list[dict] = []
    total = 0
    for sk, recs in records_by_state.items():
        total += len(recs)
        r = _dr_evaluate_state(recs, temp=temp)
        if r is None:
            states_insuf.append({"state_key": sk, "status": "insufficient", "n": len(recs)})
        else:
            states_ok.append({"state_key": sk, "status": "ok", **r})

    mean_uplift = (
        round(sum(s["uplift"] for s in states_ok) / len(states_ok), 4) if states_ok else None
    )
    best_state = max(states_ok, key=lambda s: s["uplift"]) if states_ok else None
    confidence = _research_confidence("descriptive_basic", total)
    return {
        "success": True,
        "data": {
            "states": states_ok + states_insuf,
            "summary": {
                "states_analyzed": len(states_ok),
                "states_insufficient": len(states_insuf),
                "mean_uplift": mean_uplift,
                "best_state": (
                    {"state_key": best_state["state_key"], "uplift": best_state["uplift"]}
                    if best_state else None
                ),
            },
        },
        "meta": _with_input_provenance(
            {
                "sample_size": total,
                "confidence": confidence,
                "analysis_type": "policy_eval",
                "tier": "research",
                "evidence_level": "exploratory",
            },
            rallies=provenance_rows.get("rallies", []),
            strokes=provenance_rows.get("strokes", []),
        ),
    }


def _accessible_player_ids(ctx: AuthCtx, db: Session):
    """比較コホートに含めてよい player_id 集合を返す (cross-team 漏洩防止)。
    admin は None (無制限)。analyst/coach は自チーム所属 + 自チームから可視な試合に
    登場する選手のみ。team 未所属は空集合。ctx は Depends(get_auth) で受けること
    (テストの dependency_overrides[get_auth] と本番 JWT 両対応)。"""
    if ctx.is_admin:
        return None
    if ctx.team_id is None:
        return set()
    ids = {pid for (pid,) in db.query(Player.id).filter(Player.team_id == ctx.team_id).all()}
    try:
        for m in apply_match_team_scope(db.query(Match), ctx).all():
            for pid in (m.player_a_id, getattr(m, "partner_a_id", None),
                        m.player_b_id, getattr(m, "partner_b_id", None)):
                if pid:
                    ids.add(pid)
    except Exception:
        logger.exception("accessible cohort match scan failed")
    return ids


# ---------------------------------------------------------------------------
# ④ 最適輸送による棋風距離 (STYLE-001)
# ---------------------------------------------------------------------------

@router.get("/analysis/style_distance")
@stamps_population("style_distance")
def get_style_distance(
    player_id: int,
    mf: MatchFilter = Depends(match_filter_params),
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
):
    """STYLE-001: 着地点分布間の Wasserstein (最適輸送) 距離で棋風の近さを測る。
    比較コホートは team-scoped (自チーム + 自チーム可視選手のみ)。"""
    allowed = _accessible_player_ids(ctx, db)
    provenance_rows: dict[str, list] = {}
    try:
        hists = load_zone_histograms(
            db,
            player_id,
            allowed_player_ids=allowed,
            min_matches=3,
            provenance_rows=provenance_rows,
            match_filter=mf,
        )
    except Exception:
        logger.exception("optimal_transport_loader failed for player_id=%s", player_id)
        hists = {}

    confidence = _research_confidence("descriptive_basic", len(hists))
    if player_id not in hists or len(hists) < 2:
        return {
            "success": True,
            "data": {"reference_player": player_id, "cohort_size": max(0, len(hists) - 1),
                     "zone_labels": list(_OT_ZONE_LABELS), "distances": [], "nearest": [], "style_map": []},
            "meta": _with_input_provenance(
                {
                    "sample_size": len(hists),
                    "confidence": confidence,
                    "analysis_type": "style_distance",
                    "tier": "research",
                    "evidence_level": "exploratory",
                },
                rallies=provenance_rows.get("rallies", []),
                strokes=provenance_rows.get("strokes", []),
            ),
        }

    cost = _ot_build_cost_matrix(_OT_ZONE_LABELS)
    ids, D = _ot_pairwise(hists, cost)
    coords = _ot_mds(D, dims=2)
    idx = {pid: i for i, pid in enumerate(ids)}
    ref = idx[player_id]
    name_map = {pid: nm for (pid, nm) in db.query(Player.id, Player.name).filter(Player.id.in_(ids)).all()}

    distances = sorted(
        ({"player_id": pid, "player_name": name_map.get(pid), "distance": round(float(D[ref][idx[pid]]), 4)}
         for pid in ids if pid != player_id),
        key=lambda d: d["distance"],
    )
    style_map = [
        {"player_id": pid, "player_name": name_map.get(pid),
         "x": round(float(coords[idx[pid]][0]), 4), "y": round(float(coords[idx[pid]][1]), 4)}
        for pid in ids
    ]
    return {
        "success": True,
        "data": {
            "reference_player": player_id, "cohort_size": len(ids) - 1,
            "zone_labels": list(_OT_ZONE_LABELS),
            "distances": distances,
            "nearest": [d["player_id"] for d in distances[:3]],
            "style_map": style_map,
        },
        "meta": _with_input_provenance(
            {
                "sample_size": len(ids),
                "confidence": confidence,
                "analysis_type": "style_distance",
                "tier": "research",
                "evidence_level": "exploratory",
            },
            rallies=provenance_rows.get("rallies", []),
            strokes=provenance_rows.get("strokes", []),
        ),
    }


# ---------------------------------------------------------------------------
# ③ 階層ベイズ対戦予測 (MATCHUP-001)
# ---------------------------------------------------------------------------

@router.get("/analysis/matchup_forecast")
@stamps_population("matchup_forecast")
def get_matchup_forecast(
    player_id: int,
    opponent_id: Optional[int] = Query(None),
    mf: MatchFilter = Depends(match_filter_params),
    db: Session = Depends(get_db),
    ctx: AuthCtx = Depends(get_auth),
):
    """MATCHUP-001: 階層ベイズ Bradley-Terry (partial pooling) で対戦勝率を
    不確実性付きで予測。データが疎な対戦ほど CI が広がる。コホートは team-scoped。"""
    allowed = _accessible_player_ids(ctx, db)
    try:
        ids, pairs = load_match_pairs(db, player_id, allowed_player_ids=allowed, match_filter=mf)
    except Exception:
        logger.exception("hier_bayes_loader failed for player_id=%s", player_id)
        ids, pairs = [], []

    confidence = _research_confidence("descriptive_basic", len(pairs))
    if player_id not in ids or len(ids) < 2 or not pairs:
        return {
            "success": True,
            "data": {"player_id": player_id, "strength": None, "matchups": [],
                     "n_players": len(ids), "n_matches": len(pairs)},
            "meta": _with_input_provenance({
                "sample_size": len(pairs),
                "confidence": confidence,
                "analysis_type": "matchup_forecast",
                "tier": "research",
                "evidence_level": "exploratory",
            }),
        }

    idx = {pid: i for i, pid in enumerate(ids)}
    indexed = [(idx[w], idx[l]) for (w, l) in pairs if w in idx and l in idx]
    fit = fit_bradley_terry(indexed, n_players=len(ids))
    theta = fit["theta"]; var = fit["theta_var"]
    ti = idx[player_id]
    name_map = {pid: nm for (pid, nm) in db.query(Player.id, Player.name).filter(Player.id.in_(ids)).all()}

    def _h2h(pid):
        return sum(1 for (w, l) in pairs if {w, l} == {player_id, pid})

    targets = [opponent_id] if opponent_id is not None else [pid for pid in ids if pid != player_id]
    matchups = []
    for pid in targets:
        if pid not in idx or pid == player_id:
            continue
        pr = predict_matchup(float(theta[ti]), float(var[ti]), float(theta[idx[pid]]), float(var[idx[pid]]))
        n_h2h = _h2h(pid)
        matchups.append({
            "opponent_id": pid, "opponent_name": name_map.get(pid),
            "n_h2h": n_h2h,
            # この対戦自身の対戦数と区間幅で判定する (コホート全体の件数ではない)
            "confidence": _research_confidence(
                "descriptive_basic", len(pairs),
                unit_n=n_h2h, interval_width=float(pr["ci_high"]) - float(pr["ci_low"]),
            ),
            **pr,
        })
    matchups.sort(key=lambda m: -m["p_win"])

    if opponent_id is not None and matchups:
        # 1 対戦だけを表示するときは、その対戦の信頼度を全体の信頼度にする
        confidence = matchups[0]["confidence"]

    _se = math.sqrt(max(0.0, float(var[ti])))
    strength = {"value": round(float(theta[ti]), 4),
                "ci_low": round(float(theta[ti]) - 1.645 * _se, 4),
                "ci_high": round(float(theta[ti]) + 1.645 * _se, 4)}
    return {
        "success": True,
        "data": {"player_id": player_id, "strength": strength, "matchups": matchups,
                 "n_players": len(ids), "n_matches": len(pairs)},
        "meta": _with_input_provenance({
            "sample_size": len(pairs),
            "confidence": confidence,
            "analysis_type": "matchup_forecast",
            "tier": "research",
            "evidence_level": "exploratory",
        }),
    }
