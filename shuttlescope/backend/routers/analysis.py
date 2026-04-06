"""解析API（/api/analysis）"""
from collections import defaultdict
from datetime import date as DateType
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.analysis.markov import MarkovAnalyzer
from backend.analysis.shot_influence import ShotInfluenceAnalyzer
from backend.analysis.bayesian_rt import BayesianRealTimeAnalyzer

from backend.db.database import get_db
from backend.db.models import Match, GameSet, Rally, Stroke, Player
from backend.utils.confidence import check_confidence

router = APIRouter()

# ショット種別の日本語ラベル
SHOT_TYPE_JA = {
    "short_service": "ショートサーブ",
    "long_service": "ロングサーブ",
    "net_shot": "ネットショット",
    "clear": "クリア",
    "push_rush": "プッシュ/ラッシュ",
    "smash": "スマッシュ",
    "defensive": "ディフェンス",
    "drive": "ドライブ",
    "lob": "ロブ",
    "drop": "ドロップ",
    "cross_net": "クロスネット",
    "slice": "スライス",
    "around_head": "ラウンドヘッド",
    "cant_reach": "届かず",
    "flick": "フリック",
    "half_smash": "ハーフスマッシュ",
    "block": "ブロック",
    "other": "その他",
}

# 遷移行列用のショット順序（18種類）
SHOT_KEYS = [
    "short_service", "long_service", "net_shot", "clear", "push_rush",
    "smash", "defensive", "drive", "lob", "drop", "cross_net", "slice",
    "around_head", "cant_reach", "flick", "half_smash", "block", "other",
]
SHOT_LABELS_JA = [SHOT_TYPE_JA[k] for k in SHOT_KEYS]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _player_role_in_match(match: Match, player_id: int) -> str | None:
    """Return 'player_a' or 'player_b' for the given player_id, or None."""
    if match.player_a_id == player_id:
        return "player_a"
    if match.player_b_id == player_id:
        return "player_b"
    return None


