# Security Code Scanning 修正 (2026-04-22)

## 概要

GitHub Code Scanning アラート 41件（critical 4, high 17, medium 20）に対して
以下の修正を実施した。

## 適用済み修正

### [最重要] グローバル認証ミドルウェア — `backend/main.py`

`GlobalAuthMiddleware` を追加。全 `/api/` ルートに Bearer JWT を必須化。
- 除外: `/api/auth/login`, `/api/auth/logout`, `/api/auth/bootstrap-status` のみ
- **`/api/auth/analysts`, `/api/auth/players`, `/api/auth/coaches` は要認証**（実在選手名・ユーザー名の公開防止）
- loopback（Electron ローカル起動）は `is_loopback_request()` で除外（既存の選択ログインUIは引き続き動作）
- CORS preflight（OPTIONS）も除外
- 実行順: CORS → GlobalAuth → AnalysisCache → PlayerAccess → Upload → ルーター

**適用タイミング**: サーバー再起動時に自動で有効になる（コード変更済み）

**2026-04-22 追記**: 当初 `/api/auth/*` を全除外していたため `/api/auth/analysts` 等が無認証公開状態だった。
`_GLOBAL_AUTH_EXEMPT` を絞り込み修正済み。

---

### C-2: SSRF 修正 — `backend/cluster/topology.py:233`

`ping_node()` の HTTP フォールバック内で `ipaddress.ip_address()` による検証を追加。
プライベート/ローカル/リンクローカル以外のアドレスへの HTTP 疎通確認を拒否。
クラスター内（プライベート）アドレスのみ許可。

### H-1: パスインジェクション修正 — `backend/routers/sync.py:372`

`import_from_cloud_path` で `sync_folder` 未設定時（空文字列）に
パストラバーサル検証をスキップしていた問題を修正。
未設定時は HTTP 400 を返す。

### H-3: 安全でない一時ファイル — `backend/benchmark/runner.py:966`

`tempfile.mktemp()` (TOCTOU 脆弱性あり) を
`tempfile.NamedTemporaryFile(delete=False)` に置き換え。

### H-4: ReDoS — `backend/routers/public_site.py:1320`

`re.sub(r"\s+\n", ...)` を `re.sub(r"[^\S\n]+\n", ...)` に変更。
`[^\S\n]+` は改行以外の空白にのみマッチし、バックトラック不要。

### H-5: 不完全な URL 部分文字列サニタイズ — `backend/routers/tunnel.py:97`

`"app.example.com" in text` 文字列包含チェックを
`re.search(r'(?<![.\w])app\.example\.com(?![.\w])', text)` に変更。
部分マッチ（"myapp.example.com" 等）での誤検知を防止。

### H-6: XSS through DOM — `src/components/video/WebViewPlayer.tsx:102`

`handleNavigate` に `https?://` プレフィックス検証を追加。
`javascript:` URL 等の非 HTTP スキームを拒否。

### H-7: 汚染フォーマット文字列 — `src/pages/AnnotatorPage.tsx:3670`

`console.info` の文字列連結で `matchId` を直接埋め込んでいたものを
オブジェクトプロパティとして分離。

### M-1: スタックトレース露出 — 複数ファイル

以下のファイルで `str(exc)` を HTTP レスポンスに直接返していた箇所を修正:
- `backend/routers/cluster.py` — ray start/stop 失敗, ARP スキャン失敗, SSH join 失敗
- `backend/routers/yolo.py` — YOLO warmup 失敗
- `backend/routers/tunnel.py` — 疎通確認失敗
- `backend/routers/network_diag.py` — TCP プローブ失敗

修正方針: `logger.error(..., exc_info=True)` でサーバーにフルスタックを記録し、
HTTP レスポンスは汎用メッセージのみを返す。

### M-2: URL リダイレクト — `backend/main.py:923`

SPA catch-all ルートで `path.lstrip("/")` を追加。
`//evil.com` 形式の path による open redirect を防止。

### 高度攻撃テスト計画時に追加発見・修正済み（2026-04-22）

