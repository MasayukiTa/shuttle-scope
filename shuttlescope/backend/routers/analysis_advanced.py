"""analysis_advanced.py — advanced tier 解析エンドポイント"""
import math
from collections import defaultdict, Counter
from datetime import date as DateType
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.db.database import get_db
from backend.db.models import Match, GameSet, Rally, Stroke, Player, PreMatchObservation
from backend.utils.confidence import check_confidence
from backend.analysis.router_helpers import (
    SHOT_TYPE_JA, SHOT_KEYS, SHOT_LABELS_JA, END_TYPE_JA, _shot_ja,
    _player_role_in_match, _get_player_matches, _fetch_matches_sets_rallies,
)
from backend.analysis.analysis_config import AnalysisConfig
from backend.analysis.growth_engine import (
    growth_points_weighted,
    strength_weighted_moving_avg,
    compute_growth_trend,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# B-003: 連続得点/失点・デュース勝率・逆転率
# ---------------------------------------------------------------------------

@router.get("/analysis/consecutive_streaks")
def get_consecutive_streaks(match_id: int, db: Session = Depends(get_db)):
    """B-003: 試合内のスコア推移から連続得点/失点・デュース勝率・逆転率を返す"""
    match = db.get(Match, match_id)
    if not match:
        return {
            "success": False,
            "error": f"試合ID {match_id} が見つかりません",
        }

    sets = db.query(GameSet).filter(GameSet.match_id == match_id).order_by(GameSet.set_num).all()
    if not sets:
        return {
            "success": True,
            "data": {
                "streaks": [],
                "deuce_win_rate": 0.0,
                "comeback_count": 0,
            },
        }

    set_ids = [s.id for s in sets]
    set_winner_map: dict[int, str] = {s.id: s.winner for s in sets}

    rallies_all = (
        db.query(Rally)
        .filter(Rally.set_id.in_(set_ids))
        .order_by(Rally.set_id, Rally.rally_num)
        .all()
    )

    # セットごとにラリーをグループ化
    rallies_by_set: dict[int, list[Rally]] = defaultdict(list)
    for rally in rallies_all:
        rallies_by_set[rally.set_id].append(rally)

    all_streaks = []
    deuce_total = 0
    deuce_wins = 0
    comeback_count = 0

    for game_set in sets:
        set_rallies = rallies_by_set[game_set.id]
        if not set_rallies:
            continue

        set_winner = game_set.winner  # player_a / player_b

        # デュースセット判定
        if game_set.is_deuce and set_winner:
            deuce_total += 1
            # player_a が勝ったセット数を基準にするため、ここでは単純にカウント
            # ※ デュースに達したセットで player_a が勝った場合を「勝ち」として扱う
            deuce_wins += 1  # 実際は後で逆転判定と合わせる

        # 連続得点/失点ストリーク検出（player_a 基準）
        streaks_in_set = []
        streak_type = None
        streak_start_idx = 0
        streak_len = 0

        for i, rally in enumerate(set_rallies):
            current_type = "win_streak" if rally.winner == "player_a" else "lose_streak"
            if streak_type is None:
                streak_type = current_type
                streak_start_idx = i
                streak_len = 1
            elif current_type == streak_type:
                streak_len += 1
            else:
                # ストリーク終了: 3以上なら記録
                if streak_len >= AnalysisConfig.STREAK_MIN_LENGTH:
                    start_rally = set_rallies[streak_start_idx]
                    score_a = start_rally.score_a_after - (1 if start_rally.winner == "player_a" else 0)
                    score_b = start_rally.score_b_after - (1 if start_rally.winner == "player_b" else 0)
                    streaks_in_set.append({
                        "set_num": game_set.set_num,
                        "start_rally": start_rally.rally_num,
                        "end_rally": set_rallies[streak_start_idx + streak_len - 1].rally_num,
                        "type": streak_type,
                        "length": streak_len,
                        "score_at_start": f"{score_a}-{score_b}",
                    })
                streak_type = current_type
                streak_start_idx = i
                streak_len = 1

        # 末尾ストリーク処理
        if streak_len >= AnalysisConfig.STREAK_MIN_LENGTH:
            start_rally = set_rallies[streak_start_idx]
            score_a = start_rally.score_a_after - (1 if start_rally.winner == "player_a" else 0)
            score_b = start_rally.score_b_after - (1 if start_rally.winner == "player_b" else 0)
            streaks_in_set.append({
                "set_num": game_set.set_num,
                "start_rally": start_rally.rally_num,
                "end_rally": set_rallies[streak_start_idx + streak_len - 1].rally_num,
                "type": streak_type,
                "length": streak_len,
                "score_at_start": f"{score_a}-{score_b}",
            })

        all_streaks.extend(streaks_in_set)

        # 逆転判定: player_a が一時リードを許した（負けていた）後に逆転勝利したか
        if set_winner == "player_a":
            was_trailing = False
            for rally in set_rallies:
                if rally.score_b_after > rally.score_a_after:
                    was_trailing = True
                    break
            if was_trailing:
                comeback_count += 1

    # デュース勝率の再計算（is_deuce フラグを持つセットのうち player_a が勝った割合）
    deuce_sets = [s for s in sets if s.is_deuce]
    deuce_total = len(deuce_sets)
    deuce_wins = sum(1 for s in deuce_sets if s.winner == "player_a")
    deuce_win_rate = round(deuce_wins / deuce_total, 3) if deuce_total else 0.0

    return {
        "success": True,
        "data": {
            "streaks": all_streaks,
            "deuce_win_rate": deuce_win_rate,
            "comeback_count": comeback_count,
        },
    }


# ---------------------------------------------------------------------------
# D-001: ラリー長区間別勝率
# ---------------------------------------------------------------------------

@router.get("/analysis/rally_length_vs_winrate")
def get_rally_length_vs_winrate(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """D-001: ラリー長区間別勝率とプレイヤータイプを返す"""
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    empty_confidence = check_confidence("rally_vs_winrate", 0)
    if not matches:
        return {
            "success": True,
            "data": {
                "buckets": [],
                "player_type": "unknown",
                "player_type_ja": "不明",
            },
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    match_ids = [m.id for m in matches]
    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, player_id) for m in matches
    }

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_ids = [s.id for s in sets]
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []

    # 区間定義: (label, min_length, max_length_inclusive)
    buckets_def = [
        ("1-3", 1, 3),
        ("4-6", 4, 6),
        ("7-10", 7, 10),
        ("11-15", 11, 15),
        ("16+", 16, None),
    ]
    bucket_total: dict[str, int] = {b[0]: 0 for b in buckets_def}
    bucket_wins: dict[str, int] = {b[0]: 0 for b in buckets_def}

    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        player_role = role_by_match[match_id]
        length = rally.rally_length
        player_won = rally.winner == player_role

        for label, lo, hi in buckets_def:
            if hi is None:
                if length >= lo:
                    bucket_total[label] += 1
                    if player_won:
                        bucket_wins[label] += 1
                    break
            else:
                if lo <= length <= hi:
                    bucket_total[label] += 1
                    if player_won:
                        bucket_wins[label] += 1
                    break

    total_rallies = len(rallies)

    bucket_results = []
    for label, _lo, _hi in buckets_def:
        total = bucket_total[label]
        wins = bucket_wins[label]
        win_rate = round(wins / total, 3) if total else 0.0
        bucket_results.append({
            "range": label,
            "count": total,
            "win_rate": win_rate,
        })

    # プレイヤータイプ判定
    short_wr = (
        bucket_wins["1-3"] / bucket_total["1-3"]
        if bucket_total["1-3"] else 0.0
    )
    long_wr = (
        (bucket_wins["11-15"] + bucket_wins["16+"])
        / (bucket_total["11-15"] + bucket_total["16+"])
        if (bucket_total["11-15"] + bucket_total["16+"]) > 0 else 0.0
    )

    if short_wr >= 0.60 and short_wr > long_wr + 0.10:
        player_type = "short_game_specialist"
        player_type_ja = "短期決戦型"
    elif long_wr >= 0.55 and long_wr > short_wr + 0.05:
        player_type = "endurance_player"
        player_type_ja = "持久戦型"
    else:
        player_type = "balanced"
        player_type_ja = "バランス型"

    confidence = check_confidence("rally_vs_winrate", total_rallies)

    return {
        "success": True,
        "data": {
            "buckets": bucket_results,
            "player_type": player_type,
            "player_type_ja": player_type_ja,
        },
        "meta": {
            "sample_size": total_rallies,
            "confidence": confidence,
        },
    }


# ---------------------------------------------------------------------------
# D-004: デュース・終盤時のパフォーマンス
# ---------------------------------------------------------------------------

@router.get("/analysis/pressure_performance")
def get_pressure_performance(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """D-004: デュース時・終盤時・通常時のパフォーマンス比較"""
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    empty_confidence = check_confidence("pressure_performance", 0)
    empty_stat = {"total": 0, "win_rate": 0.0, "avg_rally_length": 0.0}
    if not matches:
        return {
            "success": True,
            "data": {
                "deuce": empty_stat,
                "endgame": empty_stat,
                "normal": empty_stat,
            },
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    match_ids = [m.id for m in matches]
    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, player_id) for m in matches
    }

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_ids = [s.id for s in sets]
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []

    # 各シチュエーションの統計
    stats: dict[str, dict] = {
        "deuce": {"total": 0, "wins": 0, "total_length": 0},
        "endgame": {"total": 0, "wins": 0, "total_length": 0},
        "normal": {"total": 0, "wins": 0, "total_length": 0},
    }

    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        player_role = role_by_match[match_id]
        player_won = rally.winner == player_role

        # シチュエーション分類（デュース優先）
        if rally.is_deuce:
            key = "deuce"
        elif rally.score_a_after >= AnalysisConfig.PRESSURE_SCORE_THRESHOLD or rally.score_b_after >= AnalysisConfig.PRESSURE_SCORE_THRESHOLD:
            # 得点後スコアが17以上 → 終盤局面（score_after なので前のスコアで判断すると
            # score_after - 1が実際の打球時スコアだが仕様に従い score_after で判定）
            key = "endgame"
        else:
            key = "normal"

        stats[key]["total"] += 1
        stats[key]["total_length"] += rally.rally_length
        if player_won:
            stats[key]["wins"] += 1

    def _build_stat(s: dict) -> dict:
        total = s["total"]
        win_rate = round(s["wins"] / total, 3) if total else 0.0
        avg_rally_length = round(s["total_length"] / total, 3) if total else 0.0
        return {"total": total, "win_rate": win_rate, "avg_rally_length": avg_rally_length}

    total_all = sum(s["total"] for s in stats.values())
    confidence = check_confidence("pressure_performance", total_all)

    return {
        "success": True,
        "data": {
            "deuce": _build_stat(stats["deuce"]),
            "endgame": _build_stat(stats["endgame"]),
            "normal": _build_stat(stats["normal"]),
        },
        "meta": {
            "sample_size": total_all,
            "confidence": confidence,
        },
    }


# ---------------------------------------------------------------------------
# C-001: ショット遷移行列（18x18）
# ---------------------------------------------------------------------------

@router.get("/analysis/shot_transition_matrix")
def get_shot_transition_matrix(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """C-001: プレイヤーのショット遷移行列（18x18）を返す"""
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    n = len(SHOT_KEYS)
    empty_matrix = [[0.0] * n for _ in range(n)]
    empty_raw = [[0] * n for _ in range(n)]
    empty_confidence = check_confidence("shot_transition", 0)

    if not matches:
        return {
            "success": True,
            "data": {
                "matrix": empty_matrix,
                "shot_labels": SHOT_LABELS_JA,
                "shot_keys": SHOT_KEYS,
                "raw_counts": empty_raw,
                "total_transitions": 0,
                "top_sequences": [],
            },
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    match_ids = [m.id for m in matches]
    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, player_id) for m in matches
    }

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_ids = [s.id for s in sets]
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}

    if not set_ids:
        return {
            "success": True,
            "data": {
                "matrix": empty_matrix,
                "shot_labels": SHOT_LABELS_JA,
                "shot_keys": SHOT_KEYS,
                "raw_counts": empty_raw,
                "total_transitions": 0,
                "top_sequences": [],
            },
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    rally_ids_rows = db.query(Rally.id, Rally.set_id).filter(Rally.set_id.in_(set_ids)).all()
    rally_ids = [r.id for r in rally_ids_rows]
    rally_to_set: dict[int, int] = {r.id: r.set_id for r in rally_ids_rows}

    if not rally_ids:
        return {
            "success": True,
            "data": {
                "matrix": empty_matrix,
                "shot_labels": SHOT_LABELS_JA,
                "shot_keys": SHOT_KEYS,
                "raw_counts": empty_raw,
                "total_transitions": 0,
                "top_sequences": [],
            },
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    # 全ストロークを取得（rally_id, stroke_num, player, shot_type の順でソート）
    all_strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(rally_ids))
        .order_by(Stroke.rally_id, Stroke.stroke_num)
        .all()
    )

    # ラリーごとにプレイヤーロールを確定
    rally_to_role: dict[int, str] = {}
    for r_id, s_id in [(r.id, r.set_id) for r in rally_ids_rows]:
        match_id = set_to_match[s_id]
        rally_to_role[r_id] = role_by_match[match_id]

    # ラリーごとにストロークをグループ化し、プレイヤーのストロークだけ抽出して遷移を集計
    shot_idx = {k: i for i, k in enumerate(SHOT_KEYS)}
    raw_counts = [[0] * n for _ in range(n)]

    strokes_by_rally: dict[int, list[Stroke]] = defaultdict(list)
    for stroke in all_strokes:
        strokes_by_rally[stroke.rally_id].append(stroke)

    total_transitions = 0
    for r_id, strokes in strokes_by_rally.items():
        player_role = rally_to_role.get(r_id)
        if not player_role:
            continue
        # プレイヤーのストロークだけ抽出（stroke_num順にソート済み）
        player_strokes = [s for s in strokes if s.player == player_role]
        # バドミントンでは同一プレイヤーは1打おきに打つため、
        # プレイヤーのストロークのみの連続遷移（s_i → s_{i+1}）を集計する
        for i in range(len(player_strokes) - 1):
            s1 = player_strokes[i]
            s2 = player_strokes[i + 1]
            # stroke_num の差が2なら正常な交互打球（差が2より大きい場合も含む）
            # 差が奇数の場合はスキップ（通常は発生しないが念のため）
            diff = s2.stroke_num - s1.stroke_num
            if diff < 2 or diff % 2 != 0:
                continue
            idx1 = shot_idx.get(s1.shot_type)
            idx2 = shot_idx.get(s2.shot_type)
            if idx1 is None or idx2 is None:
                continue
            raw_counts[idx1][idx2] += 1
            total_transitions += 1

    # 正規化行列（行和で割る）
    matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        row_sum = sum(raw_counts[i])
        if row_sum > 0:
            for j in range(n):
                matrix[i][j] = round(raw_counts[i][j] / row_sum, 4)

    # 上位遷移シーケンス（出現数上位10件）
    transition_list = []
    for i in range(n):
        for j in range(n):
            if raw_counts[i][j] > 0:
                row_sum = sum(raw_counts[i])
                prob = round(raw_counts[i][j] / row_sum, 3) if row_sum else 0.0
                transition_list.append({
                    "from": SHOT_KEYS[i],
                    "to": SHOT_KEYS[j],
                    "count": raw_counts[i][j],
                    "probability": prob,
                })
    transition_list.sort(key=lambda x: x["count"], reverse=True)
    top_sequences = transition_list[:10]

    confidence = check_confidence("shot_transition", total_transitions)

    return {
        "success": True,
        "data": {
            "matrix": matrix,
            "shot_labels": SHOT_LABELS_JA,
            "shot_keys": SHOT_KEYS,
            "raw_counts": raw_counts,
            "total_transitions": total_transitions,
            "top_sequences": top_sequences,
        },
        "meta": {
            "sample_size": total_transitions,
            "confidence": confidence,
        },
    }


