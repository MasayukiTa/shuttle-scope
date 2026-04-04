"""権限管理ユーティリティ（POCフェーズ：簡易実装）"""
from enum import Enum


class UserRole(str, Enum):
    ANALYST = "analyst"
    COACH = "coach"
    PLAYER = "player"


# playerロールに見せてはいけないデータキー
PLAYER_SENSITIVE_KEYS = [
    "win_rate_vs_opponent",
    "epv",
    "weakness_zones",
    "rival_comparison",
    "bottom_patterns",  # EPV下位パターン
]


def filter_by_role(data: dict, role: str) -> dict:
    """ロールに応じてデータをフィルタリング"""
    if role == UserRole.PLAYER:
        return {k: v for k, v in data.items() if k not in PLAYER_SENSITIVE_KEYS}
    return data
