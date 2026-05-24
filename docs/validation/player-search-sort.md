# 選手管理 検索・ソート機能

## 実装日
2026-04-13

## 対象ファイル

| ファイル | 変更内容 |
|---|---|
| `shuttlescope/src/pages/SettingsPage.tsx` | 検索・ソートstate追加、filteredPlayers useMemo、UI更新 |
| `shuttlescope/src/i18n/ja.json` | `player.search_placeholder` / `player.target_only` / `player.sort_asc` / `player.sort_desc` / `player.count_suffix` 追加 |

## 要件

- 複数ユーザが同じサーバの選手リストを参照しながら、端末ごとに**独立したソート**を行える
- サーバサイドはソート前の状態（登録順）を保持する
- 対象規模: 2,000〜3,000件程度

## 設計方針

### クライアントサイド完結

- `GET /api/players` で全件取得（既存）→ サーバは変更なし
- フィルタ・ソートは `useMemo` でクライアント内のみで計算
- 各端末の状態（`playerSearch`, `targetOnly`, `playerSortKey`, `playerSortDir`）は `useState` で管理されるため、他端末に影響しない

### 追加 state

```typescript
type PlayerSortKey = 'name' | 'team' | 'nationality' | 'world_ranking' | 'is_target'

const [playerSearch, setPlayerSearch]     // テキスト検索クエリ
const [targetOnly, setTargetOnly]         // 解析対象のみフィルタ
const [playerSortKey, setPlayerSortKey]   // ソートキー（デフォルト: 'name'）
const [playerSortDir, setPlayerSortDir]   // 'asc' | 'desc'（デフォルト: 'asc'）
```

### filteredPlayers useMemo

1. `targetOnly` チェック
2. `playerSearch` で name / name_en / team / nationality を前方一致でフィルタ
3. `playerSortKey` + `playerSortDir` でソート
   - `name` / `team` / `nationality`: `localeCompare('ja')`
   - `world_ranking`: 数値昇順（null/undefinedは末尾）
   - `is_target`: true優先

### UI

- テキスト検索バー（クリアボタン付き）
- 「解析対象のみ」チェックボックス
- 件数表示（絞り込み中は `X人 / N人` 表示）
- カラムヘッダークリックでソート（名前・チーム・国・Rk・対象）
  - アクティブカラム: ChevronUp / ChevronDown
  - 非アクティブ: ChevronsUpDown（薄表示）
- 空状態: 登録なし / 絞り込み結果なし を個別メッセージで表示

## 動作確認

- [x] TypeScript コンパイルエラーなし（`npm run build` 成功）
- [ ] 選手一覧が検索バーで絞り込まれること
- [ ] 「解析対象のみ」チェックで `is_target=true` のみ表示
- [ ] カラムヘッダークリックでソート切替（昇順→降順→昇順）
- [ ] 同一カラムを2回クリックで昇降反転
- [ ] 別カラムクリックで昇順リセット
- [ ] 件数表示が絞り込み前後で更新される
- [ ] 選手追加・編集・削除後もフィルタ状態が維持される
- [ ] 検索クリアボタンでテキストがリセットされる