# ---------------------------------------------------------------------------
# D-002: スコアフェーズ別パフォーマンス（序盤/中盤/終盤）
# ---------------------------------------------------------------------------

@router.get("/analysis/temporal_performance")
def get_temporal_performance(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """D-002: 序盤(0-7点)・中盤(8-14点)・終盤(15点以降)の勝率を集計する"""
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    empty_confidence = check_confidence("temporal", 0)
    if not matches:
        return {
            "success": True,
            "data": {"phases": []},
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    match_ids = [m.id for m in matches]
    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, player_id) for m in matches
    }

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []

    # フェーズ別集計: score_a_after + score_b_after でラリー後の合計点を判断
    phases = {
        "序盤(0-7点)": {"wins": 0, "total": 0},
        "中盤(8-14点)": {"wins": 0, "total": 0},
        "終盤(15点以降)": {"wins": 0, "total": 0},
    }

    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        role = role_by_match[match_id]
        player_won = rally.winner == role

        # ラリー後のスコア合計から現在のフェーズを判定
        total_points = rally.score_a_after + rally.score_b_after
        if total_points <= 7:
            phase_key = "序盤(0-7点)"
        elif total_points <= 14:
            phase_key = "中盤(8-14点)"
        else:
            phase_key = "終盤(15点以降)"

        phases[phase_key]["total"] += 1
        if player_won:
            phases[phase_key]["wins"] += 1

    phase_list = []
    total_sample = 0
    for phase_name, stats in phases.items():
        total = stats["total"]
        total_sample += total
        win_rate = round(stats["wins"] / total, 3) if total else 0.0
        phase_list.append({
            "phase": phase_name,
            "win_rate": win_rate,
            "rally_count": total,
        })

    confidence = check_confidence("temporal", total_sample)

    return {
        "success": True,
        "data": {"phases": phase_list},
        "meta": {"sample_size": total_sample, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# D-003: 長ラリー後のパフォーマンス
# ---------------------------------------------------------------------------

@router.get("/analysis/post_long_rally_stats")
def get_post_long_rally_stats(
    player_id: int,
    threshold: int = Query(10, ge=1),
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """D-003: 長ラリー（threshold打以上）後の次ラリーのパフォーマンスを通常時と比較する"""
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    empty_confidence = check_confidence("descriptive_basic", 0)
    if not matches:
        return {
            "success": True,
            "data": {
                "normal": {"win_rate": 0.0, "avg_rally_length": 0.0, "count": 0},
                "post_long": {"win_rate": 0.0, "avg_rally_length": 0.0, "count": 0},
                "diff_win_rate": 0.0,
            },
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    match_ids = [m.id for m in matches]
    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, player_id) for m in matches
    }

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]

    rallies_all = (
        db.query(Rally)
        .filter(Rally.set_id.in_(set_ids))
        .order_by(Rally.set_id, Rally.rally_num)
        .all()
    ) if set_ids else []

    # セットごとにラリーをグループ化して時系列処理
    rallies_by_set: dict[int, list[Rally]] = defaultdict(list)
    for rally in rallies_all:
        rallies_by_set[rally.set_id].append(rally)

    normal = {"wins": 0, "total": 0, "total_length": 0}
    post_long = {"wins": 0, "total": 0, "total_length": 0}

    for set_id, set_rallies in rallies_by_set.items():
        match_id = set_to_match[set_id]
        role = role_by_match[match_id]
        prev_long = False

        for rally in set_rallies:
            player_won = rally.winner == role
            is_long = rally.rally_length >= threshold

            bucket = post_long if prev_long else normal
            bucket["total"] += 1
            bucket["total_length"] += rally.rally_length
            if player_won:
                bucket["wins"] += 1

            prev_long = is_long

    def _build(s: dict) -> dict:
        total = s["total"]
        win_rate = round(s["wins"] / total, 3) if total else 0.0
        avg_len = round(s["total_length"] / total, 2) if total else 0.0
        return {"win_rate": win_rate, "avg_rally_length": avg_len, "count": total}

    normal_stat = _build(normal)
    post_stat = _build(post_long)
    diff = round(post_stat["win_rate"] - normal_stat["win_rate"], 3)

    total_sample = normal["total"] + post_long["total"]
    confidence = check_confidence("descriptive_basic", total_sample)

    return {
        "success": True,
        "data": {
            "normal": normal_stat,
            "post_long": post_stat,
            "diff_win_rate": diff,
        },
        "meta": {"sample_size": total_sample, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# E-001: 対戦相手統計
# ---------------------------------------------------------------------------

@router.get("/analysis/opponent_stats")
def get_opponent_stats(player_id: int, db: Session = Depends(get_db)):
    """E-001: 過去に対戦した相手ごとの勝率・ラリー長を集計する"""
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
        )
        .all()
    )

    empty_confidence = check_confidence("opponent_analysis", 0)
    if not matches:
        return {
            "success": True,
            "data": {"opponents": []},
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    match_ids = [m.id for m in matches]
    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, player_id) for m in matches
    }

    # 対戦相手IDを抽出
    opponent_map: dict[int, int] = {}  # match_id -> opponent_id
    for m in matches:
        opp_id = m.player_b_id if m.player_a_id == player_id else m.player_a_id
        opponent_map[m.id] = opp_id

    opponent_ids = set(opponent_map.values())
    players_obj = db.query(Player).filter(Player.id.in_(opponent_ids)).all()
    player_name_map: dict[int, str] = {p.id: p.name for p in players_obj}

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []

    # 対戦相手ごとに集計
    opp_stats: dict[int, dict] = defaultdict(lambda: {
        "match_ids": set(), "wins": 0, "total_length": 0, "rally_count": 0
    })

    for m in matches:
        opp_id = opponent_map[m.id]
        opp_stats[opp_id]["match_ids"].add(m.id)
        role = role_by_match[m.id]
        result = m.result
        if role == "player_b":
            result = "win" if result == "loss" else ("loss" if result == "win" else result)
        if result == "win":
            opp_stats[opp_id]["wins"] += 1

    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        opp_id = opponent_map.get(match_id)
        if opp_id is None:
            continue
        opp_stats[opp_id]["total_length"] += rally.rally_length
        opp_stats[opp_id]["rally_count"] += 1

    opponents_list = []
    total_sample = 0
    for opp_id, stats in sorted(opp_stats.items()):
        match_count = len(stats["match_ids"])
        total_sample += stats["rally_count"]
        win_rate = round(stats["wins"] / match_count, 3) if match_count else 0.0
        avg_rally = round(stats["total_length"] / stats["rally_count"], 2) if stats["rally_count"] else 0.0
        opponents_list.append({
            "opponent_id": opp_id,
            "opponent_name": player_name_map.get(opp_id, "不明"),
            "match_count": match_count,
            "win_rate": win_rate,
            "avg_rally_length": avg_rally,
            "sample_size": stats["rally_count"],
        })

    confidence = check_confidence("opponent_analysis", total_sample)

    return {
        "success": True,
        "data": {"opponents": opponents_list},
        "meta": {"sample_size": total_sample, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# E-002: 対戦相手の課題ゾーン
# ---------------------------------------------------------------------------

@router.get("/analysis/opponent_vulnerability")
def get_opponent_vulnerability(opponent_id: int, db: Session = Depends(get_db)):
    """E-002: 対戦相手が失点しやすいゾーンを集計する"""
    # 相手が player_a / player_b として出場した試合
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == opponent_id) | (Match.player_b_id == opponent_id)
        )
        .all()
    )

    empty_confidence = check_confidence("heatmap", 0)
    if not matches:
        return {
            "success": True,
            "data": {"zone_loss_rates": {}, "weak_zones": []},
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, opponent_id) for m in matches
    }

    match_ids = [m.id for m in matches]
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    # 相手が失点したラリー
    lost_rally_ids: set[int] = set()
    rally_to_role: dict[int, str] = {}
    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        role = role_by_match[match_id]
        rally_to_role[rally.id] = role
        if rally.winner != role:
            lost_rally_ids.add(rally.id)

    rally_ids = [r.id for r in rallies]
    if not rally_ids:
        return {
            "success": True,
            "data": {"zone_loss_rates": {}, "weak_zones": []},
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    # 失点ラリーの着地ゾーンを集計（相手の最終打の着地点）
    strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(list(lost_rally_ids)))
        .order_by(Stroke.rally_id, Stroke.stroke_num)
        .all()
    )

    # ラリーごとの最終ストロークの着地ゾーン
    last_stroke_zone: dict[int, str] = {}
    strokes_by_rally: dict[int, list[Stroke]] = defaultdict(list)
    for stroke in strokes:
        strokes_by_rally[stroke.rally_id].append(stroke)

    for r_id, stks in strokes_by_rally.items():
        role = rally_to_role.get(r_id)
        if not role:
            continue
        # 相手（opponent）のストロークのみ
        opp_strokes = [s for s in stks if s.player != role]
        if opp_strokes:
            last = opp_strokes[-1]
            if last.land_zone:
                last_stroke_zone[r_id] = last.land_zone

    zone_loss_counts: dict[str, int] = defaultdict(int)
    total_losses = len(lost_rally_ids)
    for zone in last_stroke_zone.values():
        zone_loss_counts[zone] += 1

    zone_loss_rates = {
        zone: round(cnt / total_losses, 3) if total_losses else 0.0
        for zone, cnt in zone_loss_counts.items()
    }
    # 上位2ゾーン
    weak_zones = sorted(zone_loss_rates, key=lambda z: zone_loss_rates[z], reverse=True)[:2]

    confidence = check_confidence("heatmap", total_losses)

    return {
        "success": True,
        "data": {"zone_loss_rates": zone_loss_rates, "weak_zones": weak_zones},
        "meta": {"sample_size": total_losses, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# E-003: 対戦相手カード
# ---------------------------------------------------------------------------

@router.get("/analysis/opponent_card")
def get_opponent_card(opponent_id: int, db: Session = Depends(get_db)):
    """E-003: 対戦相手の基本情報・主要ショット・平均ラリー長をカード形式で返す"""
    opponent = db.get(Player, opponent_id)
    if not opponent:
        return {"success": False, "error": f"選手ID {opponent_id} が見つかりません"}

    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == opponent_id) | (Match.player_b_id == opponent_id)
        )
        .all()
    )

    empty_confidence = check_confidence("opponent_analysis", 0)
    if not matches:
        return {
            "success": True,
            "data": {
                "name": opponent.name,
                "match_count": 0,
                "top_shot": None,
                "avg_rally_length": 0.0,
                "serve_style": None,
                "serve_style_ja": None,
            },
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, opponent_id) for m in matches
    }
    match_ids = [m.id for m in matches]
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    rally_ids = [r.id for r in rallies]

    rally_to_role: dict[int, str] = {}
    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        rally_to_role[rally.id] = role_by_match[match_id]

    total_length = sum(r.rally_length for r in rallies)
    total_rallies = len(rallies)
    avg_rally = round(total_length / total_rallies, 2) if total_rallies else 0.0

    # 対戦相手のショット集計
    if rally_ids:
        strokes = (
            db.query(Stroke)
            .filter(Stroke.rally_id.in_(rally_ids))
            .all()
        )
        shot_counter: dict[str, int] = defaultdict(int)
        serve_counter: dict[str, int] = defaultdict(int)
        for stroke in strokes:
            role = rally_to_role.get(stroke.rally_id)
            if stroke.player == role:
                shot_counter[stroke.shot_type] += 1
                if stroke.stroke_num == 1:
                    serve_counter[stroke.shot_type] += 1
    else:
        shot_counter = defaultdict(int)
        serve_counter = defaultdict(int)

    top_shot = None
    if shot_counter:
        total_shots = sum(shot_counter.values())
        top_st = max(shot_counter, key=lambda k: shot_counter[k])
        top_shot = {
            "shot_type": top_st,
            "shot_type_ja": SHOT_TYPE_JA.get(top_st, top_st),
            "rate": round(shot_counter[top_st] / total_shots, 3) if total_shots else 0.0,
        }

    serve_style = None
    serve_style_ja = None
    if serve_counter:
        top_serve = max(serve_counter, key=lambda k: serve_counter[k])
        serve_style = top_serve
        serve_style_ja = SHOT_TYPE_JA.get(top_serve, top_serve)

    confidence = check_confidence("opponent_analysis", total_rallies)

    return {
        "success": True,
        "data": {
            "name": opponent.name,
            "match_count": len(matches),
            "top_shot": top_shot,
            "avg_rally_length": avg_rally,
            "serve_style": serve_style,
            "serve_style_ja": serve_style_ja,
        },
        "meta": {"sample_size": total_rallies, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# F-001: コートカバレッジ（試合内）
# ---------------------------------------------------------------------------

@router.get("/analysis/court_coverage_split")
def get_court_coverage_split(match_id: int, db: Session = Depends(get_db)):
    """F-001: 試合内のコート前後エリアカバレッジを集計する"""
    match = db.get(Match, match_id)
    if not match:
        return {"success": False, "error": f"試合ID {match_id} が見つかりません"}

    sets = db.query(GameSet).filter(GameSet.match_id == match_id).all()
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    rally_ids = [r.id for r in rallies]

    # シングルス判定
    is_singles = match.format == "singles" or match.partner_a_id is None

    # 集計対象プレイヤーを決定
    if is_singles:
        players_to_track = ["player_a", "player_b"]
    else:
        players_to_track = ["player_a", "partner_a"]

    # プレイヤーごとの前後エリアカウント
    area_counts: dict[str, dict] = {
        role: {"front": 0, "mid": 0, "back": 0, "total": 0}
        for role in players_to_track
    }

    if rally_ids:
        strokes = (
            db.query(Stroke)
            .filter(
                Stroke.rally_id.in_(rally_ids),
                Stroke.player.in_(players_to_track),
            )
            .all()
        )

        for stroke in strokes:
            role = stroke.player
            if role not in area_counts:
                continue
            area_counts[role]["total"] += 1
            # hit_y: y<0.4=前衛, y>0.6=後衛, それ以外=中間
            y = stroke.hit_y
            if y is not None:
                if y < AnalysisConfig.NET_FRONT_Y_THRESHOLD:
                    area_counts[role]["front"] += 1
                elif y > 0.6:
                    area_counts[role]["back"] += 1
                else:
                    area_counts[role]["mid"] += 1

    def _build_coverage(stats: dict) -> dict:
        total = stats["total"]
        return {
            "front_rate": round(stats["front"] / total, 3) if total else 0.0,
            "back_rate": round(stats["back"] / total, 3) if total else 0.0,
            "mid_rate": round(stats["mid"] / total, 3) if total else 0.0,
            "total_strokes": total,
        }

    result_key1 = players_to_track[0]
    result_key2 = players_to_track[1]
    cov1 = _build_coverage(area_counts[result_key1])
    cov2 = _build_coverage(area_counts[result_key2])

    # バランススコア: 前衛率の差が小さいほど1に近い
    balance_score = round(1.0 - abs(cov1["front_rate"] - cov2["front_rate"]), 3)

    total_sample = area_counts[result_key1]["total"] + area_counts[result_key2]["total"]
    confidence = check_confidence("descriptive_basic", total_sample)

    response_data: dict = {
        "balance_score": balance_score,
    }
    if is_singles:
        response_data["player_a"] = cov1
        response_data["player_b"] = cov2
    else:
        response_data["player_a"] = cov1
        response_data["partner_a"] = cov2

    return {
        "success": True,
        "data": response_data,
        "meta": {"sample_size": total_sample, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# F-002: パートナー別パフォーマンス比較（ダブルス）
# ---------------------------------------------------------------------------

@router.get("/analysis/partner_comparison")
def get_partner_comparison(player_id: int, db: Session = Depends(get_db)):
    """F-002: ダブルス試合におけるパートナー別の勝率・相乗効果スコアを返す"""
    # ダブルス試合のみ
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id),
            Match.format != "singles",
        )
        .all()
    )

    empty_confidence = check_confidence("descriptive_basic", 0)
    if not matches:
        return {
            "success": True,
            "data": {"partners": []},
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    # パートナーIDを抽出
    partner_map: dict[int, int | None] = {}  # match_id -> partner_id
    for m in matches:
        if m.player_a_id == player_id:
            partner_map[m.id] = m.partner_a_id
        else:
            partner_map[m.id] = m.partner_b_id

    partner_ids = {pid for pid in partner_map.values() if pid is not None}
    partners_obj = db.query(Player).filter(Player.id.in_(partner_ids)).all()
    partner_name_map: dict[int, str] = {p.id: p.name for p in partners_obj}

    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, player_id) for m in matches
    }

    # パートナーごとに集計
    partner_stats: dict[int, dict] = defaultdict(lambda: {"match_ids": set(), "wins": 0})

    for m in matches:
        partner_id = partner_map.get(m.id)
        if partner_id is None:
            continue
        partner_stats[partner_id]["match_ids"].add(m.id)
        role = role_by_match[m.id]
        result = m.result
        if role == "player_b":
            result = "win" if result == "loss" else ("loss" if result == "win" else result)
        if result == "win":
            partner_stats[partner_id]["wins"] += 1

    match_ids = [m.id for m in matches]
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]
    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []

    # パートナー別平均ラリー長
    partner_rally: dict[int, dict] = defaultdict(lambda: {"total_length": 0, "count": 0})
    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        partner_id = partner_map.get(match_id)
        if partner_id is None:
            continue
        partner_rally[partner_id]["total_length"] += rally.rally_length
        partner_rally[partner_id]["count"] += 1

    partners_list = []
    total_sample = 0
    for partner_id, stats in sorted(partner_stats.items()):
        match_count = len(stats["match_ids"])
        total_sample += match_count
        win_rate = round(stats["wins"] / match_count, 3) if match_count else 0.0
        avg_rally = round(
            partner_rally[partner_id]["total_length"] / partner_rally[partner_id]["count"], 2
        ) if partner_rally[partner_id]["count"] else 0.0
        # 相乗効果スコア: 勝率 × min(1, 試合数/5)
        synergy_score = round(win_rate * min(1.0, match_count / 5), 3)
        partners_list.append({
            "partner_id": partner_id,
            "partner_name": partner_name_map.get(partner_id, "不明"),
            "match_count": match_count,
            "win_rate": win_rate,
            "synergy_score": synergy_score,
            "avg_rally_length": avg_rally,
        })

    confidence = check_confidence("descriptive_basic", total_sample)

    return {
        "success": True,
        "data": {"partners": partners_list},
        "meta": {"sample_size": total_sample, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# F-003: ダブルスのサーブ/レシーブ分析
# ---------------------------------------------------------------------------

@router.get("/analysis/doubles_serve_receive")
def get_doubles_serve_receive(player_id: int, db: Session = Depends(get_db)):
    """F-003: ダブルス試合のサーブ側・レシーブ側ごとの勝率を集計する"""
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id),
            Match.format != "singles",
        )
        .all()
    )

    empty_confidence = check_confidence("descriptive_basic", 0)
    if not matches:
        return {
            "success": True,
            "data": {
                "serve_win_rate": 0.0,
                "receive_win_rate": 0.0,
                "serve_style": {"short_service": 0.0, "long_service": 0.0},
                "receive_zones": [],
            },
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    match_ids = [m.id for m in matches]
    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, player_id) for m in matches
    }

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    rally_ids = [r.id for r in rallies]

    serve_wins = 0
    serve_total = 0
    receive_wins = 0
    receive_total = 0

    rally_to_role: dict[int, str] = {}
    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        role = role_by_match[match_id]
        rally_to_role[rally.id] = role
        player_won = rally.winner == role
        is_server = rally.server == role

        if is_server:
            serve_total += 1
            if player_won:
                serve_wins += 1
        else:
            receive_total += 1
            if player_won:
                receive_wins += 1

    # サーブスタイル・レシーブゾーン集計
    if rally_ids:
        strokes = (
            db.query(Stroke)
            .filter(Stroke.rally_id.in_(rally_ids))
            .all()
        )
    else:
        strokes = []

    serve_style: dict[str, int] = defaultdict(int)
    receive_zone_wins: dict[str, dict] = defaultdict(lambda: {"wins": 0, "total": 0})

    strokes_by_rally: dict[int, list[Stroke]] = defaultdict(list)
    for stroke in strokes:
        strokes_by_rally[stroke.rally_id].append(stroke)

    for rally in rallies:
        role = rally_to_role.get(rally.id)
        stks = strokes_by_rally.get(rally.id, [])
        is_server = rally.server == role
        player_won = rally.winner == role

        if is_server:
            # サーブ（stroke_num=1）のショットタイプを集計
            serves = [s for s in stks if s.stroke_num == 1 and s.player == role]
            for s in serves:
                if s.shot_type in ("short_service", "long_service"):
                    serve_style[s.shot_type] += 1
        else:
            # レシーブ（stroke_num=2）のゾーンを集計
            returns = [s for s in stks if s.stroke_num == 2 and s.player == role]
            for s in returns:
                zone = s.land_zone or "unknown"
                receive_zone_wins[zone]["total"] += 1
                if player_won:
                    receive_zone_wins[zone]["wins"] += 1

    total_serves = sum(serve_style.values())
    serve_style_rates = {
        st: round(cnt / total_serves, 3) if total_serves else 0.0
        for st, cnt in serve_style.items()
    }

    receive_zones = [
        {
            "zone": zone,
            "count": stats["total"],
            "win_rate": round(stats["wins"] / stats["total"], 3) if stats["total"] else 0.0,
        }
        for zone, stats in sorted(receive_zone_wins.items())
    ]

    total_sample = serve_total + receive_total
    confidence = check_confidence("descriptive_basic", total_sample)

    return {
        "success": True,
        "data": {
            "serve_win_rate": round(serve_wins / serve_total, 3) if serve_total else 0.0,
            "receive_win_rate": round(receive_wins / receive_total, 3) if receive_total else 0.0,
            "serve_style": serve_style_rates,
            "receive_zones": receive_zones,
        },
        "meta": {"sample_size": total_sample, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# F-004: ストローク分担率（ダブルス）
# ---------------------------------------------------------------------------

@router.get("/analysis/stroke_sharing")
def get_stroke_sharing(player_id: int, db: Session = Depends(get_db)):
    """F-004: ダブルス試合でのラリー内ストローク分担バランスを集計する"""
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id),
            Match.format != "singles",
        )
        .all()
    )

    empty_confidence = check_confidence("descriptive_basic", 0)
    if not matches:
        return {
            "success": True,
            "data": {
                "balanced_win_rate": 0.0,
                "imbalanced_win_rate": 0.0,
                "balanced_count": 0,
                "imbalanced_count": 0,
                "avg_balance_ratio": 0.0,
            },
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    match_ids = [m.id for m in matches]
    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, player_id) for m in matches
    }
    # パートナーロール
    partner_role_map: dict[int, str] = {}
    for m in matches:
        if m.player_a_id == player_id:
            partner_role_map[m.id] = "partner_a"
        else:
            partner_role_map[m.id] = "partner_b"

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []
    rally_ids = [r.id for r in rallies]

    rally_to_role: dict[int, str] = {}
    rally_to_partner: dict[int, str] = {}
    rally_player_won: dict[int, bool] = {}
    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        role = role_by_match[match_id]
        rally_to_role[rally.id] = role
        rally_to_partner[rally.id] = partner_role_map[match_id]
        rally_player_won[rally.id] = rally.winner == role

    if not rally_ids:
        return {
            "success": True,
            "data": {
                "balanced_win_rate": 0.0,
                "imbalanced_win_rate": 0.0,
                "balanced_count": 0,
                "imbalanced_count": 0,
                "avg_balance_ratio": 0.0,
            },
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    all_strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(rally_ids))
        .all()
    )

    strokes_by_rally: dict[int, list[Stroke]] = defaultdict(list)
    for stroke in all_strokes:
        strokes_by_rally[stroke.rally_id].append(stroke)

    balanced_wins = 0
    balanced_total = 0
    imbalanced_wins = 0
    imbalanced_total = 0
    total_balance_ratio = 0.0
    total_rallies = 0

    for rally in rallies:
        r_id = rally.id
        player_role = rally_to_role.get(r_id)
        partner_role = rally_to_partner.get(r_id)
        stks = strokes_by_rally.get(r_id, [])

        player_count = sum(1 for s in stks if s.player == player_role)
        partner_count = sum(1 for s in stks if s.player == partner_role)
        team_total = player_count + partner_count
        if team_total == 0:
            continue

        # バランス比率: 0.5に近いほどバランスが取れている
        balance_ratio = min(player_count, partner_count) / team_total
        total_balance_ratio += balance_ratio
        total_rallies += 1

        player_won = rally_player_won.get(r_id, False)
        # balance_ratio >= 0.35をバランス取れている基準とする
        if balance_ratio >= AnalysisConfig.BALANCE_RATIO_MIN:
            balanced_total += 1
            if player_won:
                balanced_wins += 1
        else:
            imbalanced_total += 1
            if player_won:
                imbalanced_wins += 1

    avg_balance_ratio = round(total_balance_ratio / total_rallies, 3) if total_rallies else 0.0
    balanced_win_rate = round(balanced_wins / balanced_total, 3) if balanced_total else 0.0
    imbalanced_win_rate = round(imbalanced_wins / imbalanced_total, 3) if imbalanced_total else 0.0

    confidence = check_confidence("descriptive_basic", total_rallies)

    return {
        "success": True,
        "data": {
            "balanced_win_rate": balanced_win_rate,
            "imbalanced_win_rate": imbalanced_win_rate,
            "balanced_count": balanced_total,
            "imbalanced_count": imbalanced_total,
            "avg_balance_ratio": avg_balance_ratio,
        },
        "meta": {"sample_size": total_rallies, "confidence": confidence},
    }


