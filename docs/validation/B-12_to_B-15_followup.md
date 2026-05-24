# Phase B-12 〜 B-15: フォローアップ実装

## B-12: 派生レコード書き込み時の team_id 注入

### 共通ルール
- 書き込み時: `team_id = ctx.team_id` を注入
- 読み取り時: `team_id IS NULL OR team_id = ctx.team_id`（admin は素通し）
- `team_id IS NULL` は B-1 以前の互換データ扱い（暫定的に全員可視）

### 変更
- `backend/routers/comments.py`
  - `create_comment`: `team_id` 注入
  - `list_comments`: チームスコープフィルタ
- `backend/routers/bookmarks.py`
  - `create_bookmark`: `team_id` 注入
  - `list_bookmarks`: チームスコープフィルタ
- `backend/routers/expert.py`
  - `upsert_label`: 既存行が NULL のとき書き込みチームに確定、新規は ctx.team_id
  - `list_labels`: チームスコープフィルタ
- `backend/routers/human_forecast.py`
  - `create_human_forecast`: `team_id` 注入
  - `get_human_forecasts`: チームスコープフィルタ
- `backend/routers/warmup.py`
  - `save_warmup_observations`: 自チーム既存のみ上書き、新規は team_id 注入
  - `get_warmup_observations`: チームスコープフィルタ
- `backend/routers/prediction.py`
  - `_upsert_prematch_prediction`: `team_id: Optional[int] = None` 引数追加
    - `team_id` 指定時はチームスコープでフィルタして upsert
    - None は admin 互換扱い

### 注記
- 呼び出し元（prediction の upsert を起動する集計ジョブ）は team_id を渡さない
  デフォルト動作のままなので互換性が保たれる。ユーザフェイシングな書き込み
  経路（手動で predict を upsert するルート）が増えたら呼び出し側で team_id を
  渡すよう拡張する

## B-13: 試合登録 UI に is_public_pool チェックボックス（admin 限定）

### `src/pages/MatchListPage.tsx`
- `MatchFormData` に `is_public_pool: boolean` を追加（default false）
- 登録 dialog 内、メモの直下に admin ロール限定で表示するチェックボックス追加
  - "全チーム共有（公開プール: BWF などの公開試合用）"
- 送信時に `is_public_pool=true` のときのみ body に含める（サーバ側で admin
  以外の指定は無視されるが、UI 側でも露出させない）

## B-14: Match.owner_team_id NOT NULL 化マイグレーション 0012

### `backend/db/migrations/versions/0012_match_owner_not_null.py`
- 残存 NULL を testチーム へ再吸収
- それでも NULL が残れば例外で停止（admin に手動振り分け要求）
- SQLite: `batch_alter_table(recreate="always")` で NOT NULL 化
- Postgres: `ALTER COLUMN ... SET NOT NULL`

### `backend/db/models.py`
- `Match.owner_team_id` を `Mapped[int]` (nullable=False) に変更

## B-15: Windows build 検証

### 実施手順
```
cd shuttlescope
npm install
NODE_OPTIONS=--max-old-space-size=16384 npm run build
```

### 結果 ✅
- main: 16.98 kB / 694ms
- preload: 3.11 kB / 33ms
- renderer: 2,862 modules / 17.23s
  - index.html 0.41 kB
  - index-*.css 121.13 kB
  - index-*.js 3,457.02 kB
- すべてエラーなく完了

## 残るのは admin の運用作業

1. **本番 alembic 適用**: 0008〜0012 を順に upgrade head
2. **既存試合の owner 振り分け**: testチームに集約された既存試合を、admin が
   UI または API で正しい owner_team_id へ移し替え（その後で 0012 を適用すれば
   NOT NULL 制約が安全に通る）
3. **Player.team_id の不一致行**: admin UI から手動紐付け
4. **ユーザの team_id 紐付け**: testtest 以外の既存ユーザは admin が個別に設定
