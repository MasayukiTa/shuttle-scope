"""
optimal_transport_loader.py — OT スタイル距離解析用 DB ローダ (Research)

ゾーンヒストグラムを DB から組み立て、コスト行列を提供する。

ゾーン座標マップについて:
  backend/tracknet/zone_mapper.py の既存区切り値を再利用して
  各ゾーンの重心座標 (x, y) を正規化コート座標系 [0,1]×[0,1] で定義する。

  zone_mapper.py の区切り値:
    Y_BACK = 0.50  (y > 0.50 → Back、y <= 0.25 → Net、その他 → Mid)
    Y_NET  = 0.25
    X_LEFT = 0.33  (x <= 0.33 → Left、x > 0.67 → Right、その他 → Center)
    X_RIGHT= 0.67

  各ゾーンの重心 = 領域の中点:
    行 B (Back):  y_min=0.50, y_max=1.00  → 重心 y = 0.750
    行 M (Mid):   y_min=0.25, y_max=0.50  → 重心 y = 0.375
    行 N (Net):   y_min=0.00, y_max=0.25  → 重心 y = 0.125
    列 L (Left):  x_min=0.00, x_max=0.33  → 重心 x = 0.165
    列 C (Center):x_min=0.33, x_max=0.67  → 重心 x = 0.500
    列 R (Right): x_min=0.67, x_max=1.00  → 重心 x = 0.835

セキュリティ:
  allowed_player_ids が指定された場合、参照選手以外のコホートは
  その集合に属する選手_id のみに絞り込む。None のときは制限なし。
  呼び出し元エンドポイントはチームスコープで許可された
  player_id の集合を渡す責任を持つ。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

import numpy as np
from sqlalchemy.orm import Session

from backend.db.models import Match, GameSet, Rally, Stroke

# ---------------------------------------------------------------------------
# ゾーンラベルと座標マップ
# ---------------------------------------------------------------------------

# zone_mapper.py の区切り値から導出した各ゾーン重心 (x, y) 正規化座標
# キー: ゾーンラベル (Stroke.land_zone と同じ 2 文字コード)
# 値: (x, y) タプル、[0,1]×[0,1]
_ZONE_CENTROID_MAP: dict[str, tuple[float, float]] = {
    # Back 行 (y = 0.750)
    "BL": (0.165, 0.750),
    "BC": (0.500, 0.750),
    "BR": (0.835, 0.750),
    # Mid 行 (y = 0.375)
    "ML": (0.165, 0.375),
    "MC": (0.500, 0.375),
    "MR": (0.835, 0.375),
    # Net 行 (y = 0.125)
    "NL": (0.165, 0.125),
    "NC": (0.500, 0.125),
    "NR": (0.835, 0.125),
}

# ゾーンラベルの正規順序 (ヒストグラムの軸順序を固定)
ZONE_LABELS: list[str] = ["BL", "BC", "BR", "ML", "MC", "MR", "NL", "NC", "NR"]

# 既知ゾーンの高速引き当てセット
_VALID_ZONES: frozenset[str] = frozenset(ZONE_LABELS)


def build_cost_matrix(zone_labels: list[str] = ZONE_LABELS) -> np.ndarray:
    """ゾーン間ユークリッド距離行列を [0,1] に正規化して返す。

    zone_labels : ゾーンラベルのリスト (デフォルト = ZONE_LABELS)
    返り値      : K×K ndarray (対角 = 0、最大値 ≤ 1)

    正規化: コート対角線の長さ = sqrt(2) で割る (最大距離を ≤ 1 にする)
    """
    K = len(zone_labels)
    coords = np.array(
        [_ZONE_CENTROID_MAP[z] for z in zone_labels], dtype=float
    )   # (K, 2)

    # ペアワイズユークリッド距離
    diff = coords[:, None, :] - coords[None, :, :]   # (K, K, 2)
    dist = np.sqrt((diff ** 2).sum(axis=-1))           # (K, K)

    # コート対角線 sqrt(1^2 + 1^2) = sqrt(2) で正規化
    max_dist = np.sqrt(2.0)
    dist /= max_dist

    # 数値誤差で対角が tiny にならないよう明示的にゼロ化
    np.fill_diagonal(dist, 0.0)
    return dist


# ---------------------------------------------------------------------------
# DB ローダ
# ---------------------------------------------------------------------------

def load_zone_histograms(
    db: Session,
    player_id: int,
    *,
    allowed_player_ids: Optional[set[int]] = None,
    min_matches: int = 3,
) -> dict[int, np.ndarray]:
    """参照選手 + コホート選手の land_zone 正規化ヒストグラム辞書を返す。

    db              : SQLAlchemy Session
    player_id       : 解析対象の選手 ID (参照選手)
    allowed_player_ids: コホートを絞り込む許可済み選手 ID 集合。
                      None のときは制限なし。
                      【セキュリティ】エンドポイントはチームスコープ内の
                      player_id のみをここに渡す。
    min_matches     : コホートに含める最低試合数 (参照選手には適用しない)

    返り値: {player_id: normalized_histogram}
      - ヒストグラムは ZONE_LABELS の順で長さ 9 の ndarray
      - 和 = 1 (有効ゾーンストロークが 0 件の選手は除外)

    処理の流れ:
      1. 全選手の Match を取得し、試合数カウントでコホートを選別
      2. コホート + 参照選手のストロークを一括取得
      3. 各選手の land_zone 集計 → 正規化
    """
    K = len(ZONE_LABELS)
    zone_index = {z: i for i, z in enumerate(ZONE_LABELS)}

    # ── 参照選手の試合 ─────────────────────────────────────────────────────
    ref_matches = (
        db.query(Match)
        .filter((Match.player_a_id == player_id) | (Match.player_b_id == player_id))
        .all()
    )
    ref_match_ids: set[int] = {m.id for m in ref_matches}

    # ── コホート候補: 全選手の試合数を集計 ────────────────────────────────
    # match テーブルで player_a_id / player_b_id の出現回数を数える
    # 大量の試合がある環境では群別クエリが望ましいが、
    # ローカル SQLite 規模では全件取得で十分 (honesty: スケール限界あり)

    all_matches = db.query(Match).all()

    # 試合数カウント {player_id: set of match_id}
    player_match_ids: dict[int, set[int]] = defaultdict(set)
    for m in all_matches:
        player_match_ids[m.player_a_id].add(m.id)
        player_match_ids[m.player_b_id].add(m.id)

    # コホート選手 = 自分以外 かつ 試合数 >= min_matches
    # かつ allowed_player_ids フィルタ (セキュリティ必須)
    cohort_ids: list[int] = []
    for pid, mids in player_match_ids.items():
        if pid == player_id:
            continue
        if len(mids) < min_matches:
            continue
        if allowed_player_ids is not None and pid not in allowed_player_ids:
            continue   # チームスコープ外は除外
        cohort_ids.append(pid)

    # 対象選手 ID セット (参照 + コホート)
    target_ids: set[int] = {player_id} | set(cohort_ids)

    # ── ストローク取得: 対象選手 ID に紐づく全ストロークを一括取得 ────────
    # Match → GameSet → Rally → Stroke と辿る
    target_match_ids: set[int] = set()
    for m in all_matches:
        if m.player_a_id in target_ids or m.player_b_id in target_ids:
            target_match_ids.add(m.id)

    if not target_match_ids:
        return {}

    sets = (
        db.query(GameSet)
        .filter(GameSet.match_id.in_(list(target_match_ids)))
        .all()
    )
    if not sets:
        return {}
    set_ids = [s.id for s in sets]
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}

    rallies = (
        db.query(Rally)
        .filter(Rally.set_id.in_(set_ids), Rally.is_skipped == False)  # noqa: E712
        .all()
    )
    if not rallies:
        return {}
    rally_ids = [r.id for r in rallies]
    rally_to_set: dict[int, int] = {r.id: r.set_id for r in rallies}

    # match_id → (player_a_id, player_b_id) の逆引き
    match_players: dict[int, tuple[int, int]] = {
        m.id: (m.player_a_id, m.player_b_id) for m in all_matches
    }

    # rally_id → (player_a_id, player_b_id) を合成
    rally_to_players: dict[int, tuple[int, int]] = {}
    for r in rallies:
        mid = set_to_match.get(r.set_id)
        if mid and mid in match_players:
            rally_to_players[r.id] = match_players[mid]

    strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(rally_ids))
        .all()
    )

    # ── ゾーン集計: 選手 ID ごとに land_zone をカウント ──────────────────
    # Stroke.player は "player_a" / "player_b" / "partner_a" / "partner_b"
    # → match の player_a_id / player_b_id から実 player_id を解決する
    counts: dict[int, np.ndarray] = {pid: np.zeros(K) for pid in target_ids}

    for s in strokes:
        if s.land_zone is None:
            continue
        zone = s.land_zone.strip().upper()
        if zone not in _VALID_ZONES:
            continue
        z_idx = zone_index[zone]

        # ストローク打者の実 player_id を解決
        players_in_rally = rally_to_players.get(s.rally_id)
        if players_in_rally is None:
            continue
        pa_id, pb_id = players_in_rally

        if s.player == "player_a":
            actual_pid = pa_id
        elif s.player == "player_b":
            actual_pid = pb_id
        else:
            # ダブルス partner_a/b は現フェーズでは OT 解析対象外
            continue

        if actual_pid in counts:
            counts[actual_pid][z_idx] += 1.0

    # ── 正規化 ─────────────────────────────────────────────────────────────
    result: dict[int, np.ndarray] = {}
    for pid, cnt in counts.items():
        total = cnt.sum()
        if total == 0.0:
            # 有効ゾーンストロークが 0 件 → 信頼できないため除外
            continue
        result[pid] = cnt / total

    return result
