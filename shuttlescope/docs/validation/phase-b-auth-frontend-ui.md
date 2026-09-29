# Phase B: 認証機能の Frontend UI

Date: 2026-04-23

## 目的
backend で B-1〜B-5 を実装したが、admin/ユーザーから操作できる UI がなかったため
以下 3 画面を追加:

1. ログイン済みユーザが自身のパスワードを変更するカード (SettingsPage アカウントタブ)
2. Admin がユーザのパスワードを強制リセットするボタン + 一時パスワード表示モーダル (UserManagementPage)
3. Admin が監査ログを閲覧できる AuditLogPage (`/audit-logs`)

## 変更

### src/api/client.ts
- `authChangePassword(current, next)` → `POST /auth/password`
- `authAdminResetPassword(userId)` → `POST /auth/users/{id}/reset-password`, returns `{ temporary_password }`
- `authAuditLogs({ action?, user_id?, since?, limit? })` → `GET /auth/audit-logs`
- `AuditLogEntry` 型を export

### src/i18n/ja.json
- `auth.password_change.*`: title/hint/current/new/confirm/submit/submitting/mismatch/success/requirements
- `auth.admin_reset.*`: title/hint/button/submitting/result_title/copy/copied/close
- `auth.audit_log.*`: title/hint/filter_action/filter_user/limit/refresh/column_*/empty

### src/components/auth/PasswordChangeCard.tsx (新規)
- 現在/新規/確認の 3 フィールド、mismatch 早期エラー、成功時にフィールドクリア
- 変更成功後は backend 側で refresh 全失効するため他端末はログアウトされる (ヒントで明示)

### src/pages/UserManagementPage.tsx
- `KeyRound` ボタンを操作列に追加 (admin のみ、編集/削除の隣)
- confirm 後 `authAdminResetPassword` を呼び、成功時は一時パスワードをモーダル表示
- モーダル: 対象 username, モノスペース表示のパスワード, クリップボードコピー, 閉じる

### src/pages/AuditLogPage.tsx (新規)
- admin 限定 (role 確認で早期 return)
- action / user_id / limit で絞り込み、RefreshCw アイコンで再読込
- created_at / action / user (username + #id) / IP / details を表で表示
- 空状態メッセージ、読込中スピナー、エラー表示

### src/App.tsx
- `/audit-logs` ルートを `AdminRoute` 配下で追加

## 検証
- `NODE_OPTIONS=--max-old-space-size=16384 npm run build` 成功 (11.92s)
- 既存テストへの影響なし (backend 変更なし)

## 既知の制約
- UI からの動作確認は手動 (smoke) のみ。ユニットテストは追加していない。
- 監査ログは refetch のみ (WebSocket 連携なし)。自動更新が必要なら後続で。
- 一時パスワード表示モーダルはコピー後に自動で閉じない。誤操作防止のため意図的。
- パスワード変更後、他タブ/端末は次のリクエスト時に 401 → refresh 失敗 → ログインへ (既存の client.ts の 401 フローで処理)。

## 今後
- 監査ログの CSV export
- 監査ログの日時絞り込み UI (現状 since クエリだけ存在)
- `/users` ページへ「監査ログを表示」リンク追加検討
