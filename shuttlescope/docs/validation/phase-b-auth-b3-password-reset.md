# Phase B-3: Password change / admin reset (A6)

Date: 2026-04-23

## 方針
POC 期間中は email 配送がないため、ロードマップ通り以下 2 本で代替する:

1. 認証済みユーザーが**自分のパスワードを変更**する self-service エンドポイント。
2. Admin が特定ユーザーの**一時パスワードを発行**する強制 reset エンドポイント。

password reset メール等は B-7 以降 / 運用移行時に再検討。

## 事前確認
- B-4 (連続失敗ログイン対策) は既に実装済みと確認:
  - `_check_ip_rate_limit`: 同一 IP から 60 秒以内に 10 回まで、超過で 429
  - `_check_lockout` + `_on_login_failure`: 5 回失敗で 30 分アカウントロック
  - `/auth/users/{id}/unlock` で admin が手動解除可能

## 変更

### backend/routers/auth.py

#### POST /auth/password (self-service)
- Body: `{ current_password, new_password }`
- 現在のパスワードを `_verify_password` で検証 → 不一致は 401 + `password_change_failed` 監査ログ
- 新パスワードは `_validate_password_strength` で強度検証 (12 文字以上、大小英数記号)
- 成功時: `hashed_credential` 更新 → `revoke_all_refresh_tokens_for_user` で既存 refresh を全失効 → `password_changed` 監査

#### POST /auth/users/{target_id}/reset-password (admin only)
- `_require_admin` で admin 限定
- `_generate_temp_password`: 13 文字のランダム文字列 (大小英数記号を最低 1 文字ずつ保証、`secrets.SystemRandom` でシャッフル)
- 成功時: 一時パスワードを hash 保存、`failed_attempts` と `locked_until` もクリア、全 refresh 失効、`temporary_password` を JSON で返却
- 監査ログ: `password_reset_by_admin` (target_user_id 含む)

## 検証

### 新規テスト (backend/tests/test_password_reset.py, 8 cases, all pass)
- 自身のパスワード変更成功 / 旧パスワード不可 / 新パスワードでログイン可
- current_password 誤りは 401
- new_password 弱いと 422
- 未認証は 401
- パスワード変更で既存 refresh が失効
- admin による一時パスワード発行、旧パスワード不可、一時パスワードでログイン可
- 非 admin (analyst target) は 403
- 存在しないユーザーは 404

### 回帰
- `test_refresh_token.py` + `test_password_reset.py` + `test_auth_bootstrap.py` を同時実行で 20 passed。

## 既知の制約
- 一時パスワードはレスポンス JSON でそのまま返す。admin が口頭/Slack 等の安全なチャネルで本人へ伝達する運用を前提。
- 「次回ログイン時にパスワード変更必須」フラグ (`must_change_password`) は現段階では未実装。運用で回避可能と判断。必要時に B-8 以降で追加予定。
- self-service change 後に refresh を全失効させるため、他端末のセッションは強制ログアウトされる (セキュリティ上の意図した挙動)。

## 今後
- Frontend UI (設定画面にパスワード変更フォーム、admin ユーザー管理画面にリセットボタン) は別タスク。
- B-5: audit log 閲覧ページ。
