"""
conformal_loader.py — DB からコンフォーマル予測用ラリー結果サンプルを構築する

exploitability_loader の構造を踏襲する:
  - _get_player_matches / _player_role_in_match を使う
  - ショット種別は 7 バケットに粗化 (bucket_shot を再利用)
  - デフォルト (coarse=True) でフィーチャーグループ = (score_phase, player_role, dominant_shot_bucket)
    の 3 次元キー

返り値:
  [{"group": <feature_key>, "win": 0|1}, ...]  (ラリー 1 件 = 1 レコード)
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional

from sqlalchemy.orm import Session

from backend.db.models import GameSet, Rally, Stroke
from backend.analysis.router_helpers import _get_player_matches, _player_role_in_match
from backend.analysis.state_spec import classify_score_phase, classify_player_role
from backend.analysis.exploitability_loader import bucket_shot, coarse_state_key


def _dominant_shot_bucket(strokes: list, player_role: str) -> Optional[str]:
    """ラリー内で対象選手が最も多く打ったショットバケットを返す。

    ストロークが存在しない、または全て shot_type 不明な場合は None。
    """
    counts: dict[str, int] = defaultdict(int)
    for s in strokes:
        if s.player == player_role:
            b = bucket_shot(s.shot_type)
            if b is not None:
                counts[b] += 1
    if not counts:
        return None
    return max(counts, key=lambda k: counts[k])


def load_rally_outcome_samples(
    db: Session,
    player_id: int,
    *,
    coarse: bool = True,
) -> list[dict]:
    """player_id の全試合から per-rally サンプルを返す。

    各サンプル: {"group": <feature_key_str>, "win": 0|1}

    feature_key (coarse=True):
        "{score_phase}|{player_role}|{dominant_shot_bucket}"
    勝敗不明 / ストロークなし / shot_type 不明のラリーはスキップする。
    """
    matches = _get_player_matches(db, player_id)
    if not matches:
        return []

    match_ids = [m.id for m in matches]
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in matches}

    sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_ids = [s.id for s in sets]
    set_to_match: dict[int, int] = {s.id: s.match_id for s in sets}

    if not set_ids:
        return []

    rallies = (
        db.query(Rally)
        .filter(Rally.set_id.in_(set_ids), Rally.is_skipped == False)  # noqa: E712
        .all()
    )
    if not rallies:
        return []

    rally_ids = [r.id for r in rallies]

    # ストロークを一括取得し rally_id → stroke リストで保持
    all_strokes = (
        db.query(Stroke)
        .filter(Stroke.rally_id.in_(rally_ids))
        .order_by(Stroke.rally_id, Stroke.stroke_num)
        .all()
    )
    strokes_by_rally: dict[int, list] = defaultdict(list)
    for s in all_strokes:
        strokes_by_rally[s.rally_id].append(s)

    samples: list[dict] = []

    for rally in rallies:
        if not rally.winner:
            continue  # 勝者不明はスキップ

        mid = set_to_match.get(rally.set_id)
        if mid is None:
            continue
        role = role_by_match.get(mid)
        if not role:
            continue

        # スコアフェーズ (ラリー終了後スコアを "このラリー" のコンテキストとして使用)
        if role == "player_a":
            my_score = rally.score_a_after
            opp_score = rally.score_b_after
        else:
            my_score = rally.score_b_after
            opp_score = rally.score_a_after

        score_phase = classify_score_phase(my_score, opp_score)
        player_role_label = classify_player_role(rally.server, role)  # "server" or "receiver"

        strokes = strokes_by_rally.get(rally.id, [])

        # ラリー内の主要ショットバケット
        dom_bucket = _dominant_shot_bucket(strokes, role)
        if dom_bucket is None:
            continue  # ショット情報なしはスキップ

        # フィーチャーキー構築
        if coarse:
            group = f"{score_phase}|{player_role_label}|{dom_bucket}"
        else:
            # 細粒度: 将来拡張用 (現在は coarse と同じ)
            group = f"{score_phase}|{player_role_label}|{dom_bucket}"

        win = 1 if rally.winner == role else 0
        samples.append({"group": group, "win": win})

    return samples