#### `/api/cache/invalidate` / `/api/cache/stats` — 無認証（main.py:617-627）

「POC用、無認証」のコメントが残っており、認証なしでキャッシュフラッシュ・統計取得が可能だった。
修正: admin ロールのみ許可するよう `get_auth()` チェックを追加。

#### WebSocket 3エンドポイント — JWT検証なし（main.py:ws/live, ws/yolo/realtime, ws/camera）

`/ws/live/{session_code}`, `/ws/yolo/realtime/{session_code}`, `/ws/camera/{session_code}` が
JWT 検証なしで接続を受け付けていた。CSWSH（Cross-Site WebSocket Hijacking）リスク。
修正: `_ws_require_auth()` を `accept()` 前に呼ぶことで以下のルールを適用:
- loopback (127.0.0.1) → 認証不要（Electron）
- ws:// (LAN 直接) → session_code が共有秘密として機能、認証不要（LAN 内のみ）
- wss:// (Cloudflare 経由) → `?token=<jwt>` 必須
フロント側: `DeviceManagerPanel.tsx`, `CameraSenderPage.tsx`, `ViewerPage.tsx` で
`isHttps` のとき `sessionStorage` の JWT を `?token=` に付加するよう修正。

#### H-2 IDOR: `/api/analysis/*` player_id クエリパラメータ未検証（main.py PlayerAccessControlMiddleware）

`PlayerAccessControlMiddleware` の IDOR チェックが URL パスパターンのみを対象としており、
`/api/analysis/heatmap/composite?player_id=5` のようにクエリパラメータで player_id を渡すケースを見落としていた。
player JWT (player_id=12) で他選手 (player_id=5, 107) の解析データ取得が可能だった。

修正: `/api/analysis/` および `/api/reports/` パスに対してクエリパラメータ `player_id` を取得し、
JWT の player_id と不一致なら 403 を返すチェックを追加。

#### H-3 タイミング攻撃: ユーザー名列挙（auth.py login handler）

存在しないユーザー名でのログイン試行が、bcrypt 検証をスキップして即時 (~138ms) 返却していた。
存在するユーザーは bcrypt 検証 (~608ms) を経るため、差 ~469ms でユーザー名の存在を統計的に判定可能だった。

修正 (`backend/routers/auth.py`): ユーザー不在時にもダミーハッシュに対して `_verify_password()` を呼び出し、
レスポンスタイムを均一化。

```python
if not user or not user.hashed_credential:
    # ユーザー不在時もダミーのbcrypt検証を走らせてタイミング差を消す
    _verify_password(secret, "$2b$12$dummyhashfortimingequalizationxxxxxxxxxxxxxxxx")
    log_access(...)
    raise HTTPException(status_code=401, detail="login failed")
```

#### キャッシュIDOR: AnalysisCacheMiddleware がアクセス制御前に実行（main.py）

Starlette は `add_middleware` の逆順でミドルウェアを実行する。
`AnalysisCacheMiddleware`（line 518）が `PlayerAccessControlMiddleware`（line 443）より後に登録されていたため、
実行順では AnalysisCache が先に動き、キャッシュ HIT 時に PlayerAccess を完全にスキップしていた。

さらにキャッシュキーが `X-Role`/`X-Player-Id` ヘッダー（ユーザーが任意に設定可能）を使っていたため、
player JWT ユーザーがアナリストと同一キャッシュキーを生成し、他選手のデータを取得できた。
前述の H-2 IDOR 修正（クエリパラメータ検証）もキャッシュがある状態では完全にバイパスされていた。

修正: キャッシュキーを JWT 検証済み claims（role/player_id/team_name）から生成するよう変更。
`X-Role` 等の生ヘッダーはキャッシュキーに使用しない。

#### bootstrap-status: 管理者ユーザー名を無認証公開（auth.py BootstrapStatusResponse）

`/api/auth/bootstrap-status`（認証不要）が `bootstrap_username` フィールドで管理者のユーザー名を返していた。
攻撃者がブルートフォースの標的ユーザー名を特定できる状態だった。