# ─── R-006: 速報 flash_advice ─────────────────────────────────────────────────

@router.get("/analysis/flash_advice")
def get_flash_advice(
    match_id: int,
    as_of_set: int,
    player_id: int,
    as_of_rally_num: int | None = None,
    db: Session = Depends(get_db),
):
    """速報5+6+7ルール: インターバル/セット間で使う短い助言を5〜7項目生成する。"""

    from collections import Counter

    # --- 対象ラリー取得（as_of_set + as_of_rally_num でフィルタ） ---
    sets_q = db.query(GameSet).filter(GameSet.match_id == match_id).order_by(GameSet.set_num)
    sets = sets_q.all()
    if not sets:
        return {"success": True, "data": {"items": [], "item_count": 0, "extended_items_included": False},
                "meta": {"sample_size": 0, "confidence": check_confidence("descriptive_basic", 0)}}

    # 対象セット
    target_set = next((s for s in sets if s.set_num == as_of_set), None)
    if not target_set:
        return {"success": True, "data": {"items": [], "item_count": 0, "extended_items_included": False},
                "meta": {"sample_size": 0, "confidence": check_confidence("descriptive_basic", 0)}}

    # 対象プレイヤーのロール確認
    match = db.query(Match).filter(Match.id == match_id).first()
    if not match:
        return {"success": True, "data": {"items": [], "item_count": 0, "extended_items_included": False},
                "meta": {"sample_size": 0, "confidence": check_confidence("descriptive_basic", 0)}}

    # ダブルスのパートナーも含めてロール決定
    player_role = "player_a" if (match.player_a_id == player_id or match.partner_a_id == player_id) else "player_b"
    opp_role = "player_b" if player_role == "player_a" else "player_a"

    # セット内ラリー
    rally_q = db.query(Rally).filter(Rally.set_id == target_set.id).order_by(Rally.rally_num)
    if as_of_rally_num is not None:
        rally_q = rally_q.filter(Rally.rally_num <= as_of_rally_num)
    rallies = rally_q.all()

    sample_size = len(rallies)
    if sample_size == 0:
        return {"success": True, "data": {"items": [], "item_count": 0, "extended_items_included": False},
                "meta": {"sample_size": 0, "confidence": check_confidence("descriptive_basic", 0)}}

    # 直近5ラリー
    recent_rallies = rallies[-5:]
    rally_ids = [r.id for r in rallies]
    recent_ids = [r.id for r in recent_rallies]

    # --- ストローク取得 ---
    all_strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(rally_ids))
        .order_by(Stroke.rally_id, Stroke.stroke_num)
        .all()
    )
    recent_strokes = [s for s in all_strokes if s.rally_id in recent_ids]

    strokes_by_rally: dict[int, list] = {}
    for s in all_strokes:
        strokes_by_rally.setdefault(s.rally_id, []).append(s)

    # --- 勝敗マップ ---
    win_rallies = {r.id for r in rallies if r.winner == player_role}
    loss_rallies = {r.id for r in rallies if r.winner == opp_role}

    # ── 1. danger: 直近5ラリーの失点ショット傾向 ──────────────────────────────
    recent_loss_shots = [
        s.shot_type for s in recent_strokes
        if s.rally_id in {r.id for r in recent_rallies if r.winner == opp_role}
        and s.player == opp_role
        and s.shot_type
    ]
    danger_body = "直近5ラリーでは失点の特定パターンが見られません"
    if recent_loss_shots:
        top_shot, top_cnt = Counter(recent_loss_shots).most_common(1)[0]
        total_recent_loss = len([r for r in recent_rallies if r.winner == opp_role])
        shot_label = _shot_ja(top_shot)
        danger_body = f"直近で相手の「{shot_label}」による失点が{top_cnt}回（直近{len(recent_rallies)}ラリー中）"

    # ── 2. opportunity: 得点率が高い自分のショット ────────────────────────────
    player_win_shots = [
        s.shot_type for s in all_strokes
        if s.rally_id in win_rallies and s.player == player_role and s.shot_type
    ]
    opportunity_body = "有効な攻め口のデータが不足しています"
    if player_win_shots:
        shot_counts = Counter(player_win_shots)
        top_shot = shot_counts.most_common(1)[0][0]
        # 全ラリー中でのそのショット勝率
        shot_rallies_win = sum(
            1 for s in all_strokes
            if s.shot_type == top_shot and s.player == player_role and s.rally_id in win_rallies
        )
        shot_rallies_total = sum(
            1 for s in all_strokes
            if s.shot_type == top_shot and s.player == player_role
        )
        win_pct = round(shot_rallies_win / shot_rallies_total * 100) if shot_rallies_total else 0
        shot_label = _shot_ja(top_shot)
        opportunity_body = f"「{shot_label}」での得点が多い（このセット勝率 {win_pct}%）"

    # ── 3. pattern: セット全体の失点前3球のショット傾向 ──────────────────────
    pre_loss_3 = []
    for rid in loss_rallies:
        strokes = strokes_by_rally.get(rid, [])
        # 最後から3球目以前のショット（失点直前）
        if len(strokes) >= 3:
            pre_loss_3.append(strokes[-3].shot_type)
        elif len(strokes) >= 2:
            pre_loss_3.append(strokes[-2].shot_type)
    pattern_body = "ラリーパターンのデータが不足しています"
    if pre_loss_3:
        top_pre, cnt = Counter([s for s in pre_loss_3 if s]).most_common(1)[0]
        pattern_body = f"失点の{cnt}回でラリー中盤に「{_shot_ja(top_pre)}」が多い"

    # ── 4. opponent: 相手の直近多用ショット ──────────────────────────────────
    opp_recent = [
        s.shot_type for s in recent_strokes
        if s.player == opp_role and s.shot_type
    ]
    opponent_body = "相手の直近ショットデータが不足しています"
    if opp_recent:
        top_opp, cnt = Counter(opp_recent).most_common(1)[0]
        opponent_body = f"直近{len(recent_rallies)}ラリーで相手は「{_shot_ja(top_opp)}」を多用（{cnt}回）"

    # ── 5. next_action: danger + opportunity から1文推奨 ─────────────────────
    if player_win_shots and recent_loss_shots:
        top_win = _shot_ja(Counter(player_win_shots).most_common(1)[0][0])
        next_body = f"「{top_win}」を積極的に使い、相手の得意コースへの返球を避けること"
    elif player_win_shots:
        top_win = _shot_ja(Counter(player_win_shots).most_common(1)[0][0])
        next_body = f"「{top_win}」を中心に攻め続けること"
    else:
        next_body = "相手の多用ショットへの対応を優先すること"

    items = [
        {"category": "danger",      "title": "直近の失点パターン",   "body": danger_body,      "priority": 1},
        {"category": "opportunity", "title": "有効な攻め口",         "body": opportunity_body, "priority": 2},
        {"category": "pattern",     "title": "ラリー展開の傾向",     "body": pattern_body,     "priority": 3},
        {"category": "opponent",    "title": "相手の多用ショット",   "body": opponent_body,    "priority": 4},
        {"category": "next_action", "title": "次に試す戦術",         "body": next_body,        "priority": 5},
    ]

    # ── 6/7. 拡張項目（confidence >= medium 時のみ） ─────────────────────────
    confidence = check_confidence("descriptive_basic", sample_size)
    extended = False
    if confidence["level"] in ("medium", "high"):
        # 6. trend: 前半/後半勝率比較
        mid = len(rallies) // 2
        first_half = rallies[:mid]
        second_half = rallies[mid:]
        def win_rate(rs: list) -> float:
            if not rs:
                return 0.0
            return round(sum(1 for r in rs if r.winner == player_role) / len(rs), 3)
        wr_first = win_rate(first_half)
        wr_second = win_rate(second_half)
        delta = round(wr_second - wr_first, 3)
        if delta > 0.05:
            trend_body = f"後半の勝率が上昇傾向（前半{wr_first*100:.0f}% → 後半{wr_second*100:.0f}%）"
        elif delta < -0.05:
            trend_body = f"後半の勝率が低下傾向（前半{wr_first*100:.0f}% → 後半{wr_second*100:.0f}%）"
        else:
            trend_body = f"前後半で勝率に大きな変化なし（前半{wr_first*100:.0f}%・後半{wr_second*100:.0f}%）"
        items.append({"category": "trend", "title": "セット内勝率トレンド", "body": trend_body, "priority": 6})

        # 7. fatigue_signal: 長ラリー後のパフォーマンス低下
        long_rally_threshold = AnalysisConfig.LONG_RALLY_THRESHOLD
        long_rallies = [r for r in rallies if (r.rally_length or 0) >= long_rally_threshold]
        if long_rallies:
            # 長ラリー後（次のラリー）の勝率
            long_ids = {r.id for r in long_rallies}
            rally_list = list(rallies)
            post_long_results = []
            for i, r in enumerate(rally_list[:-1]):
                if r.id in long_ids:
                    nxt = rally_list[i + 1]
                    post_long_results.append(nxt.winner == player_role)
            if post_long_results:
                post_win_rate = round(sum(post_long_results) / len(post_long_results) * 100)
                if post_win_rate < 40:
                    fatigue_body = f"長ラリー（{long_rally_threshold}球以上）後の次ラリー勝率が{post_win_rate}%と低い — 消耗に注意"
                elif post_win_rate > 60:
                    fatigue_body = f"長ラリー後も勝率{post_win_rate}%を維持 — 体力面の安定が見られる"
                else:
                    fatigue_body = f"長ラリー後の勝率は{post_win_rate}%（特異な傾向なし）"
                items.append({"category": "fatigue_signal", "title": "長ラリー後のパフォーマンス", "body": fatigue_body, "priority": 7})

        extended = True

    return {
        "success": True,
        "data": {
            "items": sorted(items, key=lambda x: x["priority"]),
            "item_count": len(items),
            "extended_items_included": extended,
        },
        "meta": {"sample_size": sample_size, "confidence": confidence},
    }


