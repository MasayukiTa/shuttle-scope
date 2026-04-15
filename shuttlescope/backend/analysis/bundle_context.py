"""bundle_context.py — 振り返りタブ bundle 用の共有データコンテキスト

Match / GameSet / Rally / Stroke を1回だけロードし、6つのカード計算関数が
同じオブジェクト参照を共有することで、SQL往復コストを削減する。

設計メモ:
- stable 系 5 endpoint (_get_player_matches ベース) はフィルタ (result/tournament_level/
  date_from/date_to) を SQL で適用しており、かつ is_skipped フィルタは適用していない。
- rally_sequence_patterns は _fetch_matches_sets_rallies を使っており、
  プレイヤーのフィルタは一切適用せず、is_skipped=False のラリーのみ集める。
  → ctx.rallies_active は is_skipped=False のラリーだけの list。
- どちらも Stroke はラリーIDに対して一括取得すれば共有できる。
"""
from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy.orm import Session

from backend.analysis.router_helpers import _get_player_matches, _player_role_in_match
from backend.db.models import GameSet, Match, Rally, Stroke


@dataclass
class AnalysisContext:
    """振り返りタブ bundle 用に1回だけ DB を叩いて共有するためのコンテナ"""

    player_id: int
    filters: dict

    # stable endpoint 用: _get_player_matches でフィルタ済み
    matches: list
    match_ids: list
    role_by_match: dict
    sets: list
    set_ids: list
    set_to_match: dict
    rallies: list                 # is_skipped 問わず全ラリー (stable 用)
    rally_ids: list
    strokes: list                 # 上記ラリーの全 Stroke

    # rally_sequence_patterns 用 (_fetch_matches_sets_rallies 互換)
    # 「フィルタなし + is_skipped=False」のフルデータ
    rs_matches: list
    rs_role_by_match: dict
    rs_sets: list
    rs_set_to_match: dict
    rs_rallies: list              # is_skipped=False のみ
    rs_strokes: list

    sample_size: int = 0


def load_context(db: Session, player_id: int, filters: dict) -> AnalysisContext:
    result = filters.get("result")
    tournament_level = filters.get("tournament_level")
    date_from = filters.get("date_from")
    date_to = filters.get("date_to")

    # --- stable 系 (フィルタ適用) ---
    matches = _get_player_matches(
        db, player_id, result, tournament_level, date_from, date_to
    )
    match_ids = [m.id for m in matches]
    role_by_match = {m.id: _player_role_in_match(m, player_id) for m in matches}

    sets = (
        db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
        if match_ids else []
    )
    set_to_match = {s.id: s.match_id for s in sets}
    set_ids = [s.id for s in sets]
    rallies = (
        db.query(Rally).filter(Rally.set_id.in_(set_ids)).all()
        if set_ids else []
    )
    rally_ids = [r.id for r in rallies]
    strokes = (
        db.query(Stroke).filter(Stroke.rally_id.in_(rally_ids)).all()
        if rally_ids else []
    )

    # --- rally_sequence_patterns 用 (フィルタなし + is_skipped=False) ---
    # フィルタがすべて default (None/"all") で matches と同一とみなせる場合は
    # re-fetch せず使い回す。
    no_filter = (
        (result is None or result == "all")
        and not tournament_level
        and not date_from
        and not date_to
    )

    if no_filter:
        rs_matches = matches
        rs_role_by_match = role_by_match
        rs_sets = sets
        rs_set_to_match = set_to_match
        rs_rallies = [r for r in rallies if not r.is_skipped]
        # strokes は rally_id で絞るだけ (再クエリ不要)
        rs_rally_id_set = {r.id for r in rs_rallies}
        rs_strokes = [s for s in strokes if s.rally_id in rs_rally_id_set]
    else:
        rs_matches = (
            db.query(Match)
            .filter(
                (Match.player_a_id == player_id)
                | (Match.player_b_id == player_id)
            )
            .all()
        )
        rs_match_ids = [m.id for m in rs_matches]
        rs_role_by_match = {
            m.id: _player_role_in_match(m, player_id) for m in rs_matches
        }
        rs_sets = (
            db.query(GameSet).filter(GameSet.match_id.in_(rs_match_ids)).all()
            if rs_match_ids else []
        )
        rs_set_to_match = {s.id: s.match_id for s in rs_sets}
        rs_set_ids = [s.id for s in rs_sets]
        if rs_set_ids:
            rs_rallies = (
                db.query(Rally)
                .filter(Rally.set_id.in_(rs_set_ids))
                .filter(Rally.is_skipped == False)  # noqa: E712
                .all()
            )
        else:
            rs_rallies = []
        rs_rally_ids = [r.id for r in rs_rallies]
        rs_strokes = (
            db.query(Stroke).filter(Stroke.rally_id.in_(rs_rally_ids)).all()
            if rs_rally_ids else []
        )

    return AnalysisContext(
        player_id=player_id,
        filters=dict(filters),
        matches=matches,
        match_ids=match_ids,
        role_by_match=role_by_match,
        sets=sets,
        set_ids=set_ids,
        set_to_match=set_to_match,
        rallies=rallies,
        rally_ids=rally_ids,
        strokes=strokes,
        rs_matches=rs_matches,
        rs_role_by_match=rs_role_by_match,
        rs_sets=rs_sets,
        rs_set_to_match=rs_set_to_match,
        rs_rallies=rs_rallies,
        rs_strokes=rs_strokes,
        sample_size=len(strokes),
    )
