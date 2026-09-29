# 共有データ化・パフォーマンス最終フェーズ タスク分解

## 日付
2026-04-15

## ゴール
- 振り返りタブ / 研究タブ 初回アクセスを 5s 以内へ
- 予測タブも選手増加に耐える構造に
- 妥協なし: shared-data bundle で冗長データロードを完全排除

## 依存関係とエージェント分割（競合回避）

### Agent A（実行中: af196d9d0c4488aab）— 振り返りタブ shared-data
- 対象ファイル: `backend/analysis/bundle_context.py` (new), `backend/routers/analysis_bundle.py`, 6 review endpoints の impl 抽出
- 成果物: `docs/validation/2026-04-15-bundle-review-sharedata.md`
- ロック: `analysis_bundle.py`, review 系 6 endpoints

### Agent B — 研究タブ shared-data bundle（A 完了待ち）
- 対象: `backend/analysis/research_bundle_context.py` (new), `analysis_bundle.py` に `/api/analysis/bundle/research` 追加
- 対象 endpoints: epv, epv_state_table, state_action_values, counterfactual_shots, counterfactual_v2, bayes_matchup, opponent_policy, doubles_role, shot_influence_v2, hazard_fatigue
- 成果物: `docs/validation/2026-04-15-bundle-research-sharedata.md`
- ロック: `analysis_research.py`, `analysis_bundle.py`（A 完了後）

### Agent C — 予測タブ N+1 / 計算最適化（並列可）
- 対象: `backend/routers/prediction.py`, `backend/analysis/prediction_engine.py`, `backend/analysis/bayes_engine.py`（あれば）
- 狙い: 選手 1000 人想定で相手強度/過去対戦の bulk load 化、同一 player_id 内の再計算キャッシュ
- 成果物: `docs/validation/2026-04-15-prediction-perf.md`
- ロック: prediction 系のみ（A/B と競合しない）

### Agent D — フロント研究タブ bundle consumer 足場（並列可）
- 対象: `src/hooks/useResearchBundle.ts` (new), `src/contexts/ResearchBundleContext.tsx` (new), `DashboardResearchPage.tsx` の Provider 化、10 カードの `useResearchBundleSlice` fallback 導入
- backend 未実装でも FE は optional fetch + fallback で動く設計
- 成果物: `docs/validation/2026-04-15-research-bundle-frontend.md`
- ロック: `src/` のみ

## 実行順序
1. 今すぐ: Agent C, D を並列起動（A と非競合）
2. A 完了通知後: Agent B 起動
3. すべて完了後: parity スクリプトと pytest 再実行、統合 validation MD

## 検証共通要件
- `pytest backend/tests -x -q`: 520 passed + 既存 4 fail 維持
- byte-exact parity 確認スクリプトを各タスクで作成
- Windows build: `NODE_OPTIONS=--max-old-space-size=16384 npm run build`（FE 変更時のみ）
