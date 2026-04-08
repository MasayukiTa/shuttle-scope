"""
growth_engine.py — 成長解析エンジン (Stage 2-B)

改善点:
  - 全試合を等重み → 相手強度で重み付けした成長率を計算
  - 「弱い相手に勝った成長」と「強い相手に粘った成長」を区別できる
  - prediction の recent_form にも後から接続できる設計

相手強度の算出方針:
  1. Player.world_ranking が入っていれば使用（低ランク=強い）
  2. ない場合は DB 内の全試合勝率で推定
  3. 両方なければ強度 0.5（中立）にフォールバック

設計原則:
  - 全関数は純粋関数（副作用なし）
  - 非同期 DB 呼び出しなし（同期 SQLAlchemy セッション使用）
  - 既存レスポンスに strength_weighted_* フィールドを追加する形で後方互換
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import Session

from backend.db.models import Match, GameSet, Rally, Player


# ── 相手強度計算 ─────────────────────────────────────────────────────────────

def compute_opponent_strength(db: Session, opponent_id: int) -> float:
    """
    相手選手の強度スコアを 0.0-1.0 の範囲で計算する。
    1.0 = 最強、0.0 = 最弱。

    算出ロジック:
      1. world_ranking が 1-500 の範囲にある場合:
         strength = 1 - (rank - 1) / 499  （1位=1.0, 500位=0.0）
      2. ranking がない場合:
         DB 内の全試合勝率を使用（全試合 win/loss のみ）
      3. いずれもデータなしの場合: 0.5（中立）
    """
    player = db.get(Player, opponent_id)
    if player and player.world_ranking and 1 <= player.world_ranking <= 500:
        return round(1.0 - (player.world_ranking - 1) / 499, 4)

    # world_ranking なし → 過去試合の勝率から推定
    matches = (
        db.query(Match)
        .filter(
            (Match.player_a_id == opponent_id) | (Match.player_b_id == opponent_id),
            Match.result.in_(["win", "loss"]),
        )
        .all()
    )
    if len(matches) < 3:
        return 0.5  # サンプル不足

    wins = sum(
        1 for m in matches
        if (m.player_a_id == opponent_id and m.result == "win")
        or (m.player_b_id == opponent_id and m.result == "loss")
    )
    return round(wins / len(matches), 4)


def build_strength_cache(
    db: Session,
    matches: list[Match],
    player_id: int,
) -> dict[int, float]:
    """
    対戦相手 ID ごとの強度スコアをまとめて計算してキャッシュ dict を返す。
    N+1 を防ぐために一度に処理する。
    """
    opp_ids: set[int] = set()
    for m in matches:
        if m.player_a_id == player_id:
            opp_ids.add(m.player_b_id)
        else:
            opp_ids.add(m.player_a_id)

    return {opp_id: compute_opponent_strength(db, opp_id) for opp_id in opp_ids}


# ── 重み付き指標計算 ─────────────────────────────────────────────────────────

def weighted_win_rate(
    matches: list[Match],
    player_id: int,
    strength_cache: dict[int, float],
) -> Optional[float]:
    """
    相手強度で重み付けした勝率を計算する。

    weighted_wins = Σ(strength_i × won_i)
    weighted_total = Σ(strength_i)
    weighted_wr = weighted_wins / weighted_total

    強い相手への勝利: 高重みで勝利に貢献
    弱い相手への敗戦: 低重みで影響小

    Returns:
        重み付き勝率 (0.0-1.0)、計算不能な場合は None
    """
    total_weight = 0.0
    weighted_wins = 0.0

    for m in matches:
        if m.result not in ("win", "loss"):
            continue
        if m.player_a_id == player_id:
            opp_id = m.player_b_id
            won = m.result == "win"
        else:
            opp_id = m.player_a_id
            won = m.result == "loss"

        strength = strength_cache.get(opp_id, 0.5)
        total_weight += strength
        if won:
            weighted_wins += strength

    if total_weight < 0.01:
        return None
    return round(weighted_wins / total_weight, 4)


def growth_points_weighted(
    matches: list[Match],
    player_id: int,
    db: Session,
    metric: str = "win_rate",
) -> list[dict]:
    """
    時系列の各試合について、通常指標と相手強度補正済み指標の両方を計算する。

    Parameters:
        matches:   試合一覧（日付昇順推奨）
        player_id: 対象選手 ID
        db:        DB セッション
        metric:    'win_rate' / 'serve_win_rate' / 'avg_rally_length'

    Returns:
        [
          {
            "match_id": int,
            "date": str,
            "value": float,              # 通常指標
            "strength_weight": float,    # 相手強度 (0-1)
            "opponent_id": int,
          }, ...
        ]
    """
    strength_cache = build_strength_cache(db, matches, player_id)
    points: list[dict] = []

    for m in matches:
        role = "player_a" if m.player_a_id == player_id else "player_b"
        opp_id = m.player_b_id if m.player_a_id == player_id else m.player_a_id

        sets = db.query(GameSet).filter(GameSet.match_id == m.id).all()
        set_ids = [s.id for s in sets]
        if not set_ids:
            continue
        rallies = db.query(Rally).filter(Rally.set_id.in_(set_ids)).all()
        if not rallies:
            continue

        if metric == "win_rate":
            wins = sum(1 for r in rallies if r.winner == role)
            value = round(wins / len(rallies), 4)

        elif metric == "serve_win_rate":
            serve_rallies = [r for r in rallies if r.server == role]
            if not serve_rallies:
                continue
            value = round(
                sum(1 for r in serve_rallies if r.winner == role) / len(serve_rallies), 4
            )

        elif metric == "avg_rally_length":
            value = round(sum(r.rally_length for r in rallies) / len(rallies), 2)

        else:
            continue

        strength = strength_cache.get(opp_id, 0.5)
        points.append({
            "match_id": m.id,
            "date": str(m.date),
            "value": value,
            "strength_weight": strength,
            "opponent_id": opp_id,
        })

    return points


def strength_weighted_moving_avg(
    points: list[dict],
    window_size: int = 3,
) -> list[dict]:
    """
    各ポイントについて strength_weight を加味した移動平均を計算する。

    通常の移動平均に加え、相手強度重み付き移動平均も付与する。

    Returns:
        points に "moving_avg" と "weighted_moving_avg" を追加したリスト
    """
    result = [dict(p) for p in points]
    n = len(result)

    for i in range(n):
        if i + 1 >= window_size:
            window = result[i + 1 - window_size : i + 1]
            # 通常移動平均
            result[i]["moving_avg"] = round(
                sum(p["value"] for p in window) / window_size, 4
            )
            # 強度重み付き移動平均
            total_w = sum(p.get("strength_weight", 0.5) for p in window)
            if total_w > 0.01:
                result[i]["weighted_moving_avg"] = round(
                    sum(p["value"] * p.get("strength_weight", 0.5) for p in window) / total_w, 4
                )
            else:
                result[i]["weighted_moving_avg"] = result[i]["moving_avg"]
        else:
            result[i]["moving_avg"] = None
            result[i]["weighted_moving_avg"] = None

    return result


def compute_growth_trend(
    points: list[dict],
    window_size: int,
    metric: str,
    trend_delta: float = 0.03,
) -> dict:
    """
    time series points からトレンドを判定する。
    通常値と強度補正値の両方について trend を返す。

    Returns:
        {
          "trend": "improving"|"stable"|"declining"|"pending",
          "trend_delta": float,
          "weighted_trend": "improving"|"stable"|"declining"|"pending",
          "weighted_trend_delta": float,
        }
    """
    base = {
        "trend": "pending",
        "trend_delta": 0.0,
        "weighted_trend": "pending",
        "weighted_trend_delta": 0.0,
    }

    if len(points) < window_size * 2:
        return base

    def _trend(values: list[float]) -> tuple[str, float]:
        if not values or len(values) < window_size * 2:
            return "pending", 0.0
        early = sum(values[:window_size]) / window_size
        recent = sum(values[-window_size:]) / window_size
        delta = round(recent - early, 4)
        if metric == "avg_rally_length":
            return "stable", delta
        if delta >= trend_delta:
            return "improving", delta
        if delta <= -trend_delta:
            return "declining", delta
        return "stable", delta

    normal_values = [p["value"] for p in points]
    wt, wd = _trend(normal_values)
    base["trend"] = wt
    base["trend_delta"] = wd

    weighted_values = [
        p.get("weighted_moving_avg") or p["value"]
        for p in points
    ]
    wwt, wwd = _trend(weighted_values)
    base["weighted_trend"] = wwt
    base["weighted_trend_delta"] = wwd

    return base
