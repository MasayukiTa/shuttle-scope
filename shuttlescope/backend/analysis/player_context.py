"""
player_context.py — 解析視点統一ユーティリティ

DB は player_a / player_b という保存形式を持つが、
解析は常に target_player_id 視点で行う必要がある。
このモジュールはその変換を一元管理する。

使用方針:
  - analysis.py / prediction_engine.py / routers 全体でこのモジュールを使う
  - 解析コード内で `match.player_a_id` に直接依存しない
"""
from __future__ import annotations
from typing import Optional
from backend.db.models import Match
from backend.analysis.role_view import (  # noqa: F401  (再公開)
    TeamSide,
    is_opponent_stroke,
    own_slot,
    perspective,
    stroke_side,
    teammate_slot,
)


def involves_player(player_id: int):
    """SQLAlchemy の条件: player_id がその試合に (選手としても相方としても) 出ている。"""
    from sqlalchemy import or_

    return or_(
        Match.player_a_id == player_id,
        Match.player_b_id == player_id,
        Match.partner_a_id == player_id,
        Match.partner_b_id == player_id,
    )


def head_to_head(player_id: int, opponent_id: int):
    """SQLAlchemy の条件: player_id と opponent_id が別のチームで対戦した試合。
    どちらもダブルスの相方として出ている場合を含む。"""
    from sqlalchemy import and_, or_

    def on_a(pid):
        return or_(Match.player_a_id == pid, Match.partner_a_id == pid)

    def on_b(pid):
        return or_(Match.player_b_id == pid, Match.partner_b_id == pid)

    return or_(
        and_(on_a(player_id), on_b(opponent_id)),
        and_(on_b(player_id), on_a(opponent_id)),
    )


def player_result_filter(player_id: int, result: str):
    """SQLAlchemy の条件: player_id から見て result ('win' | 'loss') の試合。
    Match.result は A 側 (player_a と partner_a) から見た勝敗で格納されている。"""
    from sqlalchemy import and_, or_

    opposite = "loss" if result == "win" else "win"
    return or_(
        and_(or_(Match.player_a_id == player_id, Match.partner_a_id == player_id), Match.result == result),
        and_(or_(Match.player_b_id == player_id, Match.partner_b_id == player_id), Match.result == opposite),
    )


def target_role(match: Match, player_id: int) -> str | None:
    """
    試合オブジェクトから target_player_id の保存側ロールを返す。
    player_a → 'player_a'
    player_b → 'player_b'
    どちらでもない → None (ダブルスのパートナーなど)

    注意: ダブルスの相方を解決したい分析では perspective() を使う。
    """
    if match.player_a_id == player_id:
        return "player_a"
    if match.player_b_id == player_id:
        return "player_b"
    return None


def player_wins_match(match: Match, player_id: int) -> bool:
    """
    試合結果を target_player_id 視点の bool に変換する。
    DB の result は player_a 基準で格納されているため、
    player_b 視点 (および partner_b 視点) では反転が必要。

    UR-4 fix: partner_b 側も B サイド勝敗で反転する。
    旧コードは partner_a / partner_b の両方で
    `match.result == 'win'` を返しており、partner_b の勝率が反転していた。
    """
    role = target_role(match, player_id)
    if role == "player_a":
        return match.result == "win"
    if role == "player_b":
        return match.result == "loss"
    # パートナー (ダブルス) — どちらサイドかを直接 ID で判定
    if getattr(match, "partner_a_id", None) == player_id:
        return match.result == "win"
    if getattr(match, "partner_b_id", None) == player_id:
        return match.result == "loss"
    # 該当なし: player_a 基準のまま (シングルスで partner 列が無いケース等)
    return match.result == "win"


def opponent_player_id(match: Match, player_id: int) -> Optional[int]:
    """target_player_id に対する対戦相手 (相手チームの player_a / player_b 枠) の player_id を返す。
    ダブルスの相方が target の場合も相手チームを返す。"""
    view = perspective(match, player_id)
    if view is None:
        return None
    return match.player_b_id if view == "player_a" else match.player_a_id


def partner_player_id(match: Match, player_id: int) -> Optional[int]:
    """ダブルスにおける target_player_id のパートナー ID を返す (シングルスは None)。
    相方が target の場合は、同じチームの player_a / player_b 枠の選手を返す。"""
    view = perspective(match, player_id)
    if view is None:
        return None
    return {
        "player_a": match.partner_a_id,
        "partner_a": match.player_a_id,
        "player_b": match.partner_b_id,
        "partner_b": match.player_b_id,
    }[view.slot]


def opponent_role(match: Match, player_id: int) -> Optional[str]:
    """target_player_id の対戦相手側の保存ロール ('player_a' / 'player_b')"""
    view = perspective(match, player_id)
    if view is None:
        return None
    return "player_b" if view == "player_a" else "player_a"


def resolve_doubles_roles(match: Match, player_id: int) -> dict:
    """
    ダブルス試合での各スロットを target_player 視点で解決する。
    返り値:
      {
        "team_side":       'player_a' | 'player_b',      # 保存側ロール
        "individual_slot": 'player_a' | 'partner_a' | 'player_b' | 'partner_b',
        "partner_slot":    同上,
        "opponent_slot":   同上,
        "partner_id":      int | None,
      }
    """
    view = perspective(match, player_id)
    if view is None:
        # フォールバック (試合に出ていない選手)
        individual, partner, opponent = "player_a", "partner_a", "player_b"
        role = None
    else:
        role = str(view)
        individual = view.slot
        partner = {
            "player_a": "partner_a", "partner_a": "player_a",
            "player_b": "partner_b", "partner_b": "player_b",
        }[view.slot]
        opponent = "player_b" if role == "player_a" else "player_a"

    partner_id = partner_player_id(match, player_id)
    return {
        "team_side": role or "player_a",
        "individual_slot": individual,
        "partner_slot": partner,
        "opponent_slot": opponent,
        "partner_id": partner_id,
    }
