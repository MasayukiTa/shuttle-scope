"""
opponent_classifier.py — 相手タイプ多軸分類エンジン (Stage 2-C)

改善点:
  - 単軸 style（攻撃型/守備型/バランス型）→ 5軸分類に拡張
  - 既存 style 出力は後方互換で維持
  - 各軸は純粋関数（副作用なし）で計算

5軸:
  1. style        : 攻撃型 / 守備型 / バランス型  （従来互換）
  2. pace         : fast / medium / slow            （ドライブ・プッシュ率）
  3. rally_length : short / medium / long           （平均ラリー長）
  4. handedness   : right / left / unknown          （Player.dominant_hand）
  5. court_zone   : front / rear / balanced         （前衛 NL/NC/NR 占有率）
"""
from __future__ import annotations
from typing import Optional
from sqlalchemy.orm import Session

from backend.db.models import Match, GameSet, Rally, Stroke, Player
from backend.analysis.analysis_config import AnalysisConfig


# ── 軸別判定定数 ──────────────────────────────────────────────────────────────

# pace: ドライブ + プッシュ の合計比率で判定
_FAST_SHOT_TYPES = {"drive", "push"}
PACE_FAST_THRESHOLD = 0.30   # 30% 以上 → fast
PACE_SLOW_THRESHOLD = 0.10   # 10% 未満 → slow

# court_zone: 前衛ゾーン（NL/NC/NR）の占有率
_FRONT_ZONES = {"NL", "NC", "NR"}
COURT_FRONT_THRESHOLD = 0.45   # 45% 以上 → front
COURT_REAR_THRESHOLD = 0.25    # 25% 未満 → rear


# ── 単試合ラリーデータから相手指標を抽出 ────────────────────────────────────

def _extract_opponent_metrics(
    rallies: list[Rally],
    opp_role: str,
    db: Session,
) -> Optional[dict]:
    """
    単試合のラリー・ストロークデータから相手の指標を抽出する。

    Returns:
        {
          "avg_rally_length": float,
          "smash_rate": float,
          "fast_shot_rate": float,
          "front_zone_rate": float,
        }
        データ不足の場合は None
    """
    if not rallies:
        return None

    rally_ids = [r.id for r in rallies]
    opp_strokes = (
        db.query(Stroke)
        .filter(
            Stroke.rally_id.in_(rally_ids),
            Stroke.player == opp_role,
        )
        .all()
    )
    total = len(opp_strokes)
    if total == 0:
        return None

    avg_len = sum(r.rally_length for r in rallies) / len(rallies)

    smash_cnt = sum(1 for s in opp_strokes if s.shot_type in ("smash", "half_smash"))
    smash_rate = smash_cnt / total

    fast_cnt = sum(1 for s in opp_strokes if s.shot_type in _FAST_SHOT_TYPES)
    fast_shot_rate = fast_cnt / total

    front_cnt = sum(1 for s in opp_strokes if s.hit_zone in _FRONT_ZONES)
    front_zone_rate = front_cnt / total

    return {
        "avg_rally_length": avg_len,
        "smash_rate": smash_rate,
        "fast_shot_rate": fast_shot_rate,
        "front_zone_rate": front_zone_rate,
    }


# ── 5軸分類 ─────────────────────────────────────────────────────────────────

def classify_style(avg_rally_length: float, smash_rate: float) -> str:
    """従来互換の style 軸判定（後方互換）。"""
    if avg_rally_length < AnalysisConfig.ATTACKER_MAX_RALLY_LEN and smash_rate >= AnalysisConfig.ATTACKER_MIN_SMASH_RATE:
        return "攻撃型"
    if avg_rally_length >= AnalysisConfig.DEFENDER_MIN_RALLY_LEN:
        return "守備型"
    return "バランス型"


def classify_pace(fast_shot_rate: float) -> str:
    """pace 軸: ドライブ + プッシュ比率 → fast / medium / slow"""
    if fast_shot_rate >= PACE_FAST_THRESHOLD:
        return "fast"
    if fast_shot_rate < PACE_SLOW_THRESHOLD:
        return "slow"
    return "medium"


def classify_rally_length(avg_rally_length: float) -> str:
    """rally_length 軸: 平均ラリー長 → short / medium / long"""
    if avg_rally_length < AnalysisConfig.ATTACKER_MAX_RALLY_LEN:
        return "short"
    if avg_rally_length >= AnalysisConfig.DEFENDER_MIN_RALLY_LEN:
        return "long"
    return "medium"


def classify_handedness(db: Session, opponent_id: int) -> str:
    """handedness 軸: Player.dominant_hand → right / left / unknown"""
    player = db.get(Player, opponent_id)
    if player and player.dominant_hand:
        hand = player.dominant_hand.strip().upper()
        if hand in ("R", "RIGHT"):
            return "right"
        if hand in ("L", "LEFT"):
            return "left"
    return "unknown"


def classify_court_zone(front_zone_rate: float) -> str:
    """court_zone 軸: 前衛ゾーン占有率 → front / rear / balanced"""
    if front_zone_rate >= COURT_FRONT_THRESHOLD:
        return "front"
    if front_zone_rate < COURT_REAR_THRESHOLD:
        return "rear"
    return "balanced"


# ── 相手1人分の全試合集約分類 ───────────────────────────────────────────────

