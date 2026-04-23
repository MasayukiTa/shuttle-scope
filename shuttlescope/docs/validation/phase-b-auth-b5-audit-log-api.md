# Phase B-5: 監査ログ閲覧 API (A7, backend only)

Date: 2026-04-23

## 目的
`log_access` による `AccessLog` への書き込みは各所で既に実装済み (login, logout, account_locked, password_changed 等)。admin が本番/検証で内容を確認できる閲覧手段を提供する。

本タスクは**バックエンド API とテストのみ**。Frontend の閲覧ページは別タスク。

## 変更

### backend/routers/auth.py

#### GET /auth/audit-logs (admin only)
- `_require_admin` で admin 限定。403 で analyst/coach/player を拒否。
- Query parameters:
  - `action`: 完全一致 (例: `login_failed`, `password_changed`)
  - `user_id`: 特定ユーザの履歴のみ
  - `since`: ISO8601 datetime 以降。タイムゾーン付きは naive UTC に正規化。不正値は 422。
  - `limit`: 1..500 (default 100)。範囲外は clamp。
- レスポンス: `{ success: true, data: [{ id, user_id, username, action, resource_type, resource_id, details, ip_addr, created_at }] }`
- username は `access_logs.user_id` → `users.username` を 1 回のクエリで解決。
- 並び順は `created_at DESC` (新しい順)。

## 既存監査ログ書き込みポイント (参考)
- login (成功/失敗/MFA/select 各分岐)
- logout
- token_refresh
- account_locked / account_unlocked
- user_created / user_updated / user_deleted
- password_changed / password_change_failed / password_reset_by_admin
- page_access 変更 (PlayerPageAccess 経路)

## 検証

### 新規テスト (backend/tests/test_audit_logs.py, 5 cases, all pass)
- admin で一覧取得、login/login_failed が含まれる
- action フィルタ（login_failed のみ返る）
- 非 admin (analyst) は 403
- 未認証は 401/403
- `limit=99999` でも 200 (内部で 500 に clamp)
- `since=not-a-date` は 422

### 回帰
- `test_refresh_token.py` のフィクスチャも user/access_logs/refresh_tokens/revoked_tokens を
  テスト毎にクリアする形に統一。auth 系 25 tests 全緑 (`test_refresh_token` 5 + `test_password_reset` 8 + `test_audit_logs` 5 + `test_auth_bootstrap` 7)。

## 既知の制約
- 検索は完全一致のみ。部分一致 / OR 検索は現時点で未サポート。
- 大量ログ対策のページングは未実装 (limit のみ)。運用で必要になった時点で cursor-based に拡張。
- `details` は JSON 文字列そのまま返す。frontend 側で `JSON.parse` することを想定。

## 今後
- Frontend: admin 設定画面に監査ログタブを追加し、action / user_id / 期間で絞り込み表示。
- B-6 以降: ログ保持期間 (例: 90 日で自動削除) ジョブ、export (CSV) 機能。
