"""analysis_stable.py — stable tier 解析エンドポイント"""
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

router = APIRouter()


# ---------------------------------------------------------------------------
# 1. Descriptive statistics
# ---------------------------------------------------------------------------

@router.get("/analysis/descriptive")
def get_descriptive(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    match_ids = [m.id for m in matches]
    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, player_id)
        for m in matches
    }

    # 対象試合のセットを取得
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all() if match_ids else []
    set_ids = [s.id for s in sets]
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}

    # 対象セットのラリーを取得
    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []

    total_rallies = len(rallies)
    wins = 0
    total_length = 0
    end_type_dist: dict[str, int] = defaultdict(int)
    length_hist: dict[int, int] = defaultdict(int)
    win_by_end_type: dict[str, dict[str, int]] = defaultdict(lambda: {"wins": 0, "total": 0})
    server_wins = 0
    server_total = 0
    receiver_wins = 0
    receiver_total = 0

    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        player_role = role_by_match[match_id]
        player_won = rally.winner == player_role

        if player_won:
            wins += 1

        total_length += rally.rally_length
        end_type_dist[rally.end_type] += 1
        length_hist[rally.rally_length] += 1

        # end_type別の勝利/合計を集計
        win_by_end_type[rally.end_type]["total"] += 1
        if player_won:
            win_by_end_type[rally.end_type]["wins"] += 1

        # サーブ側勝率
        is_server = rally.server == player_role
        if is_server:
            server_total += 1
            if player_won:
                server_wins += 1
        else:
            receiver_total += 1
            if player_won:
                receiver_wins += 1

    win_rate = round(wins / total_rallies, 3) if total_rallies else 0.0
    avg_rally_length = round(total_length / total_rallies, 3) if total_rallies else 0.0

    rally_length_histogram = [
        {"length": length, "count": count}
        for length, count in sorted(length_hist.items())
    ]

    server_win_rate = {
        "as_server": round(server_wins / server_total, 3) if server_total else 0.0,
        "as_receiver": round(receiver_wins / receiver_total, 3) if receiver_total else 0.0,
    }

    confidence = check_confidence("descriptive_basic", total_rallies)

    return {
        "success": True,
        "data": {
            "total_matches": len(matches),
            "total_rallies": total_rallies,
            "win_rate": win_rate,
            "avg_rally_length": avg_rally_length,
            "end_type_distribution": dict(end_type_dist),
            "rally_length_histogram": rally_length_histogram,
            "win_by_end_type": {k: v for k, v in win_by_end_type.items()},
            "server_win_rate": server_win_rate,
        },
        "meta": {
            "sample_size": total_rallies,
            "confidence": confidence,
        },
    }


# ---------------------------------------------------------------------------
# 2. Heatmap
# ---------------------------------------------------------------------------

@router.get("/analysis/heatmap")
def get_heatmap(
    player_id: int,
    type: str = Query("hit", pattern="^(hit|land)$"),
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    match_id: Optional[int] = Query(None),
    match_ids: Optional[str] = Query(None),  # カンマ区切り match ID リスト（直近N試合用）
    db: Session = Depends(get_db),
):
    ALL_ZONES = ["BL", "BC", "BR", "ML", "MC", "MR", "NL", "NC", "NR"]

    # match_ids（直近N試合など複数指定）優先 → match_id（単一）→ 全期間
    if match_ids is not None:
        id_list = [int(x) for x in match_ids.split(",") if x.strip().lstrip("-").isdigit()]
        _matches = db.query(Match).filter(Match.id.in_(id_list)).all() if id_list else []
    elif match_id is not None:
        m = db.query(Match).filter(Match.id == match_id).first()
        if m is None:
            _matches = []
        else:
            _matches = [m]
    else:
        _matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    match_ids_as_a = [m.id for m in _matches if m.player_a_id == player_id]
    match_ids_as_b = [m.id for m in _matches if m.player_b_id == player_id]

    zone_col = Stroke.hit_zone if type == "hit" else Stroke.land_zone

    zone_counts: dict[str, int] = defaultdict(int, {z: 0 for z in ALL_ZONES})
    total_strokes = 0

    def _count_strokes(match_ids: list[int], player_role: str) -> None:
        nonlocal total_strokes
        if not match_ids:
            return
        set_ids = [
            s.id
            for s in db.query(GameSet.id).filter(GameSet.match_id.in_(match_ids)).all()
        ]
        if not set_ids:
            return
        rally_ids = [
            r.id
            for r in db.query(Rally.id).filter(Rally.set_id.in_(set_ids)).all()
        ]
        if not rally_ids:
            return
        rows = (
            db.query(zone_col)
            .filter(
                Stroke.rally_id.in_(rally_ids),
                Stroke.player == player_role,
                zone_col.isnot(None),
            )
            .all()
        )
        for (zone,) in rows:
            zone_counts[zone] += 1
            total_strokes += 1

    _count_strokes(match_ids_as_a, "player_a")
    _count_strokes(match_ids_as_b, "player_b")

    confidence = check_confidence("heatmap", total_strokes)

    return {
        "success": True,
        "data": dict(zone_counts),
        "meta": {
            "sample_size": total_strokes,
            "confidence": confidence,
        },
    }


@router.get("/analysis/heatmap_zone_detail")
def get_heatmap_zone_detail(
    player_id: int,
    type: str = Query("hit", pattern="^(hit|land)$"),
    zone: str = Query(...),
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    match_id: Optional[int] = Query(None),
    match_ids: Optional[str] = Query(None),  # カンマ区切り match ID リスト（直近N試合用）
    db: Session = Depends(get_db),
):
    """ゾーン別詳細: 特定ゾーンのショットタイプ分布・勝率・遷移先（type=hit時）を返す"""
    # 試合絞り込み: match_ids（複数）優先 → match_id（単一）→ 全期間
    if match_ids is not None:
        id_list = [int(x) for x in match_ids.split(",") if x.strip().lstrip("-").isdigit()]
        _matches = db.query(Match).filter(Match.id.in_(id_list)).all() if id_list else []
    elif match_id is not None:
        m = db.query(Match).filter(Match.id == match_id).first()
        _matches = [m] if m else []
    else:
        _matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    match_ids_as_a = [m.id for m in _matches if m.player_a_id == player_id]
    match_ids_as_b = [m.id for m in _matches if m.player_b_id == player_id]

    zone_col = Stroke.hit_zone if type == "hit" else Stroke.land_zone

    shot_type_counts: dict[str, int] = defaultdict(int)
    land_zone_counts: dict[str, int] = defaultdict(int)  # type=hit 時の着地分布
    total = 0
    wins = 0

    def _collect(match_ids: list[int], player_role: str) -> None:
        nonlocal total, wins
        if not match_ids:
            return
        set_ids = [s.id for s in db.query(GameSet.id).filter(GameSet.match_id.in_(match_ids)).all()]
        if not set_ids:
            return
        rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all()
        rally_map = {r.id: r for r in rallies}
        if not rally_map:
            return

        rows = (
            db.query(Stroke)
            .filter(
                Stroke.rally_id.in_(list(rally_map.keys())),
                Stroke.player == player_role,
                zone_col == zone,
            )
            .all()
        )
        for stroke in rows:
            total += 1
            rally = rally_map.get(stroke.rally_id)
            if rally and rally.winner == player_role:
                wins += 1
            if stroke.shot_type:
                shot_type_counts[stroke.shot_type] += 1
            # hit_zone の場合は land_zone 分布も集計
            if type == "hit" and stroke.land_zone:
                land_zone_counts[stroke.land_zone] += 1

    _collect(match_ids_as_a, "player_a")
    _collect(match_ids_as_b, "player_b")

    win_rate = round(wins / total, 3) if total > 0 else None

    top_shot_types = sorted(shot_type_counts.items(), key=lambda x: -x[1])[:5]
    transitions = sorted(land_zone_counts.items(), key=lambda x: -x[1])[:5]

    return {
        "success": True,
        "data": {
            "zone": zone,
            "type": type,
            "count": total,
            "wins": wins,
            "win_rate": win_rate,
            "top_shot_types": [{"shot_type": k, "count": v} for k, v in top_shot_types],
            "transitions": [{"zone": k, "count": v} for k, v in transitions],
        },
        "meta": {"sample_size": total},
    }


