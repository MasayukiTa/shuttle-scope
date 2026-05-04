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


def target_role(match: Match, player_id: int) -> str | None:
    """
    試合オブジェクトから target_player_id の保存側ロールを返す。
    player_a → 'player_a'
    player_b → 'player_b'
    どちらでもない → None (ダブルスのパートナーなど)
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
    player_b 視点では反転が必要。
    """
    role = target_role(match, player_id)
    if role == "player_a":
        return match.result == "win"
    if role == "player_b":
        return match.result == "loss"
    # パートナーなど: player_a 基準の result をそのまま返す
    return match.result == "win"


def opponent_player_id(match: Match, player_id: int) -> Optional[int]:
    """target_player_id に対する対戦相手の player_id を返す"""
    role = target_role(match, player_id)
    if role == "player_a":
        return match.player_b_id
    if role == "player_b":
        return match.player_a_id
    return None


def partner_player_id(match: Match, player_id: int) -> Optional[int]:
    """ダブルスにおける target_player_id のパートナー ID を返す (シングルスは None)"""
    role = target_role(match, player_id)
    if role == "player_a":
        return match.partner_a_id
    if role == "player_b":
        return match.partner_b_id
    return None


def opponent_role(match: Match, player_id: int) -> Optional[str]:
    """target_player_id の対戦相手側の保存ロール ('player_a' / 'player_b')"""
    role = target_role(match, player_id)
    if role == "player_a":
        return "player_b"
    if role == "player_b":
        return "player_a"
    return None


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
    role = target_role(match, player_id)
    if role == "player_a":
        individual = "player_a"
        partner = "partner_a"
        opponent = "player_b"
    elif role == "player_b":
        individual = "player_b"
        partner = "partner_b"
        opponent = "player_a"
    else:
        # フォールバック
        individual = "player_a"
        partner = "partner_a"
        opponent = "player_b"

    partner_id = partner_player_id(match, player_id)
    return {
        "team_side": role or "player_a",
        "individual_slot": individual,
        "partner_slot": partner,
        "opponent_slot": opponent,
        "partner_id": partner_id,
    }