def classify_opponent(
    db: Session,
    opponent_id: int,
    matches_with_opponent: list[Match],
    player_id: int,
) -> dict:
    """
    複数試合にわたる対戦データから相手の 5 軸分類を計算する。

    Parameters:
        db:                    DB セッション
        opponent_id:           相手選手 ID
        matches_with_opponent: 対戦試合一覧
        player_id:             自分の選手 ID

    Returns:
        {
          "opponent_id": int,
          "axes": {
            "style":        str,   # 攻撃型 / 守備型 / バランス型
            "pace":         str,   # fast / medium / slow
            "rally_length": str,   # short / medium / long
            "handedness":   str,   # right / left / unknown
            "court_zone":   str,   # front / rear / balanced
          },
          "raw": {                 # 分類に使った平均値
            "avg_rally_length": float,
            "smash_rate":       float,
            "fast_shot_rate":   float,
            "front_zone_rate":  float,
          },
          "match_count": int,
        }
    """
    agg = {
        "avg_rally_length": 0.0,
        "smash_rate": 0.0,
        "fast_shot_rate": 0.0,
        "front_zone_rate": 0.0,
    }
    used = 0

    # バルクロード: 全試合ぶんの GameSet/Rally を1クエリずつで取得
    match_ids = [m.id for m in matches_with_opponent]
    sets_by_match: dict[int, list[int]] = {}
    if match_ids:
        for s in db.query(GameSet.id, GameSet.match_id).filter(GameSet.match_id.in_(match_ids)).all():
            sets_by_match.setdefault(s.match_id, []).append(s.id)
    all_set_ids = [sid for sids in sets_by_match.values() for sid in sids]
    rallies_by_set: dict[int, list] = {}
    if all_set_ids:
        for r in db.query(Rally).filter(Rally.set_id.in_(all_set_ids)).all():
            rallies_by_set.setdefault(r.set_id, []).append(r)

    for m in matches_with_opponent:
        opp_role = "player_b" if m.player_a_id == player_id else "player_a"
        set_ids = sets_by_match.get(m.id, [])
        if not set_ids:
            continue
        rallies = [r for sid in set_ids for r in rallies_by_set.get(sid, [])]
        metrics = _extract_opponent_metrics(rallies, opp_role, db)
        if metrics is None:
            continue

        for key in agg:
            agg[key] += metrics[key]
        used += 1

    if used == 0:
        return {
            "opponent_id": opponent_id,
            "axes": {
                "style": "バランス型",
                "pace": "medium",
                "rally_length": "medium",
                "handedness": classify_handedness(db, opponent_id),
                "court_zone": "balanced",
            },
            "raw": agg,
            "match_count": len(matches_with_opponent),
        }

    avg = {k: v / used for k, v in agg.items()}

    return {
        "opponent_id": opponent_id,
        "axes": {
            "style":        classify_style(avg["avg_rally_length"], avg["smash_rate"]),
            "pace":         classify_pace(avg["fast_shot_rate"]),
            "rally_length": classify_rally_length(avg["avg_rally_length"]),
            "handedness":   classify_handedness(db, opponent_id),
            "court_zone":   classify_court_zone(avg["front_zone_rate"]),
        },
        "raw": {k: round(v, 4) for k, v in avg.items()},
        "match_count": len(matches_with_opponent),
    }


# ── プレイヤー全対戦相手に対する分類を集約 ──────────────────────────────────

def classify_all_opponents(
    db: Session,
    player_id: int,
    matches: list[Match],
) -> dict[int, dict]:
    """
    対戦した全相手に対して classify_opponent を実行し、
    opponent_id → 分類結果 の dict を返す。
    """
    # 相手 ID ごとに試合をグループ化
    opp_matches: dict[int, list[Match]] = {}
    for m in matches:
        opp_id = m.player_b_id if m.player_a_id == player_id else m.player_a_id
        opp_matches.setdefault(opp_id, []).append(m)

    return {
        opp_id: classify_opponent(db, opp_id, opp_ms, player_id)
        for opp_id, opp_ms in opp_matches.items()
    }


# ── axes 別集計ユーティリティ ────────────────────────────────────────────────

def aggregate_affinity_by_axis(
    axis: str,
    classified: dict[int, dict],
    matches: list[Match],
    player_id: int,
) -> list[dict]:
    """
    指定軸の分類値ごとに勝率・試合数を集計する。

    Parameters:
        axis:       'style' / 'pace' / 'rally_length' / 'handedness' / 'court_zone'
        classified: classify_all_opponents の返り値
        matches:    全対戦試合一覧
        player_id:  自分の選手 ID

    Returns:
        [{"label": str, "win_rate": float, "match_count": int, "wins": int}, ...]
        勝率降順ソート済み
    """
    stats: dict[str, dict] = {}

    for m in matches:
        opp_id = m.player_b_id if m.player_a_id == player_id else m.player_a_id
        cls = classified.get(opp_id)
        if cls is None:
            continue
        label = cls["axes"].get(axis, "unknown")

        if label not in stats:
            stats[label] = {"wins": 0, "total": 0}

        player_role = "player_a" if m.player_a_id == player_id else "player_b"
        won = (player_role == "player_a" and m.result == "win") or \
              (player_role == "player_b" and m.result == "loss")

        stats[label]["total"] += 1
        if won:
            stats[label]["wins"] += 1

    result = []
    for label, s in stats.items():
        if s["total"] == 0:
            continue
        result.append({
            "label": label,
            "win_rate": round(s["wins"] / s["total"], 3),
            "match_count": s["total"],
            "wins": s["wins"],
        })

    result.sort(key=lambda x: x["win_rate"], reverse=True)
    return result
