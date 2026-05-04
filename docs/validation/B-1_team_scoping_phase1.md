# Phase B-1: チーム境界の導入（teams + User.team_id）

## 目的

shuttle-scope のデータがチーム境界を持たず、現状はあらゆるチームの登録試合・選手・解析結果が相互参照可能な状態。
本 Phase は **チーム識別子の導入** と **ユーザのチーム所属の正規化** を行うための基盤整備。

owner_team / 行レベル認可は本フェーズでは導入しない。後続 B-3〜B-6 で段階的に適用する。

## 実装内容

### スキーマ変更（Alembic 0008）

`backend/db/migrations/versions/0008_teams_phase1.py`

- 新規テーブル `teams`
  - `id` (PK, autoincrement)
  - `uuid` (unique, 同期用)
  - `display_id` (unique, nullable) — coach/admin が任意で設定する公開識別子（"Resonac" や "AAAAA" など任意文字列）
  - `name` (表示名、重複可)
  - `short_name`, `notes`
  - `is_independent` (個人ユーザの「無所属」用 true)
  - `created_at`, `updated_at`, `deleted_at`
- `users` テーブルに `team_id` (FK→teams.id, nullable) を追加
- 初期データ: `display_id="TEST-0001"`, `name="testチーム"` を 1 件投入
- 既存ユーザ `username="testtest"` が存在する場合のみ `team_id` を testチーム に設定

### モデル更新

`backend/db/models.py`

- `Team` クラス追加（上記スキーマに対応）
- `User.team_id` 追加（旧 `team_name` は移行期のため併存）

### JWT / AuthCtx 更新

`backend/utils/jwt_utils.py`
- `create_access_token(team_id=...)` パラメータ追加。ペイロードに `team_id` を載せる

`backend/utils/auth.py`
- `AuthCtx` に `team_id` フィールド追加
- JWT ペイロードから `team_id` を取得して `AuthCtx` に格納

`backend/routers/auth.py`
- 全ての `create_access_token` 呼び出しに `team_id=user.team_id` を渡す（password / select / pin / mfa）

## 後方互換性

- `team_name` カラムは保持。フロント・バックエンドの既存コードは team_name で動作継続
- `User.team_id = NULL` のユーザは従来通り（B-2 で必須化、B-3 で行レベル認可導入時に意味を持つ）
- JWT ペイロードに新規キー `team_id` を追加するが、旧トークン（team_id を持たない）も `AuthCtx.team_id = None` として有効

## 検証手順

1. 既存 DB に対して `alembic upgrade head` 実行
2. `teams` テーブル生成 / `users.team_id` 列追加 / TEST-0001 が 1 件存在を確認
3. 既存ログイン（username/password, select, pin）が成功することを確認
4. JWT デコード後 `team_id` が含まれることを確認（testtest ユーザのみ非 NULL）
5. Windows build: `NODE_OPTIONS=--max-old-space-size=16384 npm run build` が通ることを確認

## 影響範囲

- **DB**: `teams` 新規 / `users` カラム追加（既存データに影響なし）
- **API**: 既存エンドポイント挙動は変わらない（JWT ペイロードに team_id が増えるのみ）
- **フロント**: 変更なし（B-2 以降で UI 対応）

## 次フェーズ（B-2）

- 新規ユーザ登録時に team_id 必須化
- 「無所属」選択時に `INDEP-<short_uuid>` の独立チームを自動生成
- admin による既存ユーザの team_id 変更 API
- coach/admin による display_id 編集 API
