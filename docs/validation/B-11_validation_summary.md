# Phase B-11: 検証サマリ

## 検証実施結果

### Python 構文チェック ✅
全変更ファイルで `ast.parse` 成功:
- `backend/db/models.py`
- `backend/db/migrations/versions/0008_teams_phase1.py`
- `backend/db/migrations/versions/0009_match_owner_team.py`
- `backend/db/migrations/versions/0010_player_team_id.py`
- `backend/db/migrations/versions/0011_derived_team_id.py`
- `backend/utils/jwt_utils.py`
- `backend/utils/auth.py`
- `backend/routers/auth.py`
- `backend/routers/matches.py`
- `backend/main.py`

### Windows build ⚠ 未実行
- `shuttlescope/node_modules/` が存在しないため build 検証は未実施
- 必要手順: `cd shuttlescope && npm install` 後
  `NODE_OPTIONS=--max-old-space-size=16384 npm run build`

## 残作業（admin による手動オペレーション）

1. 本番環境で alembic upgrade head を実行
   ```
   cd shuttlescope
   .\backend\.venv\Scripts\python -m alembic -c backend/db/alembic.ini upgrade head
   ```
   → 0008〜0011 のマイグレーションが順に適用される

2. 既存ユーザの team_id 紐付け
   - `testtest` ユーザは migration 0008 で testチームへ自動紐付け済み
   - 他ユーザは admin が `/teams` ページで対応するチームを作成し、
     `PUT /auth/users/{id}` で `team_id` を変更（admin のみ可）

3. 既存試合の owner_team_id 振り分け
   - migration 0009 で全既存試合が testチーム所有として登録される
   - admin が UI または API 経由で正しい owner_team_id へ移し替え

4. Player.team_id の補完
   - migration 0010 で `Player.team` 文字列 == `teams.name` のものは自動移行
   - 不一致のものは admin が手動紐付け

## チーム境界の動作確認チェックリスト

- [ ] coach/analyst が他チーム所有試合の URL を直叩きしても 404
- [ ] admin が is_public_pool=true で登録した試合は全チーム閲覧可
- [ ] 公開プール試合に自チーム選手が登場すれば、その試合がチームの
      「解析可能な試合一覧」に出る
- [ ] coach/analyst が POST /matches で owner_team_id を指定しても
      サーバ側で ctx.team_id が強制注入される
- [ ] is_public_pool は admin のみ true 設定可
- [ ] team_id 変更は admin のみ可（PUT /auth/users/{id} で他ロールは 403）
- [ ] AnalysisCacheMiddleware のキャッシュキーに team_id が含まれ、
      他チームのキャッシュ結果が漏れない

## 影響を受けるエンドポイント数

`TeamScopeAccessControlMiddleware` の `_MATCH_ID_PATTERNS` で捕捉される
パスパターンは 14 種類（matches / sets / sessions / warmup / annotation /
cv-candidates / yolo / tracknet / prediction / analysis / reports /
rallies / strokes）。これら全 endpoint への coach/analyst リクエストが
チーム境界で遮断される。

派生レコード（comments, expert_labels, event_bookmarks, human_forecasts,
pre_match_observations, prematch_predictions, clip_cache）は team_id 列を
追加済み。既存行は NULL のため、書き込み router 側で ctx.team_id を
注入する処理は後続フェーズ（B-12）で実装する。

## 既知の限界

- `Match.owner_team_id` の NOT NULL 化は別マイグレーションで段階適用
- 派生レコードの NULL 行は移行期の互換扱い
- 公開プール試合に対する各チームの独自派生（コメント等）の書き込み・
  読み取りロジックは router 側の調整が必要（B-12）
- フロント側の試合登録 dialog で is_public_pool チェックボックスを
  admin 限定で表示する UI 改修は未対応
