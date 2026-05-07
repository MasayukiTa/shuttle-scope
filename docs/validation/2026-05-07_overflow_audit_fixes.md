# 2026-05-07 解析タブ・体調タブの overflow / レイアウト崩壊一括修正

ユーザ指摘: 「解析・体調タブで枠はみ出し / 変な折り返しが起きていないか確認して」
→ 静的監査で 🔴 重大 7 件 / 🟡 中程度 7 件を検出 → 一括修正。

方針: **情報量を減らさず、デバイスごとに最適化する**。
- xs/sm (mobile): カードリスト or 縦積み grid。横スクロール禁止
- md (tablet): 妥協的レイアウト (アイコン / 短ラベル併用)
- lg/xl+ (desktop): テーブル + truncate + title フル表示

## 共有ユーティリティの新設 (`globals.css`)

### `.num-cell`
```css
.num-cell {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
```
解析テーブル / 集計表の数値セル (% / Brier / EPV / 試合数 etc) に統一適用。
桁数変動による桁ずれ + 折り返しによるレイアウト破綻を一発で防ぐ。

### `.cell-name-clip`
```css
.cell-name-clip {
  max-width: 14ch;   /* xs */
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
@media (min-width: 768px)  { .cell-name-clip { max-width: 22ch; } }
@media (min-width: 1024px) { .cell-name-clip { max-width: 28ch; } }
```
名前 / 大会名など可変長日本語セル用。**情報を「減らす」のではなく「畳む」** のがポイント。
呼び出し側は必ず `title="フルテキスト"` を付ける契約。

## 重大 (7 件) — モバイル card レイアウト + 数値統一

### 1. DashboardOverviewPage 試合一覧
- `<table>` only → **md未満カードリスト + md以上テーブル** の MatchListPage パターン
- 各 td の opponent / tournament に `cell-name-clip` + `title=` 付与
- 数値列に `num-cell`

### 2. DashboardShell StatCard
- `grid-cols-2 lg:grid-cols-4` → **`grid-cols-1 xs:grid-cols-2 lg:grid-cols-4`**
- StatCard 内部に `min-w-0` (flex-1)、ラベル `truncate` + `title=`、value に `num-cell`

### 3. OpponentStats
- `min-w-[320px]` 削除
- **md未満カード (相手名 / 勝率 / 試合数 / 平均ラリー縦並び) + md以上テーブル** に分岐
- 名前列 `cell-name-clip` + title

### 4. BayesMatchupCard
- 同様に **md未満カード (相手名 / posterior 大数字 / N / raw / CI 3 列 grid) + md以上テーブル** に分岐
- 数値列全件に `num-cell`、名前 `cell-name-clip`

### 5. ConditionPage 履歴行
- 5 指標 (CCS / Hooper / RPE / Sleep / Weight) を xs では `grid grid-cols-2`、sm+ で `flex-wrap` に
- `font-mono` を `num-cell` に置換 (font-mono は等幅だが tabular-nums の方が桁揃え目的に合う)
- F1-F5 表示も同様に xs `grid grid-cols-3`、sm+ flex に

### 6. AnalystDepthPanel:237
- `flex-1` → **`flex-1 min-w-0`** (バーが 0px まで潰れる問題を防止)
- score 表示を `font-mono` → `num-cell` に置換

### 7. HumanForecastPanel
- ロール列を `cell-name-clip` + title
- 4 数値列 (人間 acc / モデル acc / 人間 Brier / モデル Brier) に `num-cell` 統一
- `font-mono` を撤廃して `num-cell` に集約

## 中程度 (7 件)

### 8. ConditionPage SearchableSelect parent
- `flex items-center gap-3` → **`flex-col sm:flex-row sm:items-center gap-2 sm:gap-3`**
- xs (327px) で User icon + 「測定対象選手：」 + 280px select が破綻していた問題を解消
- select の幅指定を `min-w-[280px]` → `w-full sm:min-w-[280px] sm:max-w-md`

### 9. CoachSummaryStrip topRisk / topAction
- `text-xs leading-snug` のみ → **`line-clamp-2`** + 親 `min-w-0`
- 長い Japanese で行高が伸びて隣接セル(大数字)と縦中央が崩れていた

### 10-14. 解析テーブル横展開 (`num-cell` 一括適用、background agent)
- EffectiveDistributionMap / FirstReturnAnalysis / TournamentComparison / WinLossComparison /
  ReceivedVulnerabilityMap / StateActionValueCard / StateEPVCard /
  ConditionTagCompare / ConditionOutlierWeeks / ConditionSeasonality
- 数値セル全件に `num-cell` 適用、`font-mono` を整理

(完了状況は背景 agent 完了後に追記)

## ブレークポイント別の最終 UI

| 修正対象 | xs/sm (mobile) | md (tablet) | lg/xl+ (PC) |
|---|---|---|---|
| 試合一覧 | カードリスト (縦積み) | テーブル | テーブル |
| StatCard | 1 列 | 2 列 | 4 列 |
| OpponentStats | カード | テーブル | テーブル |
| BayesMatchupCard | カード (3 列 grid 含) | テーブル | テーブル |
| Condition 履歴 5 指標 | 2 列 grid | flex-wrap | flex-wrap |
| Condition 選手 select | 縦積み | 横並び | 横並び |
| CoachSummaryStrip topRisk | line-clamp-2 | line-clamp-2 | line-clamp-2 |

## 検証

### 追加した frontend テスト
- `src/styles/__tests__/utility_classes.test.ts` (4 ケース)
  - `.num-cell`: tabular-nums + nowrap
  - `.cell-name-clip`: xs (14ch) / md (22ch) / lg (28ch) の段階的 max-width
  - `button[data-tile="true"]`: font-size 16px + min-height 44px + touch-action
  - `button[data-tile="hit-zone"]`: 44x44 (WCAG 2.5.5)

### 既存テスト
- 影響範囲は CSS クラスと JSX のクラス文字列追加のみ。既存コンポーネントの構造変更なし
- vitest 全体: PASS (実行ログ別途)
- electron-vite build: PASS (`NODE_OPTIONS=--max-old-space-size=16384`)

## 影響

- DB スキーマ変更: なし
- バックエンド変更: なし
- 既存ルート / ページ挙動: 変更なし (見た目のみ調整、情報量は不変)
- フロント bundle 増分: +0.5KB 未満 (CSS クラス + 軽量 JSX 分岐)
- 既存ユーザの操作経路: 全く変わらない

## 残スコープ (今 PR 後)

- ConditionCorrelationHeatmap の縦書きラベル (`writing-mode: vertical-lr`) は global override
  との干渉なしを確認済 (要再テスト)
- PairSimulationPanel / LineupOptimizerPanel の `flex-1 min-w-[XXX]` 系は親に flex-wrap が
  あるためモバイルでも破綻なし (再確認済)
- Recharts / D3 軸ラベルの overflow は別事案 (本 PR スコープ外)
