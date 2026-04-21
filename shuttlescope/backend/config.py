"""ShuttleScope バックエンド設定・定数定義"""
import pathlib
from pydantic_settings import BaseSettings

# プロジェクトルート（shuttlescope/）を絶対パスで特定
_ROOT = pathlib.Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite:///./backend/db/shuttlescope.db"
    API_PORT: int = 8765
    SECRET_KEY: str = "development-secret-key"
    ENVIRONMENT: str = "development"
    BOOTSTRAP_ADMIN_USERNAME: str = "admin"
    BOOTSTRAP_ADMIN_PASSWORD: str = ""
    BOOTSTRAP_ADMIN_DISPLAY_NAME: str = "Admin"
    # R-002: LAN共有モード（0.0.0.0バインドでLAN内アクセスを可能にする）
    LAN_MODE: bool = False
    # 公開モード: SS_PUBLIC_MODE=1 でクラスタ/ベンチマーク/DB保守ルーターをマウント除外
    PUBLIC_MODE: bool = False
    # ngrok 認証トークン（環境変数 NGROK_AUTHTOKEN から自動読み込み）
    NGROK_AUTHTOKEN: str = ""
    # Cloudflare Tunnel (named tunnel) 設定
    CLOUDFLARE_TUNNEL_NAME: str = "shuttlescope"
    CLOUDFLARE_TUNNEL_HOSTNAME: str = "app.shuttle-scope.com"
    # 実運用 config は repo 外を推奨。未設定時は tunnel.py 側で
    # ~/.cloudflared/config.yml -> ~/Desktop/cloudflare-shuttle-scope/config.yml
    # の順に探索する。
    CLOUDFLARE_TUNNEL_CONFIG: str = ""

    # ── INFRA Phase A: GPU / クラスタ関連設定 ─────────────────────────
    # デフォルトはすべて無効。非 CUDA / 未インストール環境で既存動作を壊さない。
    ss_use_gpu: int = 0                       # 1 で CUDA 経路を試みる
    ss_cuda_device: int = 0                   # 複数 GPU 時のデバイス index
    ss_cluster_mode: str = "off"              # "off" | "ray" （Phase D）
    ss_ray_address: str = "auto"              # Ray head アドレス
    ss_video_root: str = str(_ROOT / "videos")
    ss_cache_root: str = str(_ROOT / "backend" / "cache")
    ss_cv_mock: int = 0                       # 1 でテスト用 mock inferencer を優先使用
    # Phase C 用。Phase A では宣言のみ（参照はされない）。
    ss_line_notify_token: str = ""
    ss_notify_webhook_url: str = ""

    class Config:
        # .env.development を優先、なければ .env を読む（絶対パス指定でCWD非依存）
        env_file = (str(_ROOT / ".env.development"), str(_ROOT / ".env"))


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
