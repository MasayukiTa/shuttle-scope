# Phase B-1: Refresh Token 設計 (2026-04-23)

## 目的
JWT access token を短命化（現状 8h / admin 24h → 15min）し、別途長命な refresh token で自動再取得することで:
- access token 漏洩時の影響窓を 8h → 15min に短縮
- UX: ユーザが 8h 毎に手動ログインする必要が無くなる（アプリ側で自動継続）
- 失効管理（ログアウト時の revoke）の対象を refresh token に一本化

## 現状把握
- `backend/utils/jwt_utils.py`: HS256、`create_access_token`、`verify_token`、`revoke_token`(jti を `RevokedToken` テーブルへ)。TTL は role 依存 (admin=24h / 他=8h)。
- `backend/routers/auth.py`: `/auth/login` が access token を 1 本返すのみ。refresh 概念は未導入。`/auth/logout` で jti を revoke。
- `src/hooks/useAuth.ts`: `token` 単一値を sessionStorage に保持。期限切れ検知・再発行ロジック無し。401 時はアプリ側で個別対応（ページ毎）。
- `src/api/client.ts`: token を Authorization ヘッダに乗せる。401 ハンドリングは現状グローバルには無い。

## 設計

### Token 構造
| 種類 | TTL | 保存場所 (frontend) | 使い道 |
|------|-----|--------------------|--------|
| access_token  | 15 min  | `sessionStorage` `shuttlescope_token`（既存）  | API 呼び出し時の Authorization |
| refresh_token | 7 day   | `sessionStorage` `shuttlescope_refresh_token`  | access_token 再取得専用 |

Electron 内ローカル HTTP のため HttpOnly Cookie 化は見送り（既存アーキ踏襲）。将来サーバ化時に再検討。

### Backend

#### 新規テーブル `RefreshToken`
| カラム | 型 | 用途 |
|--------|----|------|
| id | INTEGER PK | - |
| jti | TEXT UNIQUE | トークン識別子 |
| user_id | INTEGER FK users.id | 紐付きユーザ |
| token_hash | TEXT | refresh token 本体の SHA256（平文は保存しない） |
| issued_at | DATETIME | 発行時刻 |
| expires_at | DATETIME | 失効時刻 |
| revoked_at | DATETIME NULL | revoke 時刻 |
| replaced_by_jti | TEXT NULL | rotation 先の jti（監査用） |

#### 新規/変更エンドポイント
| メソッド | パス | 変更 |
|----------|------|------|
| POST | `/auth/login`        | レスポンスに `refresh_token` 追加。access を 15 min で発行 |
| POST | `/auth/refresh`      | **新規**。`{refresh_token}` を body で受け、正当性確認後に新 access + 新 refresh を返す（**rotation 方式**） |
| POST | `/auth/logout`       | access + refresh 両方を revoke |

#### セキュリティ要件
- refresh token rotation: 使用するたびに新しい refresh を発行し、使った方は revoke
- **再利用検知（reuse detection）**: revoke 済みの refresh を再提示された場合、同 user の全 refresh chain を revoke（漏洩の可能性）
- token_hash で保存し、平文 DB 化しない
- revoked_at 付きの行は残して監査に使用

### Frontend

#### `src/hooks/useAuth.ts`
- state に `refreshToken` 追加
- `setSession(session)` で `access_token` と `refresh_token` を両方保存
- `clearRole()` で両方クリア
- 新規 `refreshSession()`: `/auth/refresh` を呼び新 session で置換

#### `src/api/client.ts`
- request 実行時に 401 が返ったら:
  1. `refreshSession()` を試行（1 回だけ）
  2. 成功なら元のリクエストを再送
  3. 失敗なら `clearRole()` + ログイン画面へ
- 同時多発 401 対策: refresh in-flight は 1 本に束ねる（mutex）

#### UX
- ページを開いたままでも 15 min 毎に透明に refresh される
- 7 day 経過後は refresh token 失効 → ログイン画面

### DB マイグレーション
- `RefreshToken` モデル追加
- `create_tables()` は起動時に実行される（`backend/main.py`）ので自動作成
- 既存 DB では空テーブルとして作成されるだけ、後方互換性あり

## リスクと緩和
| リスク | 緩和策 |
|--------|-------|
| refresh token 漏洩 | rotation + 再利用検知で検知次第 chain 全体 revoke |
| ネットワーク競合で refresh 並列発火 | client 側で in-flight 共有 promise |
| Electron 強制終了直後の古い refresh の再利用 | sessionStorage 使用で app 終了時に消える。tab 再利用は chain 検知で拒否 |
| 本番 pull 後の既存ユーザ | 既存 access は TTL まで有効、期限切れ後にログイン促され正常フローに復帰。migration 不要 |

## 実装ステップ (A2 以降)
1. **A2 backend**: `RefreshToken` モデル + `/auth/refresh` + login/logout 変更 + ユニットテスト
2. **A3 frontend**: `useAuth` 拡張 + `client.ts` 401 ハンドリング + 手動テスト手順
3. **A2/A3 検証**: `pytest backend/tests` + `npm run build`
4. validation MD 追記

## 受け入れ基準
- login 後 15 min 放置して API 叩くと 401 にならず透明に継続
- logout で refresh token も revoke され、使用済み refresh の再利用で 401
- 既存 access 持ちユーザがログアウトせず期限切れを待っても破綻しない
