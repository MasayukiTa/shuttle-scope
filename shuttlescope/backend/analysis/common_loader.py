"""
common_loader.py — 解析共通前処理層

各解析エンドポイントが同じ前処理を繰り返すと、
- コードが散在して整合性が取れなくなる
- 研究系特徴量の土台がエンドポイントごとにずれる

このモジュールは解析に必要なデータを一元取得・整形して返す。
すべての解析エンドポイントはこの AnalysisContext を基盤にする。
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date as DateType
from typing import Optional

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.db.models import Match, GameSet, Rally, Stroke
from backend.analysis.player_context import target_role


# ── フィルタ条件 ─────────────────────────────────────────────────────────────

@dataclass
class AnalysisFilters:
    """解析フィルタ条件を一元管理する"""
    result:            Optional[str]     = None   # 'win' / 'loss' / None
    tournament_level:  Optional[str]     = None
    date_from:         Optional[DateType] = None
    date_to:           Optional[DateType] = None
    include_skipped:   bool              = False   # 見逃しラリーを含むか


# ── 解析コンテキスト ──────────────────────────────────────────────────────────

@dataclass
class AnalysisContext:
    """
    解析に必要なデータと補助マッピングを一元保持するコンテキスト。

    Attributes:
        target_player_id:   解析視点の選手 ID
        matches:            フィルタ済み試合リスト
        role_by_match:      match_id → 'player_a'|'player_b' マッピング
        sets:               関連セット一覧
        set_to_match:       set_id → match_id マッピング
        rallies:            関連ラリー一覧 (include_skipped に従う)
        strokes_by_rally:   rally_id → Stroke リスト（load_strokes=True 時のみ）
        filters:            使用したフィルタ条件
        total_strokes:      全ストローク数（信頼度計算用）
    """
    target_player_id: int
    matches: list[Match]              = field(default_factory=list)
    role_by_match: dict[int, str]     = field(default_factory=dict)
    sets: list[GameSet]               = field(default_factory=list)
    set_to_match: dict[int, int]      = field(default_factory=dict)
    rallies: list[Rally]              = field(default_factory=list)
    strokes_by_rally: dict[int, list[Stroke]] = field(default_factory=dict)
    filters: AnalysisFilters          = field(default_factory=AnalysisFilters)
    total_strokes: int                = 0


# ── ローダー ─────────────────────────────────────────────────────────────────

def load_context(
    db: Session,
    player_id: int,
    filters: Optional[AnalysisFilters] = None,
    load_strokes: bool = False,
) -> AnalysisContext:
    """
    指定選手の解析コンテキストを構築して返す。

    Parameters:
        db:           DB セッション
        player_id:    解析対象選手の ID
        filters:      フィルタ条件（None の場合はデフォルト値）
        load_strokes: True の場合 strokes_by_rally も取得する

    Returns:
        AnalysisContext インスタンス
    """
    if filters is None:
        filters = AnalysisFilters()

    ctx = AnalysisContext(target_player_id=player_id, filters=filters)

    # ── 試合取得 ──────────────────────────────────────────────────────────
    q = db.query(Match).filter(
        or_(Match.player_a_id == player_id, Match.player_b_id == player_id)
    )
    if filters.tournament_level:
        q = q.filter(Match.tournament_level == filters.tournament_level)
    if filters.date_from:
        q = q.filter(Match.date >= filters.date_from)
    if filters.date_to:
        q = q.filter(Match.date <= filters.date_to)
    if filters.result in ("win", "loss"):
        opposite = "loss" if filters.result == "win" else "win"
        q = q.filter(
            or_(
                and_(Match.player_a_id == player_id, Match.result == filters.result),
                and_(Match.player_b_id == player_id, Match.result == opposite),
            )
        )
    ctx.matches = q.all()

    if not ctx.matches:
        return ctx

    match_ids = [m.id for m in ctx.matches]
    ctx.role_by_match = {
        m.id: (target_role(m, player_id) or "player_a")
        for m in ctx.matches
    }

    # ── セット取得 ────────────────────────────────────────────────────────
    ctx.sets = db.query(GameSet).filter(GameSet.match_id.in_(match_ids)).all()
    set_ids = [s.id for s in ctx.sets]
    ctx.set_to_match = {s.id: s.match_id for s in ctx.sets}

    if not set_ids:
        return ctx

    # ── ラリー取得 ────────────────────────────────────────────────────────
    rq = db.query(Rally).filter(Rally.set_id.in_(set_ids))
    if not filters.include_skipped:
        rq = rq.filter(Rally.is_skipped == False)  # noqa: E712
    ctx.rallies = rq.order_by(Rally.set_id, Rally.rally_num).all()

    # ── ストローク取得（オプション）──────────────────────────────────────
    if load_strokes and ctx.rallies:
        rally_ids = [r.id for r in ctx.rallies]
        all_strokes = (
            db.query(Stroke)
            .filter(Stroke.rally_id.in_(rally_ids))
            .order_by(Stroke.rally_id, Stroke.stroke_num)
            .all()
        )
        ctx.total_strokes = len(all_strokes)
        for s in all_strokes:
            ctx.strokes_by_rally.setdefault(s.rally_id, []).append(s)
    else:
        # ストローク総数だけカウント（信頼度計算用に軽量取得）
        if ctx.rallies:
            ctx.total_strokes = sum(r.rally_length for r in ctx.rallies)

    return ctx