修正: `BootstrapStatusResponse` から `bootstrap_username` / `bootstrap_display_name` を削除。
フロントエンドは `has_admin` / `bootstrap_configured` のみを使用しており動作に影響なし。

#### セキュリティヘッダー未設定（main.py）

`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` が未設定だった。

修正: `SecurityHeadersMiddleware` を追加。
`PUBLIC_MODE=True` 時は `Strict-Transport-Security` も付加。
CSP は React の動的スクリプト・スタイルと衝突するリスクがあるため別途検討。

#### CORS: allow_origins=["*"] をPUBLIC_MODE時のみ限定（main.py）

LAN モード（`PUBLIC_MODE=False`）では任意 IP の LAN デバイスが接続するため wildcard を維持。
`PUBLIC_MODE=True`（Cloudflare 公開）では `CLOUDFLARE_TUNNEL_HOSTNAME` のオリジンのみに限定するよう変更。

#### M-4 / S-3: ログアウト後JWT有効（jwt_utils.py + auth.py + models.py）

ログアウト後もトークンが有効期限（8時間）まで使い続けられる状態だった。

修正:
- `RevokedToken` テーブル追加（`jti`, `user_id`, `expires_at`, `revoked_at`）
- JWT に `jti`（UUID）を付与
- `verify_token()` でブラックリスト照合を追加
- `/api/auth/logout` で JTI を `revoked_tokens` に登録
- 起動時に期限切れエントリを自動クリーンアップ
- Redis 不要。PostgreSQL テーブルで実装（小規模用途では性能差ゼロ）

#### A-1: アカウントロックアウト未実装（auth.py）

ブルートフォース試行を無制限に許容していた。

修正:
- `User` モデルに `failed_attempts`, `locked_until` カラム追加
- ログイン失敗5回でアカウントを30分ロック
- ロック中は429を返しロック解除時間を通知
- ログイン成功時に `failed_attempts` をリセット
- admin が `/api/auth/users/{id}/unlock` で手動解除可能

#### A-2: パスワードポリシー未実装（auth.py）

パスワード強度の検証が存在しなかった。

修正: ユーザー作成・パスワード更新時に `_validate_password_strength()` を適用。
要件: 12文字以上、大文字・小文字・数字・記号をそれぞれ1文字以上。

#### S-1: MFA（TOTP）未実装（auth.py + jwt_utils.py）

パスワード1要素のみで多要素認証がなかった。

修正: 標準ライブラリ（hmac/hashlib/struct）のみで TOTP (RFC 6238) を実装（pyotp 不要）。

新規エンドポイント:
- `POST /api/auth/mfa/setup` → TOTPシークレット生成・`otpauth://` URI返却
- `POST /api/auth/mfa/confirm` → コード検証でMFA有効化
- `POST /api/auth/mfa/disable` → コード検証でMFA無効化
- `GET  /api/auth/mfa/status` → MFA有効化状態確認
- `POST /api/auth/mfa/login` → ログイン後のMFAコード検証でフルJWT発行

ログインフロー変更: `totp_enabled=True` のユーザーは credential 検証後に
`mfa_required: true` と短命な `mfa_token`（有効期限5分）を返す。
クライアントは Authenticator アプリのコードを `/api/auth/mfa/login` に送信してフルJWTを取得する。

---

## 未対応（意図的スキップ）

| アラート | 理由 |
|---|---|
| C-1: コマンドインジェクション (cluster, main) | admin 限定エンドポイント。GlobalAuthMiddleware + require_local_or_operator_token で保護済み。IP バリデーション追加は別 PR で検討 |
| H-2: Paramiko AutoAddPolicy | SSH 接続は username+password 必須かつ loopback 限定。既知リスクとして許容 |
| sync.py:224/261/398/422 | validate_package / import_package の返すユーザー向けバリデーションメッセージ。CodeQL 偽陽性 |
| analysis_research.py:332/340 | 正常系の return 文。CodeQL 間接追跡による偽陽性 |
| Electron webSecurity | localfile:// プロトコル依存。変更で動画再生が壊れるリスクあり。別途検討 |