# ---------------------------------------------------------------------------
# 3. Shot types
# ---------------------------------------------------------------------------

@router.get("/analysis/shot_types")
def get_shot_types(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)
    if not matches:
        return {"success": True, "data": []}

    match_ids = [m.id for m in matches]
    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, player_id)
        for m in matches
    }

    # セット・ラリーを取得
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_ids = [s.id for s in sets]
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}

    if not set_ids:
        return {"success": True, "data": []}

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all()
    rally_ids = [r.id for r in rallies]

    # ラリーごとにプレイヤーが勝ったかを判定
    rally_player_won: dict[int, bool] = {}
    rally_to_role: dict[int, str] = {}
    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        player_role = role_by_match[match_id]
        rally_to_role[rally.id] = player_role
        rally_player_won[rally.id] = rally.winner == player_role

    if not rally_ids:
        return {"success": True, "data": []}

    all_strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(rally_ids))
        .order_by(Stroke.rally_id, Stroke.stroke_num)
        .all()
    )

    # ラリーごとにストロークをグループ化
    strokes_by_rally: dict[int, list[Stroke]] = defaultdict(list)
    for stroke in all_strokes:
        strokes_by_rally[stroke.rally_id].append(stroke)

    # プレイヤーのshot_typeごとの総打数を集計
    shot_total: dict[str, int] = defaultdict(int)
    for stroke in all_strokes:
        r_id = stroke.rally_id
        player_role = rally_to_role.get(r_id)
        if stroke.player == player_role:
            shot_total[stroke.shot_type] += 1

    # 勝利ラリーにおけるプレイヤー最終打のshot_typeを集計
    shot_win_last: dict[str, int] = defaultdict(int)
    for r_id, strokes in strokes_by_rally.items():
        if not rally_player_won.get(r_id, False):
            continue
        player_role = rally_to_role.get(r_id)
        player_strokes = [s for s in strokes if s.player == player_role]
        if player_strokes:
            last = player_strokes[-1]
            shot_win_last[last.shot_type] += 1

    result = []
    for shot_type, total in sorted(shot_total.items()):
        wins = shot_win_last.get(shot_type, 0)
        win_rate = round(wins / total, 3) if total else 0.0
        result.append({"shot_type": shot_type, "count": total, "win_rate": win_rate})

    return {"success": True, "data": result}


# ---------------------------------------------------------------------------
# 4. Matches summary
# ---------------------------------------------------------------------------

@router.get("/analysis/matches_summary")
def get_matches_summary(player_id: int, db: Session = Depends(get_db)):
    # ダブルスのパートナーとして登録されている試合も含める
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) |
            (Match.player_b_id == player_id) |
            (Match.partner_a_id == player_id) |
            (Match.partner_b_id == player_id)
        )
        .all()
    )

    if not matches:
        return {"success": True, "data": []}

    # セット・ラリー数を一括取得
    match_ids = [m.id for m in matches]
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []

    rally_count_by_match: dict[int, int] = defaultdict(int)
    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        rally_count_by_match[match_id] += 1

    # 対戦相手プレイヤー名・パートナー名を取得
    related_ids: set[int] = set()
    for m in matches:
        related_ids.update(filter(None, [m.player_a_id, m.player_b_id, m.partner_a_id, m.partner_b_id]))

    players_all = db.query(Player).filter(Player.id.in_(related_ids)).all() if related_ids else []
    player_name_by_id: dict[int, str] = {p.id: p.name for p in players_all}

    # セット情報をまとめる（match_id → sets リスト）
    sets_by_match: dict[int, list] = defaultdict(list)
    for s in sets:
        sets_by_match[s.match_id].append(s)

    data = []
    for m in matches:
        # ダブルスパートナーも含めたロール決定（チームA = player_a + partner_a）
        if m.player_a_id == player_id or m.partner_a_id == player_id:
            player_role = "player_a"
            # 対戦相手 = チームB
            opp_names = [player_name_by_id.get(m.player_b_id, "")]
            if m.partner_b_id:
                opp_names.append(player_name_by_id.get(m.partner_b_id, ""))
        else:
            player_role = "player_b"
            # 対戦相手 = チームA
            opp_names = [player_name_by_id.get(m.player_a_id, "")]
            if m.partner_a_id:
                opp_names.append(player_name_by_id.get(m.partner_a_id, ""))
        opponent_name = " / ".join(filter(None, opp_names))

        # result は player_a 基準で格納されているため player_b の場合は反転
        result = m.result
        if player_role == "player_b":
            if result == "win":
                result = "loss"
            elif result == "loss":
                result = "win"

        # セット別スコア（プレイヤー視点: score_player - score_opponent, won）
        match_sets = sorted(sets_by_match.get(m.id, []), key=lambda s: s.set_num)
        set_scores = []
        for s in match_sets:
            if player_role == "player_a":
                sp, so = s.score_a, s.score_b
            else:
                sp, so = s.score_b, s.score_a
            set_scores.append({
                "set_num": s.set_num,
                "score_player": sp,
                "score_opponent": so,
                "won": s.winner == player_role,
            })

        data.append(
            {
                "match_id": m.id,
                "opponent": opponent_name,
                "tournament": m.tournament,
                "tournament_level": m.tournament_level,
                "date": m.date.isoformat() if m.date else None,
                "result": result,
                "rally_count": rally_count_by_match.get(m.id, 0),
                "format": m.format,
                "set_count": len(match_sets),
                "set_scores": set_scores,
            }
        )

    return {"success": True, "data": data}


# ---------------------------------------------------------------------------
# 5. Confidence (unchanged)
# ---------------------------------------------------------------------------

