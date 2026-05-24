# Phase B-2: 登録フローでチーム必須化 + admin による team_id 変更

## 目的
全ユーザの所属チームを team_id で正規化し、admin のみが team_id を変更できる体制にする。

## 実装内容

### `backend/routers/auth.py`
- `UserCreate` に `team_id: int | None` と `independent: bool` を追加（チーム必須化）
- `UserUpdate` に `team_id: int | None` を追加（admin のみ反映）
- `_resolve_team_for_user_create()` ヘルパ追加
  - `independent=True` → `INDEP-<short_uuid>` を持つ無所属チームを自動生成（個別、衝突時は最大5回リトライ）
  - `team_id` 指定 → 既存チームを返す（存在チェック）
  - どちらもない場合 422
- `create_user`: チーム解決を必須化、`team_name` は team.name から自動セット
- `update_user`: `body.team_id` 変更は admin のみ。Coach/Analyst/Player は 403
- `_user_to_dict`: `team_id`, `team_display_id`, `team_display_name`, `team_is_independent` を返却

### Team CRUD
- `GET /auth/teams` — admin は全チーム、それ以外は自チームのみ（リーク防止）
- `POST /auth/teams` — admin のみ
- `PATCH /auth/teams/{id}` — admin（全チーム） / coach（自チームのみ）

### display_id 設計
- 任意文字列を coach/admin が設定可（"Resonac" / "AAAAA" / 何でも可）
- DB レベルで unique 制約のみ。表示名 `name` は重複可
- 内部参照は常に `id` (int) / `uuid`

## 検証
- 新規ユーザ作成で `team_id` または `independent=true` を指定しないと 422
- coach/analyst/player が `team_id` 変更しようとすると 403
- 無所属ユーザは個別の `INDEP-xxx` 識別子を持つ