# ─── Phase 2: 継続成長ビュー ───────────────────────────────────────────────────

@router.get("/analysis/growth_timeline")
def get_growth_timeline(
    player_id: int,
    metric: str = Query("win_rate", pattern="^(win_rate|avg_rally_length|serve_win_rate)$"),
    window_size: int = Query(3, ge=2, le=10),
    db: Session = Depends(get_db),
):
    """試合軸×指標の時系列データと移動平均を返す。"""

    # 対象試合（日付昇順）
    matches = (
        db.query(Match)
        .filter((Match.player_a_id == player_id) | (Match.player_b_id == player_id))
        .order_by(Match.date)
        .all()
    )
    if not matches:
        return {"success": True, "data": {"points": [], "trend": "pending", "trend_delta": 0.0,
                                          "weighted_trend": "pending", "weighted_trend_delta": 0.0},
                "meta": {"sample_size": 0, "confidence": check_confidence("descriptive_basic", 0)}}

    # growth_engine: 強度重み付きポイント計算
    raw_points = growth_points_weighted(matches, player_id, db, metric=metric)
    points = strength_weighted_moving_avg(raw_points, window_size=window_size)

    # トレンド判定（通常値 + 強度補正値）
    trend_info = compute_growth_trend(
        points, window_size=window_size, metric=metric,
        trend_delta=AnalysisConfig.GROWTH_TREND_DELTA,
    )

    confidence = check_confidence("descriptive_basic", len(points))
    return {
        "success": True,
        "data": {
            "points": points,
            "trend": trend_info["trend"],
            "trend_delta": trend_info["trend_delta"],
            "weighted_trend": trend_info["weighted_trend"],
            "weighted_trend_delta": trend_info["weighted_trend_delta"],
        },
        "meta": {"sample_size": len(points), "confidence": confidence},
    }