@router.get("/analysis/confidence")
def get_confidence(player_id: int, analysis_type: str):
    return {
        "success": True,
        "data": {"stars": "★☆☆", "label": "参考値（データ蓄積中）"},
    }


# ---------------------------------------------------------------------------
# B-002: ショット別勝敗集計
# ---------------------------------------------------------------------------

@router.get("/analysis/shot_win_loss")
def get_shot_win_loss(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """B-002: ショット別の総数・得点・失点・勝率を返す"""
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    if not matches:
        confidence = check_confidence("win_loss_comparison", 0)
        return {
            "success": True,
            "data": [],
            "meta": {"sample_size": 0, "confidence": confidence},
        }

    match_ids = [m.id for m in matches]
    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, player_id) for m in matches
    }

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_ids = [s.id for s in sets]
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}

    if not set_ids:
        confidence = check_confidence("win_loss_comparison", 0)
        return {
            "success": True,
            "data": [],
            "meta": {"sample_size": 0, "confidence": confidence},
        }

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all()
    rally_ids = [r.id for r in rallies]

    # ラリーごとにプレイヤーの勝敗とロールを記録
    rally_player_won: dict[int, bool] = {}
    rally_to_role: dict[int, str] = {}
    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        player_role = role_by_match[match_id]
        rally_to_role[rally.id] = player_role
        rally_player_won[rally.id] = rally.winner == player_role

    if not rally_ids:
        confidence = check_confidence("win_loss_comparison", 0)
        return {
            "success": True,
            "data": [],
            "meta": {"sample_size": 0, "confidence": confidence},
        }

    # プレイヤーのストロークを全取得
    all_strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(rally_ids))
        .all()
    )

    # shot_typeごとの出現ラリーセットと勝利ラリーセットを管理
    # ストロークが属するラリーを基準に集計
    shot_rallies: dict[str, set[int]] = defaultdict(set)
    shot_win_rallies: dict[str, set[int]] = defaultdict(set)

    for stroke in all_strokes:
        r_id = stroke.rally_id
        player_role = rally_to_role.get(r_id)
        if stroke.player != player_role:
            continue
        shot_rallies[stroke.shot_type].add(r_id)
        if rally_player_won.get(r_id, False):
            shot_win_rallies[stroke.shot_type].add(r_id)

    total_rallies = len(set(rally_ids))

    result = []
    for shot_type in sorted(shot_rallies.keys()):
        total = len(shot_rallies[shot_type])
        win_count = len(shot_win_rallies[shot_type])
        lose_count = total - win_count
        win_rate = round(win_count / total, 3) if total else 0.0
        result.append({
            "shot_type": shot_type,
            "shot_type_ja": SHOT_TYPE_JA.get(shot_type, shot_type),
            "total": total,
            "win_count": win_count,
            "lose_count": lose_count,
            "win_rate": win_rate,
        })

    confidence = check_confidence("win_loss_comparison", total_rallies)

    return {
        "success": True,
        "data": result,
        "meta": {
            "sample_size": total_rallies,
            "confidence": confidence,
        },
    }


# ---------------------------------------------------------------------------
# B-005: セット別パフォーマンス比較
# ---------------------------------------------------------------------------

@router.get("/analysis/set_comparison")
def get_set_comparison(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """B-005: 1・2・3セット目別のパフォーマンス比較"""
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    if not matches:
        confidence = check_confidence("descriptive_basic", 0)
        return {
            "success": True,
            "data": {"by_set": []},
            "meta": {"sample_size": 0, "confidence": confidence},
        }

    match_ids = [m.id for m in matches]
    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, player_id) for m in matches
    }

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    if not sets:
        confidence = check_confidence("descriptive_basic", 0)
        return {
            "success": True,
            "data": {"by_set": []},
            "meta": {"sample_size": 0, "confidence": confidence},
        }

    set_ids = [s.id for s in sets]
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}
    set_num_map: dict[int, int] = {s.id: s.set_num for s in sets}

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all()

    # セット番号ごとに集計
    set_stats: dict[int, dict] = defaultdict(lambda: {
        "total": 0, "wins": 0, "total_length": 0
    })

    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        player_role = role_by_match[match_id]
        set_num = set_num_map[rally.set_id]

        set_stats[set_num]["total"] += 1
        set_stats[set_num]["total_length"] += rally.rally_length
        if rally.winner == player_role:
            set_stats[set_num]["wins"] += 1

    by_set = []
    total_all = 0
    for set_num in sorted(set_stats.keys()):
        s = set_stats[set_num]
        total = s["total"]
        total_all += total
        win_rate = round(s["wins"] / total, 3) if total else 0.0
        avg_rally_length = round(s["total_length"] / total, 3) if total else 0.0
        by_set.append({
            "set_num": set_num,
            "total_rallies": total,
            "win_rate": win_rate,
            "avg_rally_length": avg_rally_length,
        })

    confidence = check_confidence("descriptive_basic", total_all)

    # set_num → set_number + label に変換してフロントエンドの型に合わせる
    by_set_formatted = [
        {
            "set_number": item["set_num"],
            "label": f"第{item['set_num']}セット",
            "total_rallies": item["total_rallies"],
            "win_rate": item["win_rate"],
            "avg_rally_length": item["avg_rally_length"],
        }
        for item in by_set
    ]

    return {
        "success": True,
        "data": by_set_formatted,
        "meta": {
            "sample_size": total_all,
            "confidence": confidence,
        },
    }


# ---------------------------------------------------------------------------
# B-001: スコア推移
# ---------------------------------------------------------------------------

@router.get("/analysis/score_progression")
def get_score_progression(match_id: int, db: Session = Depends(get_db)):
    """B-001: ラリーごとのスコア推移データを返す（ラインチャート用）"""
    match = db.get(Match, match_id)
    if not match:
        return {"success": False, "error": f"試合ID {match_id} が見つかりません"}

    sets = (
        db.query(GameSet)
        .filter(GameSet.match_id == match_id)
        .order_by(GameSet.set_num)
        .all()
    )
    if not sets:
        return {
            "success": True,
            "data": {"sets": []},
            "meta": {"sample_size": 0},
        }

    set_ids = [s.id for s in sets]
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

    total_rallies = len(rallies_all)
    sets_data = []

    for game_set in sets:
        set_rallies = rallies_by_set[game_set.id]
        rally_data = []
        # 点差が大きく変化したラリー番号をモメンタム変化点として記録
        momentum_changes = []
        prev_diff = None

        for rally in set_rallies:
            point_diff = rally.score_a_after - rally.score_b_after
            rally_data.append({
                "rally_id": rally.id,
                "rally_num": rally.rally_num,
                "score_a": rally.score_a_after,
                "score_b": rally.score_b_after,
                "winner": rally.winner,
                "point_diff": point_diff,
                "video_timestamp_start": rally.video_timestamp_start,
            })
            # 点差が3点以上変化した場合をモメンタム変化点とする
            if prev_diff is not None and abs(point_diff - prev_diff) >= AnalysisConfig.SCORE_MOMENTUM_SWING:
                momentum_changes.append(rally.rally_num)
            prev_diff = point_diff

        sets_data.append({
            "set_id": game_set.id,
            "set_num": game_set.set_num,
            "rallies": rally_data,
            "momentum_changes": momentum_changes,
        })

    return {
        "success": True,
        "data": {"sets": sets_data},
        "meta": {"sample_size": total_rallies},
    }


