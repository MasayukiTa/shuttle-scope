# Phase B-9 / B-10: フロントエンド対応

## B-9: チーム管理 UI

### 追加ファイル
- `src/pages/TeamManagementPage.tsx`
  - admin: 全チーム閲覧 / 新規作成 / 編集
  - coach: 自チームのみ閲覧 / 編集（display_id, name, short_name, notes）
  - その他ロール: アクセス不可

### `src/api/client.ts` 追加
- `TeamDTO` 型
- `listTeams()` / `createTeam()` / `patchTeam()`

### `src/App.tsx`
- `/teams` ルート追加（権限制御はページ内で実施）

### 既存変更（最小限）
- ユーザ管理ページ等での owner_team 設定 UI は本フェーズ未対応。
  バックエンドが ctx.team_id を強制注入するため、coach/analyst の通常運用
  には影響なし。admin は API 直叩きまたは後続フェーズの UI で対応。

### 公開プール (is_public_pool) チェックボックス
- 試合登録 dialog の `is_public_pool` チェックボックスは admin 限定で表示する
  実装が必要。本フェーズでは API 側の強制注入のみ実装済み。

## B-10: フロントの試合参照を id/uuid 統一

### 現状調査結果
- `MatchListPage`, `AnnotatorPage`, `ExpertLabelerAnnotatePage` 等は既に
  `match.id` を path param / query param として保持しており、試合名による
  暗黙参照は行っていない
- `match.tournament` の利用箇所は表示文字列のみ（条件マッチ・遷移キーには未使用）

### 結論
- フロント側の試合参照は元々 ID ベース。B-10 のスコープは構造的に達成済み。
- バックエンドの `Match.uuid` も既にユニーク化されており、将来的な
  クライアント間同期でもこれを使う前提が整っている。