@router.get("/analysis/growth_judgment")
def get_growth_judgment(
    player_id: int,
    min_matches: int = Query(5, ge=1, le=20),
    db: Session = Depends(get_db),
):
    """複数指標を横断した成長判定（improving/stable/declining/pending）を返す。"""

    matches = (
        db.query(Match)
        .filter((Match.player_a_id == player_id) | (Match.player_b_id == player_id))
        .order_by(Match.date)
        .all()
    )
    match_count = len(matches)

    if match_count < min_matches:
        return {
            "success": True,
            "data": {
                "judgment": "pending",
                "judgment_ja": "判定保留",
                "metrics": {},
                "match_count": match_count,
                "min_matches_required": min_matches,
            },
            "meta": {"sample_size": match_count, "confidence": check_confidence("descriptive_basic", match_count)},
        }

    metrics_result = {}

    for metric in ("win_rate", "serve_win_rate"):
        # growth_engine: 強度重み付きポイントで計算
        raw_pts = growth_points_weighted(matches, player_id, db, metric=metric)
        annotated = len(raw_pts)
        window = max(2, annotated // 3)
        if annotated < max(window * 2, min_matches):
            metrics_result[metric] = {
                "trend": "pending", "delta": 0.0,
                "weighted_trend": "pending", "weighted_delta": 0.0,
            }
            continue

        pts_with_avg = strength_weighted_moving_avg(raw_pts, window_size=window)
        trend_info = compute_growth_trend(
            pts_with_avg, window_size=window, metric=metric,
            trend_delta=AnalysisConfig.GROWTH_TREND_DELTA,
        )
        metrics_result[metric] = {
            "trend": trend_info["trend"],
            "delta": trend_info["trend_delta"],
            "weighted_trend": trend_info["weighted_trend"],
            "weighted_delta": trend_info["weighted_trend_delta"],
        }

    # 総合判定（通常 + 重み付き両方を考慮）
    trends = [v["trend"] for v in metrics_result.values() if v["trend"] != "pending"]
    trends += [v["weighted_trend"] for v in metrics_result.values() if v.get("weighted_trend", "pending") != "pending"]
    improving_count = trends.count("improving")
    declining_count = trends.count("declining")

    if not trends:
        judgment = "pending"
        judgment_ja = "判定保留"
    elif improving_count >= 2 and declining_count == 0:
        judgment = "improving"
        judgment_ja = "改善傾向"
    elif declining_count >= 2 and improving_count == 0:
        judgment = "declining"
        judgment_ja = "悪化傾向"
    else:
        judgment = "stable"
        judgment_ja = "横ばい"

    # アノテーション済み試合数（ラリーデータが存在する試合）
    annotated_match_count = sum(
        1 for m in matches
        if db.query(GameSet).filter(GameSet.match_id == m.id).first() is not None
        and db.query(Rally).filter(
            Rally.set_id.in_([s.id for s in db.query(GameSet).filter(GameSet.match_id == m.id).all()])
        ).first() is not None
    )

    return {
        "success": True,
        "data": {
            "judgment": judgment,
            "judgment_ja": judgment_ja,
            "metrics": metrics_result,
            "match_count": match_count,
            "annotated_match_count": annotated_match_count,
            "min_matches_required": min_matches,
        },
        "meta": {"sample_size": annotated_match_count},
    }


# ─── 事前観察条件別勝率分析（PREMATCH_OBSERVATION_ANALYTICS） ────────────────

@router.get("/analysis/observation_analytics")
def get_observation_analytics(
    player_id: int,
    db: Session = Depends(get_db),
):
    """試合前観察記録を使った対戦相手条件別勝率分析 + 自コンディション分析。

    - splits: 相手への観察記録（利き手・テーピング等）に基づく勝率スプリット
    - self_observations: 自コンディション（self_condition/self_timing）ごとの勝率

    少数サンプル・主観的データのため補助インサイトとして提示すること。
    """
    from backend.routers.warmup import SELF_CONDITION_TYPES

    matches = db.query(Match).filter(
        (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
    ).all()

    if not matches:
        return {
            "success": True,
            "data": {"splits": [], "observation_count": 0, "self_observations": []},
            "meta": {"sample_size": 0},
        }

    CONF_PRIORITY = {"confirmed": 4, "likely": 3, "tentative": 2, "unknown": 1}

    # ─── 相手観察スプリット ───────────────────────────────────────────
    # (observation_type, observation_value) → {wins, total, confidence_levels, match_ids}
    splits: dict[tuple[str, str], dict] = {}

    # ─── 自コンディションスプリット ──────────────────────────────────
    self_splits: dict[tuple[str, str], dict] = {}

    for m in matches:
        is_player_a = m.player_a_id == player_id
        opponent_id = m.player_b_id if is_player_a else m.player_a_id
        won = (is_player_a and m.result == "win") or (not is_player_a and m.result == "loss")

        # 相手への観察（opponent_id でフィルタ、自コンディション除外）
        opp_obs = (
            db.query(PreMatchObservation)
            .filter(
                PreMatchObservation.match_id == m.id,
                PreMatchObservation.player_id == opponent_id,
                PreMatchObservation.observation_type.notin_(SELF_CONDITION_TYPES),
            )
            .all()
        )
        for obs in opp_obs:
            key = (obs.observation_type, obs.observation_value)
            if key not in splits:
                splits[key] = {"wins": 0, "total": 0, "confidence_levels": [], "match_ids": []}
            splits[key]["total"] += 1
            if won:
                splits[key]["wins"] += 1
            splits[key]["confidence_levels"].append(obs.confidence_level)
            splits[key]["match_ids"].append(m.id)

        # 自コンディション観察（player_id = self, observation_type in SELF_CONDITION_TYPES）
        self_obs = (
            db.query(PreMatchObservation)
            .filter(
                PreMatchObservation.match_id == m.id,
                PreMatchObservation.player_id == player_id,
                PreMatchObservation.observation_type.in_(SELF_CONDITION_TYPES),
            )
            .all()
        )
        for obs in self_obs:
            key = (obs.observation_type, obs.observation_value)
            if key not in self_splits:
                self_splits[key] = {"wins": 0, "total": 0, "confidence_levels": [], "match_ids": []}
            self_splits[key]["total"] += 1
            if won:
                self_splits[key]["wins"] += 1
            self_splits[key]["confidence_levels"].append(obs.confidence_level)
            self_splits[key]["match_ids"].append(m.id)

    def _build_splits(raw: dict) -> list:
        result = []
        for (obs_type, obs_value), stats in raw.items():
            total = stats["total"]
            win_rate = round(stats["wins"] / total, 3) if total > 0 else 0.0
            min_conf = min(stats["confidence_levels"], key=lambda c: CONF_PRIORITY.get(c, 0))
            result.append({
                "observation_type": obs_type,
                "observation_value": obs_value,
                "win_rate": win_rate,
                "wins": stats["wins"],
                "match_count": total,
                "confidence": min_conf,
            })
        result.sort(key=lambda x: (-x["match_count"], -x["win_rate"]))
        return result

    result_splits = _build_splits(splits)
    result_self = _build_splits(self_splits)

    matched_match_ids: set[int] = set()
    for stats in list(splits.values()) + list(self_splits.values()):
        matched_match_ids.update(stats["match_ids"])

    return {
        "success": True,
        "data": {
            "splits": result_splits,
            "observation_count": sum(s["total"] for s in splits.values()),
            "self_observations": result_self,
        },
        "meta": {"sample_size": len(matched_match_ids)},
    }