# ---------------------------------------------------------------------------
# B-004: 勝ち/負け試合別の主要統計比較
# ---------------------------------------------------------------------------

@router.get("/analysis/win_loss_comparison")
def get_win_loss_comparison(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """B-004: 勝ち試合と負け試合で主要統計を比較する"""
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    empty_confidence = check_confidence("win_loss_comparison", 0)
    if not matches:
        return {
            "success": True,
            "data": {"win_matches": None, "loss_matches": None},
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    # 試合ごとにプレイヤーの勝敗を判定
    win_match_ids: list[int] = []
    loss_match_ids: list[int] = []
    role_by_match: dict[int, str] = {}

    for m in matches:
        role = _player_role_in_match(m, player_id)
        role_by_match[m.id] = role
        # result は player_a 基準 → player_b の場合は反転
        result = m.result
        if role == "player_b":
            if result == "win":
                result = "loss"
            elif result == "loss":
                result = "win"
        if result == "win":
            win_match_ids.append(m.id)
        elif result == "loss":
            loss_match_ids.append(m.id)

    def _aggregate_match_stats(match_ids: list[int]) -> dict | None:
        """指定された試合IDリストで統計を集計する"""
        if not match_ids:
            return None

        set_ids = [
            s.id for s in db.query(GameSet.id).filter(GameSet.match_id.in_(match_ids)).all()
        ]
        if not set_ids:
            return None

        rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all()
        if not rallies:
            return None

        rally_ids = [r.id for r in rallies]
        # セット→試合 マッピング
        set_to_match: dict[int, int] = {
            s.id: s.match_id
            for s in db.query(GameSet).filter(GameSet.id.in_(set_ids)).all()
        }

        total_length = 0
        total_rallies = len(rallies)
        serve_wins = 0
        serve_total = 0

        for rally in rallies:
            total_length += rally.rally_length
            match_id = set_to_match[rally.set_id]
            player_role = role_by_match.get(match_id)
            if player_role and rally.server == player_role:
                serve_total += 1
                if rally.winner == player_role:
                    serve_wins += 1

        # ストロークからace率・エラー率・ショット集計
        strokes = (
            db.query(Stroke)
            .filter(Stroke.rally_id.in_(rally_ids))
            .all()
        )

        shot_counter: dict[str, int] = defaultdict(int)
        for stroke in strokes:
            match_id = set_to_match.get(
                next((r.set_id for r in rallies if r.id == stroke.rally_id), None), None
            )
            if match_id is None:
                continue
            player_role = role_by_match.get(match_id)
            if stroke.player == player_role:
                shot_counter[stroke.shot_type] += 1

        top_shots = sorted(
            [
                {
                    "shot_type": st,
                    "shot_type_ja": SHOT_TYPE_JA.get(st, st),
                    "count": cnt,
                }
                for st, cnt in shot_counter.items()
            ],
            key=lambda x: x["count"],
            reverse=True,
        )[:5]

        avg_rally_length = round(total_length / total_rallies, 2) if total_rallies else 0.0
        serve_win_rate = round(serve_wins / serve_total, 3) if serve_total else 0.0

        return {
            "count": len(match_ids),
            "avg_rally_length": avg_rally_length,
            "ace_rate": 0.0,   # シンプル実装（ace タイプ別集計は後で拡張）
            "error_rate": 0.0,
            "serve_win_rate": serve_win_rate,
            "top_shots": top_shots,
        }

    win_stats = _aggregate_match_stats(win_match_ids)
    loss_stats = _aggregate_match_stats(loss_match_ids)

    total_matches = len(win_match_ids) + len(loss_match_ids)
    confidence = check_confidence("win_loss_comparison", total_matches)

    return {
        "success": True,
        "data": {
            "win_matches": win_stats,
            "loss_matches": loss_stats,
        },
        "meta": {"sample_size": total_matches, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# B-006: 大会レベル別比較
# ---------------------------------------------------------------------------

@router.get("/analysis/tournament_level_comparison")
def get_tournament_level_comparison(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """B-006: 大会レベル（IC/SJL/国内等）ごとの勝率・ラリー長を比較する"""
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    empty_confidence = check_confidence("descriptive_basic", 0)
    if not matches:
        return {
            "success": True,
            "data": {"levels": []},
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, player_id) for m in matches
    }

    match_ids = [m.id for m in matches]
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]
    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []

    # 試合→大会レベルのマッピング
    level_by_match: dict[int, str] = {m.id: m.tournament_level for m in matches}
    result_by_match: dict[int, str] = {}
    for m in matches:
        role = role_by_match[m.id]
        result = m.result
        if role == "player_b":
            if result == "win":
                result = "loss"
            elif result == "loss":
                result = "win"
        result_by_match[m.id] = result

    # レベル別に試合を集計
    level_stats: dict[str, dict] = defaultdict(lambda: {
        "match_ids": set(), "wins": 0, "total_length": 0, "rally_count": 0
    })

    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        level = level_by_match[match_id]
        level_stats[level]["match_ids"].add(match_id)
        level_stats[level]["total_length"] += rally.rally_length
        level_stats[level]["rally_count"] += 1

    # 試合単位の勝ち数
    for m in matches:
        level = m.tournament_level
        if result_by_match[m.id] == "win":
            level_stats[level]["wins"] += 1
        if m.id not in level_stats[level]["match_ids"]:
            level_stats[level]["match_ids"].add(m.id)

    result_levels = []
    total_sample = 0
    for level, stats in sorted(level_stats.items()):
        match_count = len(stats["match_ids"])
        total_sample += match_count
        win_rate = round(stats["wins"] / match_count, 3) if match_count else 0.0
        avg_rally = round(stats["total_length"] / stats["rally_count"], 2) if stats["rally_count"] else 0.0
        result_levels.append({
            "level": level,
            "match_count": match_count,
            "win_rate": win_rate,
            "avg_rally_length": avg_rally,
            "sample_size": stats["rally_count"],
        })

    confidence = check_confidence("descriptive_basic", total_sample)

    return {
        "success": True,
        "data": {"levels": result_levels},
        "meta": {"sample_size": total_sample, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# C-002: 失点前パターン解析
# ---------------------------------------------------------------------------

@router.get("/analysis/pre_loss_patterns")
def get_pre_loss_patterns(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """C-002: 失点ラリーで失点の1・2・3球前のショットを集計する"""
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    empty_confidence = check_confidence("win_loss_comparison", 0)
    if not matches:
        return {
            "success": True,
            "data": {"pre_loss_1": [], "pre_loss_2": [], "pre_loss_3": []},
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

    # 失点ラリーを抽出
    lost_rally_ids: set[int] = set()
    rally_to_role: dict[int, str] = {}
    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        role = role_by_match[match_id]
        rally_to_role[rally.id] = role
        if rally.winner != role:  # 失点
            lost_rally_ids.add(rally.id)

    if not rally_ids:
        return {
            "success": True,
            "data": {"pre_loss_1": [], "pre_loss_2": [], "pre_loss_3": []},
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    # ストロークを取得してラリーごとにグループ化
    all_strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(list(lost_rally_ids)))
        .order_by(Stroke.rally_id, Stroke.stroke_num)
        .all()
    )

    strokes_by_rally: dict[int, list[Stroke]] = defaultdict(list)
    for stroke in all_strokes:
        strokes_by_rally[stroke.rally_id].append(stroke)

    # 各失点ラリーでプレイヤーの最終N球を集計
    pre1: dict[str, int] = defaultdict(int)
    pre2: dict[str, int] = defaultdict(int)
    pre3: dict[str, int] = defaultdict(int)
    sample_size = 0

    for rally_id, strokes in strokes_by_rally.items():
        if rally_id not in lost_rally_ids:
            continue
        player_role = rally_to_role.get(rally_id)
        if not player_role:
            continue
        # プレイヤーのストロークのみ抽出（stroke_num順）
        player_strokes = [s for s in strokes if s.player == player_role]
        if not player_strokes:
            continue
        sample_size += 1
        # 最後（1球前）
        if len(player_strokes) >= 1:
            pre1[player_strokes[-1].shot_type] += 1
        # 2球前
        if len(player_strokes) >= 2:
            pre2[player_strokes[-2].shot_type] += 1
        # 3球前
        if len(player_strokes) >= 3:
            pre3[player_strokes[-3].shot_type] += 1

    def _build_ranked(counter: dict[str, int]) -> list[dict]:
        total = sum(counter.values())
        return sorted(
            [
                {
                    "shot_type": st,
                    "shot_type_ja": SHOT_TYPE_JA.get(st, st),
                    "count": cnt,
                    "rate": round(cnt / total, 3) if total else 0.0,
                }
                for st, cnt in counter.items()
            ],
            key=lambda x: x["count"],
            reverse=True,
        )

    confidence = check_confidence("win_loss_comparison", sample_size)

    return {
        "success": True,
        "data": {
            "pre_loss_1": _build_ranked(pre1),
            "pre_loss_2": _build_ranked(pre2),
            "pre_loss_3": _build_ranked(pre3),
        },
        "meta": {"sample_size": sample_size, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# C-003: ファーストリターン解析
# ---------------------------------------------------------------------------

@router.get("/analysis/first_return_analysis")
def get_first_return_analysis(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """C-003: サーブ後最初のリターン（stroke_num=2）のゾーン別勝率を分析する"""
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    empty_confidence = check_confidence("descriptive_basic", 0)
    if not matches:
        return {
            "success": True,
            "data": {"zones": [], "top_zones": [], "sample_size": 0},
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

    rally_player_won: dict[int, bool] = {}
    # サーバーではなくレシーバー側のプレイヤーのみ
    receiver_rally_ids: set[int] = set()
    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        role = role_by_match[match_id]
        rally_player_won[rally.id] = rally.winner == role
        # プレイヤーがレシーバーの場合にstroke_num=2を集計
        if rally.server != role:
            receiver_rally_ids.add(rally.id)

    if not receiver_rally_ids:
        return {
            "success": True,
            "data": {"zones": [], "top_zones": [], "sample_size": 0},
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    # stroke_num=2 のストロークを取得
    return_strokes = (
        db.query(Stroke)
        .filter(
            Stroke.rally_id.in_(list(receiver_rally_ids)),
            Stroke.stroke_num == 2,
        )
        .all()
    )

    zone_total: dict[str, int] = defaultdict(int)
    zone_wins: dict[str, int] = defaultdict(int)

    for stroke in return_strokes:
        r_id = stroke.rally_id
        # stroke_num==2 in a receiver rally is the player's return shot by definition
        zone = stroke.land_zone or "unknown"
        zone_total[zone] += 1
        if rally_player_won.get(r_id, False):
            zone_wins[zone] += 1

    total_sample = sum(zone_total.values())
    zones_data = []
    for zone, cnt in sorted(zone_total.items()):
        wins = zone_wins.get(zone, 0)
        win_rate = round(wins / cnt, 3) if cnt else 0.0
        freq_rate = round(cnt / total_sample, 3) if total_sample else 0.0
        zones_data.append({
            "zone": zone,
            "count": cnt,
            "win_rate": win_rate,
            "freq_rate": freq_rate,
        })

    # 上位2ゾーン
    top_zones = [z["zone"] for z in sorted(zones_data, key=lambda x: x["count"], reverse=True)[:2]]
    confidence = check_confidence("descriptive_basic", total_sample)

    return {
        "success": True,
        "data": {
            "zones": zones_data,
            "top_zones": top_zones,
            "sample_size": total_sample,
        },
        "meta": {"sample_size": total_sample, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# C-004: ゾーン詳細分析
# ---------------------------------------------------------------------------

@router.get("/analysis/zone_detail")
def get_zone_detail(
    player_id: int,
    zone: str,
    type: str = Query("hit", pattern="^(hit|land)$"),
    db: Session = Depends(get_db),
):
    """C-004: 指定ゾーンのショット内訳と勝率を返す"""
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
        )
        .all()
    )

    empty_confidence = check_confidence("heatmap", 0)
    if not matches:
        return {
            "success": True,
            "data": {"zone": zone, "total_shots": 0, "shot_breakdown": [], "win_rate": 0.0},
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
            "data": {"zone": zone, "total_shots": 0, "shot_breakdown": [], "win_rate": 0.0},
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    zone_col = Stroke.hit_zone if type == "hit" else Stroke.land_zone
    strokes = (
        db.query(Stroke)
        .filter(
            Stroke.rally_id.in_(rally_ids),
            zone_col == zone,
        )
        .all()
    )

    shot_total: dict[str, int] = defaultdict(int)
    shot_wins: dict[str, int] = defaultdict(int)
    total_wins = 0
    total_shots = 0

    for stroke in strokes:
        r_id = stroke.rally_id
        player_role = rally_to_role.get(r_id)
        if stroke.player != player_role:
            continue
        shot_total[stroke.shot_type] += 1
        total_shots += 1
        if rally_player_won.get(r_id, False):
            shot_wins[stroke.shot_type] += 1
            total_wins += 1

    shot_breakdown = sorted(
        [
            {
                "shot_type": st,
                "shot_type_ja": SHOT_TYPE_JA.get(st, st),
                "count": cnt,
                "win_rate": round(shot_wins.get(st, 0) / cnt, 3) if cnt else 0.0,
            }
            for st, cnt in shot_total.items()
        ],
        key=lambda x: x["count"],
        reverse=True,
    )

    overall_win_rate = round(total_wins / total_shots, 3) if total_shots else 0.0
    confidence = check_confidence("heatmap", total_shots)

    return {
        "success": True,
        "data": {
            "zone": zone,
            "total_shots": total_shots,
            "shot_breakdown": shot_breakdown,
            "win_rate": overall_win_rate,
        },
        "meta": {"sample_size": total_shots, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# K-003: セット間5秒サマリー
# ---------------------------------------------------------------------------

@router.get("/analysis/set_summary")
def get_set_summary(set_id: int, max_rally_num: Optional[int] = None, db: Session = Depends(get_db)):
    """K-003: セット終了時の即時サマリー（セット間5秒レビュー用）
    max_rally_num: 指定した場合、そのラリー番号以前のデータのみで解析（途中地点解析用）"""
    game_set = db.get(GameSet, set_id)
    if not game_set:
        return {"success": False, "error": "セットが見つかりません"}

    q = db.query(Rally).filter(Rally.set_id == set_id)
    if max_rally_num is not None:
        q = q.filter(Rally.rally_num <= max_rally_num)
    rallies = q.order_by(Rally.rally_num).all()
    total_rallies = len(rallies)
    if total_rallies == 0:
        return {
            "success": True,
            "data": None,
            "meta": {"sample_size": 0, "confidence": check_confidence("descriptive_basic", 0)},
        }

    # 基本統計
    total_length = sum(r.rally_length for r in rallies)
    avg_rally_length = round(total_length / total_rallies, 2)
    if avg_rally_length < AnalysisConfig.SHORT_RALLY_LABEL_MAX:
        rally_length_trend = "short"
    elif avg_rally_length < AnalysisConfig.MEDIUM_RALLY_LABEL_MAX:
        rally_length_trend = "medium"
    else:
        rally_length_trend = "long"

    last_rally = rallies[-1]
    score_a = last_rally.score_a_after
    score_b = last_rally.score_b_after
    winner = "player_a" if score_a > score_b else "player_b"

    # ストローク取得
    rally_ids = [r.id for r in rallies]
    strokes = (
        db.query(Stroke).filter(Stroke.rally_id.in_(rally_ids)).all()
        if rally_ids else []
    )
    strokes_by_rally: dict[int, list] = defaultdict(list)
    for s in strokes:
        strokes_by_rally[s.rally_id].append(s)

    # 直近失点パターン（player_a 視点 / 最近 10 失点ラリー）
    loss_rallies = [r for r in rallies if r.winner == "player_b"][-10:]
    loss_pattern_counts: dict[str, int] = defaultdict(int)
    loss_pattern_labels: dict[str, str] = {}
    for r in loss_rallies:
        s_list = sorted(strokes_by_rally.get(r.id, []), key=lambda x: x.stroke_num)
        last_s = s_list[-1] if s_list else None
        et = END_TYPE_JA.get(r.end_type, r.end_type)
        st = SHOT_TYPE_JA.get(last_s.shot_type, last_s.shot_type) if last_s else "-"
        key = f"{r.end_type}_{last_s.shot_type if last_s else 'unknown'}"
        loss_pattern_counts[key] += 1
        loss_pattern_labels[key] = f"{et}（{st}）"

    total_losses = len(loss_rallies)
    recent_loss_patterns = sorted(
        [
            {
                "label": loss_pattern_labels[k],
                "count": v,
                "pct": round(v / total_losses, 2) if total_losses else 0,
            }
            for k, v in loss_pattern_counts.items()
        ],
        key=lambda x: -x["count"],
    )[:5]

    # 有効ショット（player_a がそのショットを使ったラリーの勝率 ≥ 0.6 かつ ≥ 5回）
    shot_stats: dict[str, dict] = defaultdict(lambda: {"wins": 0, "total": 0})
    for r in rallies:
        s_list = strokes_by_rally.get(r.id, [])
        used = set(s.shot_type for s in s_list if s.player == "player_a")
        won = r.winner == "player_a"
        for st in used:
            shot_stats[st]["total"] += 1
            if won:
                shot_stats[st]["wins"] += 1

    effective_shots = sorted(
        [
            {
                "shot_type": k,
                "shot_type_ja": SHOT_TYPE_JA.get(k, k),
                "win_rate": round(v["wins"] / v["total"], 2),
                "count": v["total"],
            }
            for k, v in shot_stats.items()
            if v["total"] >= 5 and v["wins"] / v["total"] >= 0.6
        ],
        key=lambda x: -x["win_rate"],
    )[:3]

    # 注意ショット（player_a の最終ショットが失点につながった率 ≥ 0.6 かつ ≥ 3回）
    last_shot_stats: dict[str, dict] = defaultdict(lambda: {"losses": 0, "total": 0})
    for r in rallies:
        s_list = sorted(strokes_by_rally.get(r.id, []), key=lambda x: x.stroke_num)
        a_strokes = [s for s in s_list if s.player == "player_a"]
        if a_strokes:
            last = a_strokes[-1]
            last_shot_stats[last.shot_type]["total"] += 1
            if r.winner == "player_b":
                last_shot_stats[last.shot_type]["losses"] += 1

    risky_shots = sorted(
        [
            {
                "shot_type": k,
                "shot_type_ja": SHOT_TYPE_JA.get(k, k),
                "loss_rate": round(v["losses"] / v["total"], 2),
                "count": v["total"],
            }
            for k, v in last_shot_stats.items()
            if v["total"] >= 3 and v["losses"] / v["total"] >= 0.6
        ],
        key=lambda x: -x["loss_rate"],
    )[:3]

    total_strokes = len(strokes)
    confidence = check_confidence("descriptive_basic", total_strokes)

    return {
        "success": True,
        "data": {
            "set_num": game_set.set_num,
            "score_a": score_a,
            "score_b": score_b,
            "winner": winner,
            "total_rallies": total_rallies,
            "avg_rally_length": avg_rally_length,
            "rally_length_trend": rally_length_trend,
            "recent_loss_patterns": recent_loss_patterns,
            "effective_shots": effective_shots,
            "risky_shots": risky_shots,
        },
        "meta": {"sample_size": total_strokes, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# R-003: 得点前パターン（pre_win_patterns）
# ---------------------------------------------------------------------------

@router.get("/analysis/pre_win_patterns")
def get_pre_win_patterns(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """R-003: 得点ラリーで得点の1・2・3球前のショットを集計する（pre_loss_patterns の勝ち版）"""
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    empty_confidence = check_confidence("win_loss_comparison", 0)
    if not matches:
        return {
            "success": True,
            "data": {"pre_win_1": [], "pre_win_2": [], "pre_win_3": []},
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

    won_rally_ids: set[int] = set()
    rally_to_role: dict[int, str] = {}
    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        role = role_by_match[match_id]
        rally_to_role[rally.id] = role
        if rally.winner == role:
            won_rally_ids.add(rally.id)

    if not rallies or not won_rally_ids:
        return {
            "success": True,
            "data": {"pre_win_1": [], "pre_win_2": [], "pre_win_3": []},
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    all_strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(list(won_rally_ids)))
        .order_by(Stroke.rally_id, Stroke.stroke_num)
        .all()
    )
    strokes_by_rally: dict[int, list] = defaultdict(list)
    for stroke in all_strokes:
        strokes_by_rally[stroke.rally_id].append(stroke)

    pre1: dict[str, int] = defaultdict(int)
    pre2: dict[str, int] = defaultdict(int)
    pre3: dict[str, int] = defaultdict(int)
    sample_size = 0

    for rally_id, strokes in strokes_by_rally.items():
        player_role = rally_to_role.get(rally_id)
        if not player_role:
            continue
        player_strokes = [s for s in strokes if s.player == player_role]
        if not player_strokes:
            continue
        sample_size += 1
        if len(player_strokes) >= 1:
            pre1[player_strokes[-1].shot_type] += 1
        if len(player_strokes) >= 2:
            pre2[player_strokes[-2].shot_type] += 1
        if len(player_strokes) >= 3:
            pre3[player_strokes[-3].shot_type] += 1

    def _build_ranked_win(counter: dict[str, int]) -> list[dict]:
        total = sum(counter.values())
        return sorted(
            [
                {
                    "shot_type": st,
                    "shot_type_ja": SHOT_TYPE_JA.get(st, st),
                    "count": cnt,
                    "rate": round(cnt / total, 3) if total else 0.0,
                }
                for st, cnt in counter.items()
            ],
            key=lambda x: x["count"],
            reverse=True,
        )

    confidence = check_confidence("win_loss_comparison", sample_size)
    return {
        "success": True,
        "data": {
            "pre_win_1": _build_ranked_win(pre1),
            "pre_win_2": _build_ranked_win(pre2),
            "pre_win_3": _build_ranked_win(pre3),
        },
        "meta": {"sample_size": sample_size, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# R-004: 有効配球マップ（effective_distribution_map）
# ---------------------------------------------------------------------------

@router.get("/analysis/effective_distribution_map")
def get_effective_distribution_map(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    shot_type: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """R-004: 得点ラリーの最終ストローク着地ゾーン分布から有効配球マップを生成する"""
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    empty_conf = check_confidence("descriptive_basic", 0)
    empty = {
        "success": True,
        "data": {"zone_effectiveness": {}, "top_zones": []},
        "meta": {"sample_size": 0, "confidence": empty_conf},
    }
    if not matches:
        return empty

    match_ids = [m.id for m in matches]
    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, player_id) for m in matches
    }
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]
    if not set_ids:
        return empty

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all()
    won_rally_ids: set[int] = set()
    rally_to_role: dict[int, str] = {}
    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        role = role_by_match[match_id]
        rally_to_role[rally.id] = role
        if rally.winner == role:
            won_rally_ids.add(rally.id)

    if not won_rally_ids:
        return empty

    # 得点ラリーの最終プレイヤーストロークの着地ゾーン集計
    q = db.query(Stroke).filter(Stroke.rally_id.in_(list(won_rally_ids)))
    if shot_type:
        q = q.filter(Stroke.shot_type == shot_type)
    win_strokes = q.order_by(Stroke.rally_id, Stroke.stroke_num).all()

    strokes_by_rally: dict[int, list] = defaultdict(list)
    for stroke in win_strokes:
        strokes_by_rally[stroke.rally_id].append(stroke)

    zone_win: dict[str, int] = defaultdict(int)
    sample_size = 0
    for rally_id, strokes in strokes_by_rally.items():
        player_role = rally_to_role.get(rally_id)
        if not player_role:
            continue
        player_strokes = [s for s in strokes if s.player == player_role]
        if not player_strokes:
            continue
        last = player_strokes[-1]
        zone = last.land_zone
        if not zone:
            continue
        zone_win[zone] += 1
        sample_size += 1

    # 全ラリーでのプレイヤーストローク着地ゾーン集計（分母）
    all_rally_ids = [r.id for r in rallies]
    q_all = db.query(Stroke).filter(Stroke.rally_id.in_(all_rally_ids))
    if shot_type:
        q_all = q_all.filter(Stroke.shot_type == shot_type)
    zone_total: dict[str, int] = defaultdict(int)
    for s in q_all.all():
        player_role = rally_to_role.get(s.rally_id)
        if player_role and s.player == player_role and s.land_zone:
            zone_total[s.land_zone] += 1

    if sample_size == 0:
        return empty

    zone_effectiveness: dict[str, dict] = {}
    for zone, win_count in zone_win.items():
        total = zone_total.get(zone, win_count)
        win_rate = round(win_count / total, 3) if total else 0.0
        freq = round(win_count / sample_size, 3)
        zone_effectiveness[zone] = {
            "win_count": win_count,
            "total_count": total,
            "win_rate": win_rate,
            "effectiveness": round(win_rate * freq, 4),
        }

    top_zones = sorted(
        zone_effectiveness.keys(),
        key=lambda z: zone_effectiveness[z]["effectiveness"],
        reverse=True,
    )[:3]

    confidence = check_confidence("descriptive_basic", sample_size)
    return {
        "success": True,
        "data": {"zone_effectiveness": zone_effectiveness, "top_zones": top_zones},
        "meta": {"sample_size": sample_size, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# R-005: 被打球弱点マップ（received_vulnerability）
# ---------------------------------------------------------------------------

@router.get("/analysis/received_vulnerability")
def get_received_vulnerability(
    player_id: int,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """R-005: 失点ラリーで相手が打った最終ストロークの着地ゾーン別失点率（被打球弱点マップ）"""
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    empty_conf = check_confidence("descriptive_basic", 0)
    empty = {
        "success": True,
        "data": {"zones": {}, "danger_zones": []},
        "meta": {"sample_size": 0, "confidence": empty_conf},
    }
    if not matches:
        return empty

    match_ids = [m.id for m in matches]
    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, player_id) for m in matches
    }
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]
    if not set_ids:
        return empty

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all()
    lost_rally_ids: set[int] = set()
    rally_to_role: dict[int, str] = {}
    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        role = role_by_match[match_id]
        rally_to_role[rally.id] = role
        if rally.winner != role:
            lost_rally_ids.add(rally.id)

    if not lost_rally_ids:
        return empty

    # 全ラリーで相手ストロークの着地ゾーン集計（分母）
    all_rally_ids = [r.id for r in rallies]
    all_strokes_q = db.query(Stroke).filter(Stroke.rally_id.in_(all_rally_ids)).all()
    zone_total_opp: dict[str, int] = defaultdict(int)
    for s in all_strokes_q:
        player_role = rally_to_role.get(s.rally_id)
        if player_role and s.player != player_role and s.land_zone:
            zone_total_opp[s.land_zone] += 1

    # 失点ラリーで相手最終ストロークの着地ゾーン集計（分子）
    loss_strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(list(lost_rally_ids)))
        .order_by(Stroke.rally_id, Stroke.stroke_num)
        .all()
    )
    strokes_by_rally: dict[int, list] = defaultdict(list)
    for s in loss_strokes:
        strokes_by_rally[s.rally_id].append(s)

    zone_loss: dict[str, int] = defaultdict(int)
    sample_size = 0
    for rally_id, strokes in strokes_by_rally.items():
        player_role = rally_to_role.get(rally_id)
        if not player_role:
            continue
        opp_strokes = sorted(
            [s for s in strokes if s.player != player_role],
            key=lambda s: s.stroke_num,
        )
        if not opp_strokes:
            continue
        zone = opp_strokes[-1].land_zone
        if not zone:
            continue
        zone_loss[zone] += 1
        sample_size += 1

    if sample_size == 0:
        return empty

    zones_data: dict[str, dict] = {}
    for zone, loss_count in zone_loss.items():
        total = zone_total_opp.get(zone, loss_count)
        loss_rate = round(loss_count / total, 3) if total else 0.0
        zones_data[zone] = {
            "loss_count": loss_count,
            "total_count": total,
            "loss_rate": loss_rate,
        }

    danger_zones = sorted(
        zones_data.keys(),
        key=lambda z: zones_data[z]["loss_rate"],
        reverse=True,
    )[:2]

    confidence = check_confidence("descriptive_basic", sample_size)
    return {
        "success": True,
        "data": {"zones": zones_data, "danger_zones": danger_zones},
        "meta": {"sample_size": sample_size, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# R-004b: 有効配球マップ ゾーン詳細
# ---------------------------------------------------------------------------

@router.get("/analysis/effective_distribution_map/zone_detail")
def get_effective_distribution_map_zone_detail(
    player_id: int,
    zone: str,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """R-004b: 有効配球マップ — 指定ゾーンへ配球したストロークの詳細（ショット種別・打点分布）"""
    empty = {
        "success": True,
        "data": {"zone": zone, "total_count": 0, "win_count": 0, "win_rate": None, "top_shot_types": [], "hit_zones": []},
        "meta": {"sample_size": 0},
    }
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)
    if not matches:
        return empty

    match_ids = [m.id for m in matches]
    role_by_match: dict[int, str] = {m.id: _player_role_in_match(m, player_id) for m in matches}
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]
    if not set_ids:
        return empty

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all()
    won_rally_ids: set[int] = set()
    rally_to_role: dict[int, str] = {}
    for rally in rallies:
        mid = set_to_match[rally.set_id]
        role = role_by_match[mid]
        rally_to_role[rally.id] = role
        if rally.winner == role:
            won_rally_ids.add(rally.id)

    all_rally_ids = [r.id for r in rallies]
    strokes = db.query(Stroke).filter(
        Stroke.rally_id.in_(all_rally_ids),
        Stroke.land_zone == zone,
    ).all()

    # 対象プレイヤーのストロークのみ
    player_strokes = [s for s in strokes if rally_to_role.get(s.rally_id) and s.player == rally_to_role[s.rally_id]]
    total_count = len(player_strokes)
    if total_count == 0:
        return empty

    win_count = sum(1 for s in player_strokes if s.rally_id in won_rally_ids)
    win_rate = round(win_count / total_count, 3)

    shot_type_counts: dict[str, int] = defaultdict(int)
    hit_zone_counts: dict[str, int] = defaultdict(int)
    for s in player_strokes:
        shot_type_counts[s.shot_type] += 1
        if s.hit_zone:
            hit_zone_counts[s.hit_zone] += 1

    top_shot_types = sorted(
        [{"shot_type": k, "count": v} for k, v in shot_type_counts.items()],
        key=lambda x: -x["count"],
    )[:6]
    hit_zones = sorted(
        [{"zone": k, "count": v} for k, v in hit_zone_counts.items()],
        key=lambda x: -x["count"],
    )[:6]

    return {
        "success": True,
        "data": {
            "zone": zone,
            "total_count": total_count,
            "win_count": win_count,
            "win_rate": win_rate,
            "top_shot_types": top_shot_types,
            "hit_zones": hit_zones,
        },
        "meta": {"sample_size": total_count},
    }


# ---------------------------------------------------------------------------
# R-005b: 被打球弱点マップ ゾーン詳細
# ---------------------------------------------------------------------------

@router.get("/analysis/received_vulnerability/zone_detail")
def get_received_vulnerability_zone_detail(
    player_id: int,
    zone: str,
    result: Optional[str] = Query(None),
    tournament_level: Optional[str] = Query(None),
    date_from: Optional[DateType] = Query(None),
    date_to: Optional[DateType] = Query(None),
    db: Session = Depends(get_db),
):
    """R-005b: 被打球弱点マップ — 指定ゾーンへの相手配球ストロークの詳細（ショット種別・打点分布）"""
    empty = {
        "success": True,
        "data": {"zone": zone, "total_count": 0, "loss_count": 0, "loss_rate": None, "top_shot_types": [], "hit_zones": []},
        "meta": {"sample_size": 0},
    }
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)
    if not matches:
        return empty

    match_ids = [m.id for m in matches]
    role_by_match: dict[int, str] = {m.id: _player_role_in_match(m, player_id) for m in matches}
    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]
    if not set_ids:
        return empty

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all()
    lost_rally_ids: set[int] = set()
    rally_to_role: dict[int, str] = {}
    for rally in rallies:
        mid = set_to_match[rally.set_id]
        role = role_by_match[mid]
        rally_to_role[rally.id] = role
        if rally.winner != role:
            lost_rally_ids.add(rally.id)

    all_rally_ids = [r.id for r in rallies]
    strokes = db.query(Stroke).filter(
        Stroke.rally_id.in_(all_rally_ids),
        Stroke.land_zone == zone,
    ).all()

    # 相手（opponent）のストロークのみ
    opp_strokes = [s for s in strokes if rally_to_role.get(s.rally_id) and s.player != rally_to_role[s.rally_id]]
    total_count = len(opp_strokes)
    if total_count == 0:
        return empty

    loss_count = sum(1 for s in opp_strokes if s.rally_id in lost_rally_ids)
    loss_rate = round(loss_count / total_count, 3)

    shot_type_counts: dict[str, int] = defaultdict(int)
    hit_zone_counts: dict[str, int] = defaultdict(int)
    for s in opp_strokes:
        shot_type_counts[s.shot_type] += 1
        if s.hit_zone:
            hit_zone_counts[s.hit_zone] += 1

    top_shot_types = sorted(
        [{"shot_type": k, "count": v} for k, v in shot_type_counts.items()],
        key=lambda x: -x["count"],
    )[:6]
    hit_zones = sorted(
        [{"zone": k, "count": v} for k, v in hit_zone_counts.items()],
        key=lambda x: -x["count"],
    )[:6]

    return {
        "success": True,
        "data": {
            "zone": zone,
            "total_count": total_count,
            "loss_count": loss_count,
            "loss_rate": loss_rate,
            "top_shot_types": top_shot_types,
            "hit_zones": hit_zones,
        },
        "meta": {"sample_size": total_count},
    }
