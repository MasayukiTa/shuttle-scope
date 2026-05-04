# Phase B-1: Refresh Token Rotation (A2 + A3)

Date: 2026-04-23

## 目的
Access token の TTL を短命化（15 分）しつつ、操作中のユーザーをログアウトさせないため refresh token による自動再発行を導入する。

- 無操作 15 分で access token 失効 → 次の API 呼び出しで 401 → refresh 自動発行失敗時はログアウト。
- 操作中は refresh token（7 日有効）で透過的に再発行される。バドミントン試合 (2h 超) にも耐える。

## バックエンド変更

### jwt_utils.py
- `ACCESS_TOKEN_EXPIRE_MINUTES = 15` / `ADMIN_TOKEN_EXPIRE_MINUTES = 15` に短縮。
- `REFRESH_TOKEN_EXPIRE_DAYS = 7`。
- `create_access_token` に `minutes` kwarg を追加（MFA pre-auth の `hours=5/60` 互換維持）。
- 新規関数:
  - `create_refresh_token(user_id)` → `(raw, jti, expires_at)`。平文 token は一度だけ返し、DB には SHA256 hash を保存。
  - `persist_refresh_token` / `rotate_refresh_token` / `revoke_refresh_token_by_plain` / `revoke_all_refresh_tokens_for_user`。
- rotation + reuse detection: 既に `revoked_at` がある token を再提示した場合、同 user の全 refresh を revoke（漏洩と判断）。

### db/models.py
- `RefreshToken` テーブル追加: `jti` / `user_id` / `token_hash` / `issued_at` / `expires_at` / `revoked_at` / `replaced_by_jti`。

### routers/auth.py
- `LoginResponse` に `refresh_token: Optional[str]` 追加。5 分岐（credential/password/select/pin/mfa_login）すべてで `_issue_refresh_for(user.id)` を同梱。
- `POST /auth/refresh`: `rotate_refresh_token` を呼び、新 access + 新 refresh を返す。
- `POST /auth/logout`: body に `refresh_token` が含まれていれば該当行を revoke。

## フロントエンド変更

### api/client.ts
- `_refreshInflight` モジュール mutex で同時多発 401 の refresh を 1 本化。
- `fetchWithAutoRefresh(input, init)`: 401 を受けたら `/auth/refresh` を呼び、成功時は新 Authorization で再送。
- apiGet/apiPost/apiPut/apiPatch/apiDelete を `fetchWithAutoRefresh` 経由に差し替え。
- `authLogout()` は sessionStorage 内の refresh token を body に含めて送信。

### hooks/useAuth.ts
- sessionStorage key `shuttlescope_refresh_token` を追加。
- `AuthSession.refreshToken` を追加、`setSession` / `clearRole` が refresh token を持続/削除。

### pages/LoginPage.tsx
- `apiLogin` が `data.refresh_token` を拾い、`setSession` に渡す。

## 検証

### 新規テスト (backend/tests/test_refresh_token.py, 5 cases, all pass)
1. login で access_token + refresh_token が返る。
2. `/auth/refresh` で新 access + 新 refresh が払い出される。
3. 無効な refresh は 401。
4. reuse detection: rt1 → rt2 に rotate 後、rt1 を再提示すると rt2 も無効化される。
5. logout 時に refresh が revoke される。

### ビルド
- `npm run build` 成功 (8.59s、`NODE_OPTIONS=--max-old-space-size=16384` 使用)。

### 回帰確認
- 既存の `test_auth_bootstrap` / `test_lan_session_auth` は全て pass。
- フルスイートの pre-existing failure (84 errors / 33 failed) は stash 比較で本変更と無関係であることを確認済み。

## 既知の制約
- sessionStorage に refresh token を保持するため XSS への耐性は HttpOnly cookie より低い。現状は Electron 単体配信のためリスクは限定的。LAN 配信後に Cookie 化を再検討。
- Admin の 15 分 TTL は運用負荷が高い場合、別途設定化を検討。

## 今後の拡張
- B-2: 無操作 30 分での強制ログアウト（renderer 側タイマー）。
- B-3: password reset flow。
- B-4: 連続失敗ログインのレート制限。
