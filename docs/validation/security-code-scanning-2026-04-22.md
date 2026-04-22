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

---

## 未対応（意図的スキップ）

| アラート | 理由 |
|---|---|
| C-1: コマンドインジェクション (cluster, main) | admin 限定エンドポイント。GlobalAuthMiddleware + require_local_or_operator_token で保護済み。IP バリデーション追加は別 PR で検討 |
| H-2: Paramiko AutoAddPolicy | SSH 接続は username+password 必須かつ loopback 限定。既知リスクとして許容 |
| sync.py:224/261/398/422 | validate_package / import_package の返すユーザー向けバリデーションメッセージ。CodeQL 偽陽性 |
| analysis_research.py:332/340 | 正常系の return 文。CodeQL 間接追跡による偽陽性 |
| Electron webSecurity | localfile:// プロトコル依存。変更で動画再生が壊れるリスクあり。別途検討 |

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