def _get_player_matches(
    db: Session,
    player_id: int,
    result: Optional[str] = None,
    tournament_level: Optional[str] = None,
    date_from: Optional[DateType] = None,
    date_to: Optional[DateType] = None,
) -> list[Match]:
    """フィルター条件付きでプレイヤーの試合を取得"""
    q = db.query(Match).filter(
        (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
    )
    if tournament_level:
        q = q.filter(Match.tournament_level == tournament_level)
    if date_from:
        q = q.filter(Match.date >= date_from)
    if date_to:
        q = q.filter(Match.date <= date_to)
    if result in ("win", "loss"):
        # resultはフロントから見たプレイヤー視点。DBはplayer_a基準で格納
        opposite = "loss" if result == "win" else "win"
        q = q.filter(
            or_(
                and_(Match.player_a_id == player_id, Match.result == result),
                and_(Match.player_b_id == player_id, Match.result == opposite),
            )
        )
    return q.all()


def _fetch_matches_sets_rallies(player_id: int, db: Session, include_skipped: bool = False):
    """プレイヤーIDに関連する試合・セット・ラリーを一括取得するヘルパー。
    include_skipped=False（デフォルト）では見逃しラリー(is_skipped=True)を除外する。
    スコア推移など得点イベント全件が必要な場合は include_skipped=True を渡す。
    """
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
        )
        .all()
    )
    if not matches:
        return [], {}, [], {}, [], {}

    match_ids = [m.id for m in matches]
    role_by_match: dict[int, str] = {
        m.id: _player_role_in_match(m, player_id) for m in matches
    }

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_ids = [s.id for s in sets]
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}

    if set_ids:
        q = db.query(Rally).filter(Rally.set_id.in_(set_ids))
        if not include_skipped:
            q = q.filter(Rally.is_skipped == False)  # noqa: E712
        rallies = q.all()
    else:
        rallies = []

    return matches, role_by_match, sets, set_to_match, rallies, {}


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
    db: Session = Depends(get_db),
):
    ALL_ZONES = ["BL", "BC", "BR", "ML", "MC", "MR", "NL", "NC", "NR"]

    # フィルター済み試合からIDを分類
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
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
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

    # 対戦相手プレイヤー名を取得
    opponent_ids: set[int] = set()
    for m in matches:
        if m.player_a_id == player_id:
            opponent_ids.add(m.player_b_id)
        else:
            opponent_ids.add(m.player_a_id)

    players = db.query(Player).filter(Player.id.in_(opponent_ids)).all() if opponent_ids else []
    player_name_by_id: dict[int, str] = {p.id: p.name for p in players}

    data = []
    for m in matches:
        opponent_id = m.player_b_id if m.player_a_id == player_id else m.player_a_id
        opponent_name = player_name_by_id.get(opponent_id, "")

        # result は player_a 基準で格納されているため player_b の場合は反転
        result = m.result
        if m.player_b_id == player_id:
            if result == "win":
                result = "loss"
            elif result == "loss":
                result = "win"

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
                if streak_len >= 3:
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
        if streak_len >= 3:
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
        elif rally.score_a_after >= 17 or rally.score_b_after >= 17:
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
            if prev_diff is not None and abs(point_diff - prev_diff) >= 3:
                momentum_changes.append(rally.rally_num)
            prev_diff = point_diff

        sets_data.append({
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
    rally_to_role: dict[int, str] = {}
    # サーバーではなくレシーバー側のプレイヤーのみ
    receiver_rally_ids: set[int] = set()
    for rally in rallies:
        match_id = set_to_match[rally.set_id]
        role = role_by_match[match_id]
        rally_to_role[rally.id] = role
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
        player_role = rally_to_role.get(r_id)
        if stroke.player != player_role:
            continue
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
                if y < 0.4:
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
        if balance_ratio >= 0.35:
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
    matches = _get_player_matches(db, player_id, result, tournament_level, date_from, date_to)

    empty_confidence = check_confidence("shot_transition", 0)
    if not matches:
        return {
            "success": True,
            "data": {"top_patterns": [], "bottom_patterns": []},
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
            "data": {"top_patterns": [], "bottom_patterns": []},
            "meta": {"sample_size": 0, "confidence": empty_confidence},
        }

    all_strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(rally_ids))
        .order_by(Stroke.rally_id, Stroke.stroke_num)
        .all()
    )

    # ラリーごとにストロークをグループ化してMarkovAnalyzer向けリストを構築
    strokes_by_rally: dict[int, list] = defaultdict(list)
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
    all_patterns = analyzer.get_top_patterns(strokes_list, top_k=20)

    top_patterns = [p for p in all_patterns if p["epv"] >= 0][:10]
    bottom_patterns = sorted(all_patterns, key=lambda x: x["epv"])[:10]

    confidence = check_confidence("shot_transition", total_strokes)

    return {
        "success": True,
        "data": {
            "top_patterns": top_patterns,
            "bottom_patterns": bottom_patterns,
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
    analyzer = ShotInfluenceAnalyzer()
    all_rally_data = []

    for rally in rallies:
        stks = strokes_by_rally.get(rally.id, [])
        player_a_strokes = [s for s in stks if s.player == "player_a"]
        won = rally.winner == "player_a"

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

        influences = analyzer.compute_heuristic_influence(stroke_dicts, won)
        all_rally_data.append({
            "rally_id": rally.id,
            "rally_num": rally.rally_num,
            "won": won,
            "strokes": influences,
        })

    # ショット種別ごとの平均影響度
    shot_scores: dict[str, list[float]] = defaultdict(list)
    for rally_data in all_rally_data:
        for s in rally_data["strokes"]:
            shot_scores[s["shot_type"]].append(s["influence_score"])

    shot_type_summary = {
        st: round(sum(scores) / len(scores), 4) if scores else 0.0
        for st, scores in sorted(shot_scores.items())
    }

    total_strokes = sum(len(rd["strokes"]) for rd in all_rally_data)
    confidence = check_confidence("shot_transition", total_strokes)

    return {
        "success": True,
        "data": {
            "rallies": all_rally_data,
            "shot_type_summary": shot_type_summary,
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
    result = analyzer.generate_interval_report(match_id, completed_set_num, db)

    if not result.get("success"):
        return result

    # sample_size を計算して meta に付与
    total_rallies = sum(
        s.get("rally_count", 0) for s in result.get("data", {}).get("sets", [])
    )
    confidence = check_confidence("descriptive_basic", total_rallies)

    return {
        "success": True,
        "data": result["data"],
        "meta": {"sample_size": total_rallies, "confidence": confidence},
    }


# ---------------------------------------------------------------------------
# K-003: セット間5秒サマリー
# ---------------------------------------------------------------------------

END_TYPE_JA = {
    "ace": "エース",
    "forced_error": "強制エラー",
    "unforced_error": "自滅",
    "net": "ネット",
    "out": "アウト",
    "cant_reach": "届かず",
}


@router.get("/analysis/set_summary")
def get_set_summary(set_id: int, db: Session = Depends(get_db)):
    """K-003: セット終了時の即時サマリー（セット間5秒レビュー用）"""
    game_set = db.get(GameSet, set_id)
    if not game_set:
        return {"success": False, "error": "セットが見つかりません"}

    rallies = (
        db.query(Rally)
        .filter(Rally.set_id == set_id)
        .order_by(Rally.rally_num)
        .all()
    )
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
    if avg_rally_length < 4:
        rally_length_trend = "short"
    elif avg_rally_length < 8:
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
