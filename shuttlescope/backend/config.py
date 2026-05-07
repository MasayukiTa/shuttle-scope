"""ShuttleScope バックエンド設定・定数定義"""
import pathlib
import warnings
from pydantic_settings import BaseSettings

# プロジェクトルート（shuttlescope/）を絶対パスで特定
_ROOT = pathlib.Path(__file__).resolve().parent.parent

_WEAK_KEYS = frozenset({
    "", "development-secret-key", "secret", "changeme",
    "password", "admin", "shuttlescope", "your-secret-key",
})


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
    # rereview defense-in-depth: loopback (127.0.0.1) からの JWT 無し API/WS 緩和を
    # 強制的に殺すスイッチ。SS_ALLOW_LOOPBACK_NO_AUTH=0 で常時 JWT 必須。
    # 既定は True (Electron 単体運用での PIN 選択 UX を維持)。
    # 本番 (cloudflared / nginx / SSH forward) では 0 に設定する。
    ALLOW_LOOPBACK_NO_AUTH: bool = True
    # API ドキュメント非表示: SS_HIDE_API_DOCS=1 で /docs /redoc /openapi.json を無効化
    # PUBLIC_MODE=True でも同様に無効化されるが、クラスタルーターを残したまま docs だけ消したい場合に使う
    HIDE_API_DOCS: bool = False
    # スタックトレース隠蔽: SS_HIDE_STACK_TRACES=1 で 500 エラーの詳細をクライアントに返さない
    # PUBLIC_MODE=True でも同様に隠蔽されるが、PUBLIC_MODE を使わず本番運用する場合に使う
    HIDE_STACK_TRACES: bool = False
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
    # ループバック専用オペレーション用トークン（未設定時は無効）
    ss_operator_token: str = ""
    # クリップ抽出並列度 (0=自動: cpu_count に応じて決定)
    ss_clip_workers: int = 0
    # ffmpeg 内部スレッド数/プロセス (0=自動: cpu_count // workers)
    ss_clip_ffmpeg_threads: int = 0
    # YouTube Live 録画アーカイブ先（HDD 上の専用サブディレクトリ）
    # 例: SS_LIVE_ARCHIVE_ROOT=E:\shuttlescope_archive
    # 未設定時はアーカイブなし（SSD 上に留まる）
    # 重要: HDD のルートや別用途フォルダを指定しないこと。
    #       このパス以外の同一ドライブへのアクセスは Electron 側で封鎖される。
    ss_live_archive_root: str = ""
    # 動画パスジェイルの追加許可ディレクトリ（; 区切り）
    # ユーザーが ss_video_root 以外の場所から動画をインポートする場合、
    # ここに明示的に列挙したディレクトリのみ許可される。
    # 例: SS_VIDEO_EXTRA_ROOTS=D:\my_videos;F:\backup\matches
    # 未列挙のパス（特に HDD のドローン映像等）はバックエンド側で拒否される。
    ss_video_extra_roots: str = ""
    # ── Phase A: データ保護鍵 (3 つを用途分離) ─────────────────────────────
    # A1: フィールドレベル透過暗号化用 Fernet 鍵 (32 bytes base64)
    # 生成: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # 未設定時は警告ログ + 平文保存にフォールバック (本番では必ず設定すること)
    ss_field_encryption_key: str = ""
    # A2: バックアップ ZIP の AES-256 パスフレーズ
    # 生成: python -c "import secrets; print(secrets.token_hex(32))"
    ss_backup_passphrase: str = ""
    # A3: Export パッケージ HMAC-SHA256 署名鍵
    # 生成: python -c "import secrets; print(secrets.token_hex(32))"
    ss_export_signing_key: str = ""
    # ── M-A: メール / Turnstile / 招待 ───────────────────────────────────
    # M-A1: メール送信バックエンド ("console" / "mailchannels_worker" / "noop")
    ss_mail_backend: str = "console"
    ss_mail_from: str = "no-reply@shuttle-scope.com"
    ss_mail_from_name: str = "ShuttleScope"
    ss_mailchannels_worker_url: str = ""
    ss_mailchannels_worker_auth_token: str = ""
    # M-A: アプリ公開 URL (検証メール本文のリンクで使う)
    ss_app_base_url: str = "https://app.shuttle-scope.com"
    # M-A3: メール経由トークンの HMAC 鍵 (Phase A の鍵とは独立)
    # 生成: python -c "import secrets; print(secrets.token_hex(32))"
    ss_email_token_hmac_key: str = ""
    ss_email_token_ttl_minutes: int = 15
    ss_invite_token_ttl_hours: int = 72
    # M-A5: Cloudflare Turnstile
    ss_turnstile_site_key: str = ""
    ss_turnstile_secret_key: str = ""
    # 1=Turnstile 必須、0=未設定時はスキップ可能 (dev 用)
    ss_turnstile_required: int = 0
    # M-A: register API の有効化フラグ。デフォルト 0 = 無効 (503 を返す)。
    # メール配信が確実に動作する環境 (Cloudflare Worker 設定済) でのみ 1 に設定する。
    # 無効時はフロントから「現在は問い合わせ経由のみ」と案内し、admin が invitation を発行する運用。
    ss_registration_enabled: int = 0
    # M-A: password reset API の有効化フラグ。同上の理由でデフォルト 0。
    ss_password_reset_enabled: int = 0
    # ── Phase Pay-1: 課金 / 決済 ────────────────────────────────────────
    # フロント完全非公開、API も SS_BILLING_ENABLED=0 の間は 503。
    # 2027 年の有償切替時に 1 へ。
    ss_billing_enabled: int = 0
    ss_billing_report_price_jpy: int = 500
    ss_billing_return_url: str = "https://app.shuttle-scope.com/billing/done"
    ss_billing_cancel_url: str = "https://app.shuttle-scope.com/billing/cancel"
    # Stripe (カード / Apple Pay / Google Pay / 国際カード)
    ss_stripe_public_key: str = ""
    ss_stripe_secret_key: str = ""
    ss_stripe_webhook_secret: str = ""
    # KOMOJU (PayPay / メルペイ / 楽天ペイ / LINE Pay / コンビニ / 銀行振込)
    ss_komoju_public_key: str = ""
    ss_komoju_secret_key: str = ""
    ss_komoju_webhook_secret: str = ""
    ss_komoju_api_base: str = "https://komoju.com/api/v1"
    # Univapay (d 払い / au PAY) — Phase Pay-3 で本実装
    ss_univapay_app_token: str = ""
    ss_univapay_app_secret: str = ""
    ss_univapay_webhook_secret: str = ""
    # ── Phase Pay-1 法的情報 (env で完全管理、コード/git に重要情報を一切置かない) ──
    # 表示は VITE_SS_BILLING_UI_ENABLED=true でフロントが ON にしたとき + 値が設定されたとき。
    ss_legal_company_name: str = ""          # 事業者名 (法人名 or 個人事業主氏名)
    ss_legal_representative: str = ""        # 代表者氏名
    ss_legal_address: str = ""               # 所在地
    ss_legal_phone: str = ""                 # 電話番号 (「請求があれば遅滞なく開示」で省略可)
    ss_legal_phone_disclosure_policy: str = "請求があった場合は遅滞なく開示します"
    ss_legal_email: str = "support@shuttle-scope.com"
    ss_legal_business_hours: str = "平日 10:00〜18:00 (土日祝休業)"
    ss_legal_extra_fees: str = "決済手数料はお客様負担なし"
    ss_legal_payment_timing: str = "ご注文時に即時"
    ss_legal_delivery_timing: str = "ご決済完了後、即時提供 (デジタル配信)"
    ss_legal_refund_policy: str = "デジタル商品の性質上、提供開始後の返金はお受けできません。決済不具合等は support までご連絡ください。"
    # インボイス制度 (適格請求書) 登録番号 "T" + 13 桁。未取得時は空文字。
    ss_invoice_registration_number: str = ""
    # 消費税率 (デジタル販売は標準税率 10%、軽減税率対象外)
    ss_consumption_tax_rate: float = 0.10
    # ── R-3: Worker 共有 (HTTP only、予備実装) ────────────────────────
    # SS_WORKER_AUTH_TOKEN が空なら Worker 機能は完全 OFF (503)。
    # 値があれば /api/_internal/videos/* が X-Worker-Token ヘッダで認証受付。
    # 現地 Worker PC が持ち込めない場合のクラウド/オフサイト Worker 用。
    ss_worker_auth_token: str = ""
    # ── 既知 env 変数の declare-only stub (extra_forbidden 回避) ───────────────
    # .env.development には以下 5 つが入っていて backend では別経路で参照される
    # (R-1 sender 側 / 公開リクエスト TTL / 課金 UI flag) が、Settings に未宣言で
    # `extra_forbidden` で起動拒否される pre-existing 問題があった。
    # 本番未影響だが unit test では import 失敗して開発体験が落ちるため declare のみ追加。
    ss_otp_ttl_minutes: int = 10
    ss_temp_password_ttl_hours: int = 24
    ss_sender_max_recording_duration_min: int = 180
    ss_public_request_ttl_hours: int = 72
    vite_ss_billing_ui_enabled: bool = False

    class Config:
        # .env.development を優先、なければ .env を読む（絶対パス指定でCWD非依存）
        env_file = (str(_ROOT / ".env.development"), str(_ROOT / ".env"))

    # ── 本番姿勢判定 (SEC-001) ────────────────────────────────────────────
    # 本番姿勢である = OpenAPI/docs 露出を切る、benchmark / cluster ルータを
    # 隠す、TrustedHost を実 hostname に絞る、bootstrap-status を admin only
    # にする、レガシーヘッダ認証を拒否する、等の安全側にデフォルトを倒す。
    #
    # 何があれば「本番姿勢」とみなすか:
    #   - PUBLIC_MODE=true                  (明示)
    #   - HIDE_API_DOCS=true                (明示)
    #   - HIDE_STACK_TRACES=true            (明示)
    #   - ENVIRONMENT=production            (環境タグ)
    #   - CLOUDFLARE_TUNNEL_HOSTNAME と CF_PUBLIC_HOST が一致 (露出ホスト動作)
    #
    # ※ 過去の `_PRODUCTION_INTENT` 変数は SECRET_KEY 起動拒否でのみ使われていた
    #    が、これを property として 1 箇所に統合し各 main.py ガードで参照する。
    @property
    def is_production_posture(self) -> bool:
        import os as _os
        if self.PUBLIC_MODE or self.HIDE_API_DOCS or self.HIDE_STACK_TRACES:
            return True
        env = (self.ENVIRONMENT or _os.environ.get("ENVIRONMENT", "")).strip().lower()
        if env == "production":
            return True
        # 公開ホスト名が明示されている (Cloudflare 経由公開) なら本番扱い
        if _os.environ.get("SS_PUBLIC_HOSTNAME", "").strip():
            return True
        return False


settings = Settings()

# 起動時に弱い秘密鍵を検出して警告・拒否
# 本番姿勢 (PUBLIC_MODE / HIDE_API_DOCS / HIDE_STACK_TRACES / ENVIRONMENT=production /
# SS_PUBLIC_HOSTNAME) のいずれかが立っていれば弱鍵のままでは起動させない。
# 過去の `_PRODUCTION_INTENT` 変数は SEC-001 で `is_production_posture` プロパティ
# に統合した。
if settings.SECRET_KEY in _WEAK_KEYS:
    if settings.is_production_posture:
        raise RuntimeError(
            "本番モード（PUBLIC_MODE/HIDE_API_DOCS/HIDE_STACK_TRACES/ENVIRONMENT=production）で\n"
            "SECRET_KEY がデフォルト値または空です。\n"
            "環境変数 SECRET_KEY に十分なランダム文字列を設定してください:\n"
            "  python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    warnings.warn(
        "SECRET_KEY がデフォルト値です。本番公開前に必ず変更してください。",
        stacklevel=2,
    )

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