---

### 本番公開後 実攻撃テストで新たに発見・修正済み（2026-04-22 夜）

以下は `https://app.shuttle-scope.com` に対して全攻撃手法を試した結果発見した残課題。
4件すべてコードで修正済み。次回 `git pull` → バックエンド再起動で反映される。

#### [High] OpenAPI/docs が PUBLIC_MODE 時に公開 (`main.py`)

`/docs`, `/redoc`, `/openapi.json` が無認証で 200 を返し、全 API の構造・パラメータ・スキーマを列挙可能だった。

修正: `PUBLIC_MODE=True` の場合は FastAPI に `docs_url=None, redoc_url=None, openapi_url=None` を渡す。

```python
_docs_url    = None if app_settings.PUBLIC_MODE else "/docs"
_redoc_url   = None if app_settings.PUBLIC_MODE else "/redoc"
_openapi_url = None if app_settings.PUBLIC_MODE else "/openapi.json"
app = FastAPI(..., docs_url=_docs_url, redoc_url=_redoc_url, openapi_url=_openapi_url)
```

#### [High] 認証エンドポイントにボディサイズ上限なし (`main.py UploadSizeLimitMiddleware`)

5MB のログインボディが処理された。全体の 100MB 上限のみで auth エンドポイントの制限がなかった。

修正: `/api/auth/` パスに対して 4KB 上限を追加。

```python
_AUTH_BODY_LIMIT = 4 * 1024
limit = _AUTH_BODY_LIMIT if request.url.path.startswith("/api/auth/") else _HTTP_UPLOAD_LIMIT
```

#### [Medium] タイミングオラクルによるユーザー名列挙 (`auth.py`)

既存ユーザー ~770ms・非実在ユーザー ~530ms の ~240ms 差が確認された。
原因: ダミーハッシュ文字列 `"$2b$12$dummyhashfortimingequalizationxxxxxxxxxxxxxxxx"` が
52文字で bcrypt の有効フォーマット（60文字）ではなく、`checkpw` が例外を投げて即リターンしていた。

修正: 起動時に有効な bcrypt ハッシュを1回生成し `_DUMMY_BCRYPT_HASH` として使用。

```python
_DUMMY_BCRYPT_HASH: str = _bcrypt_lib.hashpw(b"_dummy_timing_eq_", _bcrypt_lib.gensalt(rounds=12)).decode()
```

#### [Medium] IP ベースのレート制限なし (`auth.py`)

1分間に 20+ 回の連続ログイン試行がすべて処理された。
ユーザーごとのロックアウトは機能するが、ユーザー名を変えながら別ユーザーへのブルートフォースが無制限に可能だった。

修正: 標準ライブラリ（threading + collections.defaultdict）で IP レート制限を実装（pip 追加インストール不要）。
同一 IP から 60 秒以内に 10 回を超えたら 429 を返す。

```python
_IP_RATE_LOCK = threading.Lock()
_IP_LOGIN_TIMES: dict[str, list[float]] = defaultdict(list)
_IP_RATE_WINDOW = 60   # 秒
_IP_RATE_LIMIT  = 10   # 同一 IP から 60 秒以内
```

---

## 検証手順

```bash
# バックエンド起動
cd shuttlescope
.\backend\.venv\Scripts\python backend/main.py

# 認証なしで API を叩いて 401 が返ることを確認
curl https://app.shuttle-scope.com/api/matches
# → {"detail":"認証が必要です"} 401

# ログインして JWT を取得し、再度叩いて 200 が返ることを確認
curl -X POST https://app.shuttle-scope.com/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"grant_type":"credential","identifier":"admin001","password":"..."}'
# → {"access_token":"..."}

curl https://app.shuttle-scope.com/api/matches \
  -H "Authorization: Bearer <token>"
# → {"success":true,"data":[...]}
```
