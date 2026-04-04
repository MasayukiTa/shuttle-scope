"""ShuttleScope バックエンド設定・定数定義"""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./shuttlescope.db"
    API_PORT: int = 8765
    SECRET_KEY: str = "development-secret-key"
    ENVIRONMENT: str = "development"

    class Config:
        env_file = ".env"


settings = Settings()

# ショット種別定義
SHOT_TYPES = [
    "short_service", "long_service", "net_shot", "clear",
    "push_rush", "smash", "defensive", "drive", "lob", "drop",
    "cross_net", "slice", "around_head", "cant_reach",
    "flick", "half_smash", "block", "other"
]

SHOT_TYPE_LABELS_JA = {
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

SHOT_KEYBOARD_MAP = {
    "1": "short_service", "2": "long_service",
    "n": "net_shot", "c": "clear", "p": "push_rush",
    "s": "smash", "d": "defensive", "v": "drive",
    "l": "lob", "o": "drop", "x": "cross_net",
    "z": "slice", "a": "around_head", "q": "cant_reach",
    "f": "flick", "h": "half_smash", "b": "block", "0": "other",
}

# ゾーン定義
ZONES_9 = ["BL", "BC", "BR", "ML", "MC", "MR", "NL", "NC", "NR"]
ZONES_12 = ["BLL", "BLC", "BCR", "BRR", "MLL", "MLC", "MCR", "MRR", "NLL", "NLC", "NCR", "NRR"]

# ラリー終了種別
END_TYPES = ["ace", "forced_error", "unforced_error", "net", "out", "cant_reach"]

# 大会レベル
TOURNAMENT_LEVELS = ["IC", "IS", "SJL", "全日本", "国内", "その他"]

# ユーザーロール
USER_ROLES = ["analyst", "coach", "player"]

# 信頼度レベル（ストローク数ベース）
CONFIDENCE_LEVELS = {
    "low": {"min": 0, "max": 500, "stars": "★☆☆", "label": "参考値（データ蓄積中）"},
    "medium": {"min": 500, "max": 2000, "stars": "★★☆", "label": "中程度（解釈に注意）"},
    "high": {"min": 2000, "max": float("inf"), "stars": "★★★", "label": "高信頼（実用レベル）"},
}
