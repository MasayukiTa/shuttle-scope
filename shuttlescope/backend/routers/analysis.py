"""解析API（/api/analysis）"""
from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

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


def _fetch_matches_sets_rallies(player_id: int, db: Session):
    """プレイヤーIDに関連する試合・セット・ラリーを一括取得するヘルパー"""
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

    rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all() if set_ids else []

    return matches, role_by_match, sets, set_to_match, rallies, {}


# ---------------------------------------------------------------------------
# 1. Descriptive statistics
# ---------------------------------------------------------------------------

@router.get("/analysis/descriptive")
def get_descriptive(player_id: int, db: Session = Depends(get_db)):
    # 対象プレイヤーが出場した全試合を取得
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
        )
        .all()
    )

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
    db: Session = Depends(get_db),
):
    ALL_ZONES = ["BL", "BC", "BR", "ML", "MC", "MR", "NL", "NC", "NR"]

    # プレイヤーが player_a / player_b として出場した試合IDを取得
    match_ids_as_a = [
        m.id
        for m in db.query(Match.id).filter(Match.player_a_id == player_id).all()
    ]
    match_ids_as_b = [
        m.id
        for m in db.query(Match.id).filter(Match.player_b_id == player_id).all()
    ]

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
def get_shot_types(player_id: int, db: Session = Depends(get_db)):
    # 対象プレイヤーが出場した全試合とロールを取得
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
        )
        .all()
    )
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
                "date": m.date.isoformat() if m.date else None,
                "result": result,
                "rally_count": rally_count_by_match.get(m.id, 0),
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
def get_shot_win_loss(player_id: int, db: Session = Depends(get_db)):
    """B-002: ショット別の総数・得点・失点・勝率を返す"""
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
        )
        .all()
    )

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
def get_set_comparison(player_id: int, db: Session = Depends(get_db)):
    """B-005: 1・2・3セット目別のパフォーマンス比較"""
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
        )
        .all()
    )

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

    return {
        "success": True,
        "data": {"by_set": by_set},
        "meta": {
            "sample_size": total_all,
            "confidence": confidence,
        },
    }


# ---------------------------------------------------------------------------
# D-001: ラリー長区間別勝率
# ---------------------------------------------------------------------------

@router.get("/analysis/rally_length_vs_winrate")
def get_rally_length_vs_winrate(player_id: int, db: Session = Depends(get_db)):
    """D-001: ラリー長区間別勝率とプレイヤータイプを返す"""
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
        )
        .all()
    )

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
def get_pressure_performance(player_id: int, db: Session = Depends(get_db)):
    """D-004: デュース時・終盤時・通常時のパフォーマンス比較"""
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
        )
        .all()
    )

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
def get_shot_transition_matrix(player_id: int, db: Session = Depends(get_db)):
    """C-001: プレイヤーのショット遷移行列（18x18）を返す"""
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == player_id) | (Match.player_b_id == player_id)
        )
        .all()
    )

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
