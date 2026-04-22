# Security Code Scanning 修正 (2026-04-22)

## 概要

GitHub Code Scanning アラート 41件（critical 4, high 17, medium 20）に対して
以下の修正を実施した。

## 適用済み修正

### [最重要] グローバル認証ミドルウェア — `backend/main.py`

`GlobalAuthMiddleware` を追加。全 `/api/` ルートに Bearer JWT を必須化。
- 除外: `/api/auth/*`（ログインフロー）, `/api/health`, `/api/public/*`
- loopback（Electron ローカル起動）は X-Role フォールバックを維持
- CORS preflight（OPTIONS）も除外
- 実行順: CORS → GlobalAuth → AnalysisCache → PlayerAccess → Upload → ルーター

**適用タイミング**: サーバー再起動時に自動で有効になる（コード変更済み）

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
