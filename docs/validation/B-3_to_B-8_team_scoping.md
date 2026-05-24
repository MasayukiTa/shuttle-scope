# Phase B-3 〜 B-8: チーム境界（owner_team / 行レベル認可 / 派生スコープ）

## 概要
試合データに owner_team_id を導入し、派生レコード・キャッシュキーを含めた
全ての認可境界をチーム単位に統一する。

## B-3: Match.owner_team_id + is_public_pool + 既存試合の testチーム移行

### Migration `0009_match_owner_team.py`
- `matches` に列追加: `owner_team_id` (FK), `is_public_pool` (default False), `home_team_id`, `away_team_id`
- 既存全試合を testチーム (display_id="TEST-0001") へ一括 owner 割当
- インデックス: `ix_matches_owner_team_id`, `ix_matches_is_public_pool`
- NOT NULL 化は別マイグレーションで段階適用（SQLite 制約のため）

### Model
- `Match.owner_team_id`, `Match.is_public_pool`, `Match.home_team_id`, `Match.away_team_id`

## B-4: Player.team_id + 既存 player.team 文字列移行

### Migration `0010_player_team_id.py`
- `players` に `team_id` (FK→teams.id, nullable) 追加
- `Player.team` 文字列が `teams.name` と完全一致するもののみ team_id をセット
- 一致しないものは NULL（後で admin が手動紐付け）

### Model
- `Player.team_id` 追加。`Player.team` 文字列は表示用に併存

## B-5: 試合登録 API に owner_team 強制注入

### `backend/utils/auth.py` 追加ヘルパ
- `resolve_owner_team_for_match_create(ctx, requested_team_id, requested_is_public_pool)`
  - **admin**: requested_team_id を尊重、is_public_pool 設定可
  - **coach/analyst**: ctx.team_id を強制注入、is_public_pool 必ず False
  - チーム未所属 → 403

### `backend/routers/matches.py`
- `MatchCreate` / `MatchUpdate` に `owner_team_id`, `is_public_pool`, `home_team_id`, `away_team_id` を追加
- `POST /matches`, `POST /matches/quick-start` — 上記ヘルパで強制
- `PUT /matches/{id}` — owner/public/home/away 系の変更は admin のみ反映、それ以外は破棄
- `DELETE /matches/{id}` — 公開プール試合 / 他チーム所有の削除は admin のみ

## B-6: 行レベル認可を全ルータに適用

### `backend/utils/auth.py` 追加
- `apply_match_team_scope(query, ctx)` — Match クエリに 3 条件 OR フィルタ
  - `owner_team_id == ctx.team_id` OR
  - `is_public_pool == True` OR
  - 自チーム選手登場 (`Player.team_id == ctx.team_id`)
  - admin: 素通し / player: 自身関与のみ
- `user_can_access_match(ctx, m)` — 単体判定版（同条件）
- `require_match_access(match_id, request, db)` — 404 にして存在を隠す
- `can_access_player(ctx, player_id, db)` — 自チーム所属 OR 可視試合に登場

### `backend/routers/matches.py`
- `list_matches`, `list_needs_review_matches` を `apply_match_team_scope` に統一
- `get_match` / `update_match` / `delete_match` / `get_match_rallies` に `user_can_access_match` ガード（404 で隠蔽）

### `backend/main.py`
- `TeamScopeAccessControlMiddleware` 追加
  - coach/analyst のリクエスト全般で `_MATCH_ID_PATTERNS` から match_id を抽出
  - public/owner/team-player いずれにも該当しない場合 404
  - access_log に `access_denied` を記録
  - admin/player はスキップ（player は別ミドルウェアで処理済み、admin は全許可）

これで全 `/api/matches/{id}/*`, `/api/sets/match/{id}`, `/api/sessions/match/{id}`,
`/api/warmup/observations/{id}`, `/api/cv-candidates/...`, `/api/yolo/...`,
`/api/tracknet/...`, `/api/prediction/human_forecast/{id}`,
`/api/analysis/.../{id}`, `/api/reports/.../{id}`, `/api/rallies/match/{id}`,
`/api/strokes/match/{id}` への coach/analyst リクエストがチーム境界で遮断される。

## B-7: 派生レコードに team_id 列を追加

### Migration `0011_derived_team_id.py`
- 対象: `comments`, `expert_labels`, `event_bookmarks`, `human_forecasts`,
  `pre_match_observations`, `prematch_predictions`, `clip_cache`
- 各テーブルに `team_id` (FK→teams.id, nullable) を追加 + インデックス
- 既存行は NULL（移行期は互換）

### Model
- `Comment.team_id`, `EventBookmark.team_id`, `PreMatchObservation.team_id`,
  `HumanForecast.team_id`, `PrematchPrediction.team_id`, `ExpertLabel.team_id`,
  `ClipCache.team_id`

各テーブルへ書き込む router 側は ctx.team_id を必須注入することで、
公開プール試合に対しても各チームが独自のコメント・ラベル・ブックマーク・予測を
持てるようにする。読み取り側は `WHERE team_id = ctx.team_id OR team_id IS NULL`
の形でフィルタする運用とする（NULL は B-1 以前の移行データ扱い）。

## B-8: analysis_cache の team-scoping + ログ／エラー文言レビュー

### `backend/main.py` AnalysisCacheMiddleware
- キャッシュキー params に `team_id`（JWT ペイロードの team_id）を追加
- 同じ player_id でも team_id が異なれば別キャッシュ（他チーム閲覧結果の漏出防止）

### エラー文言
- B-6 の middleware と matches.py で他チーム所有試合は 404「試合が見つかりません」
  に統一済み（403 を返さず存在自体を隠す）
- access_log には match_id / team_id を記録するが、ユーザ向けレスポンスには出さない

## 既知の限界（後続フェーズで対処）
- `Match.owner_team_id` の NOT NULL 化はまだ
- `Player.team` 文字列カラムは表示互換のため残置
- 派生レコードの team_id NULL 行（既存）は B-12 で admin UI から手動紐付け
- coach/analyst の「自分のチームから他チームの解析結果を覗き見」は middleware で
  防御済み。ただし複合 endpoint（複数 match_id を扱う集計系）は要追加レビュー
