# Dashboard Rearchitecture 実装計画 2026-04-09

仕様元: `private_docs/ShuttleScope_DASHBOARD_REARCHITECTURE_AND_TIER_EVIDENCE_v1.md`

## 目標

現在の1ファイル1737行の DashboardPage.tsx を:
- 6サブページのルート構造に分割
- Shell（共有状態）+ サブページ（独立コンテンツ）に再設計
- Tier/Evidence システムの UI プリミティブを追加

## ファイル変更一覧

### 新規作成
| ファイル | 役割 |
|---------|------|
| `src/pages/dashboard/DashboardShell.tsx` | ルート `/dashboard/*` のシェル。選手セレクター・StatCards・フィルター・TopNav を持つ |
| `src/pages/dashboard/DashboardOverviewPage.tsx` | 概要タブ |
| `src/pages/dashboard/DashboardLivePage.tsx` | 速報タブ |
| `src/pages/dashboard/DashboardReviewPage.tsx` | 振り返りタブ |
| `src/pages/dashboard/DashboardGrowthPage.tsx` | 成長タブ |
| `src/pages/dashboard/DashboardAdvancedPage.tsx` | 詳細分析タブ（shots/rally/matrix/spatial/time/opponent/doubles） |
| `src/pages/dashboard/DashboardResearchPage.tsx` | 研究タブ（EPV・反事実・密度マップ等、要注意ラベル付き） |
| `src/components/dashboard/DashboardTopNav.tsx` | 上部6タブナビゲーション |
| `src/components/dashboard/DashboardSectionNav.tsx` | Advanced ページ内セクション切替 |
| `src/components/dashboard/EvidenceBadge.tsx` | Tier/Evidence バッジ |
| `src/components/dashboard/ResearchNotice.tsx` | Research ページ用注意バナー |

### 変更
| ファイル | 変更内容 |
|---------|---------|
| `src/App.tsx` | `/dashboard` → `/dashboard/*` に変更、DashboardShell を import |
| `src/i18n/ja.json` | dashboard サブページ用翻訳キー追加 |

### 削除
| ファイル | タイミング |
|---------|----------|
| `src/pages/DashboardPage.tsx` | 移行完了後に削除（本作業内で実施） |

## コンテンツ配置マッピング

### Overview
- StatCards（全期間統計）
- ConfidenceCalibration
- コートヒートマップ
- 試合一覧テーブル
- スコア推移（ScoreProgression）
- インターバルレポート（IntervalReport）

### Live
- FlashAdvicePanel
- RecommendationRanking
- RallyPickerModal（モーダル）
- SetIntervalSummary（モーダル）

### Review
- ReceivedVulnerabilityMap
- EffectiveDistributionMap
- PreLossPatterns
- PreWinPatterns
- SetComparison
- RallySequencePatterns

### Growth
- GrowthJudgmentCard
- GrowthTimeline（勝率・サーブ勝率）
- PairCombinedView（ペアモード）
- ペアモードトグル

### Advanced（セクション切替）
- **shot**: ShotWinLoss, SetComparison
- **rally**: RallyLengthWinRate, PressurePerformance
- **transition**: TransitionMatrix
- **spatial**: PreLossPatterns, FirstReturnAnalysis, SpatialDensityMap
- **temporal**: TemporalPerformance, PostLongRallyStats
- **opponent**: OpponentStats, OpponentTypeAffinity, OpponentAdaptiveShots, PreMatchObservationAnalytics
- **doubles**: DoublesAnalysis, PairPlaystyle, PairSynergyCard

### Research
- MarkovEPV（EPV分析）
- CounterfactualShots（反事実的ショット）
- 各カードに ResearchNotice バナー付き

## Shell 共有 Props 型

```typescript
interface DashboardSharedProps {
  playerId: number
  filters: AnalysisFilters
  matches: MatchSummary[]
  players: Player[]
  sortedPlayers: Player[]
}
```

## ルート構造

```
App.tsx → MainLayout → Routes
  /dashboard/*       → DashboardShell
    /                → redirect to /dashboard/overview
    /overview        → DashboardOverviewPage
    /live            → DashboardLivePage
    /review          → DashboardReviewPage
    /growth          → DashboardGrowthPage
    /advanced        → DashboardAdvancedPage
    /research        → DashboardResearchPage
```

## Tier 定義

| Tier | 意味 | 適用ページ |
|------|------|----------|
| stable | 日常的なコーチ/アナリスト利用OK | Overview, Live, Review, Growth |
| advanced | 実用的だがアナリスト解釈が必要 | Advanced |
| research | 探索的・要注意ラベル必須 | Research |

## Evidence フィールド

- `tier`: stable / advanced / research
- `evidenceLevel`: exploratory / directional / practical_candidate / practical_adopted
- `sampleSize`: 実サンプル数
- `confidenceLevel`: 信頼度 0-1
- `recommendationAllowed`: boolean

## 実装フェーズ

1. [x] 計画文書作成（本ファイル）
2. [ ] i18n キー追加
3. [ ] EvidenceBadge + ResearchNotice コンポーネント
4. [ ] DashboardTopNav + DashboardSectionNav
5. [ ] DashboardShell.tsx
6. [ ] 6 サブページ実装
7. [ ] App.tsx ルート更新
8. [ ] DashboardPage.tsx 削除
9. [ ] ビルド確認
