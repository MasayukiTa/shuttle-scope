# ShuttleScope Analytics Review 実装計画 v1

ベース仕様: `private_docs/ShuttleScope_ANALYTICS_REVIEW_SPEC_v1.md`  
作成日: 2026-04-06

---

## 1. ギャップ分析（既存 vs 必要）

| 機能 | 状況 |
|---|---|
| SetIntervalSummary（タブ選択式） | ✅ 実装済み（5+6+7ルールなし） |
| PreLossPatterns | ✅ 実装済み（反省ページに再利用可） |
| SetComparison | ✅ 実装済み（反省ページに再利用可） |
| 速報5項目カテゴリ（danger/opportunity/pattern/opponent/next_action） | ❌ 未実装 |
| 反省ページ（専用タブ） | ❌ 未実装 |
| 有効配球マップ | ❌ 未実装 |
| 被打球弱点マップ（received_vulnerability） | ❌ 未実装（opponent_vulnerabilityは視点が逆） |
| 得点前パターン（pre_win_patterns） | ❌ 未実装 |
| 継続成長ビュー（成長タブ） | ❌ 未実装 |
| 時系列成長判定（改善/横ばい/悪化/判定保留） | ❌ 未実装 |
| ダブルス相性スコア強化・ペア時系列 | △ 粗い実装のみ |
| **ダブルスペア両選手同時監視** | ❌ 未実装（単一選手選択のみ） |

---

## 2. フェーズ構成

```
Phase 1（最優先）  速報強化 + 反省ページ
Phase 2（次点）    継続成長ビュー + ダブルス相性強化 + ペア両選手監視
Phase 3（その次）  相手タイプ別相性 + ペア別プレースタイル
```

---

## 3. Phase 1: 速報強化 + 反省ページ

### 3.1 新規バックエンドエンドポイント

#### ① `/analysis/pre_win_patterns` — 得点前パターン

`pre_loss_patterns` の `winner == player_role` 版。  
パラメータ・レスポンス構造は `pre_loss_patterns` と完全同一（キー名を `pre_win_1/2/3` に変更）。

```
GET パラメータ: player_id, result?, tournament_level?, date_from?, date_to?
```

---

#### ② `/analysis/effective_distribution_map` — 有効配球マップ

得点ラリーの最終ストローク `land_zone` を集計してゾーン別有効度を返す。

```
GET パラメータ: player_id, result?, tournament_level?, date_from?, date_to?, shot_type?
```

```json
{
  "success": true,
  "data": {
    "zone_effectiveness": {
      "BL": { "win_count": 12, "total_count": 18, "win_rate": 0.667, "effectiveness": 0.45 },
      "BC": { "win_count": 8,  "total_count": 14, "win_rate": 0.571, "effectiveness": 0.31 }
    },
    "top_zones": ["BL", "BR", "NL"]
  },
  "meta": { "sample_size": 120, "confidence": { "level": "medium", "stars": "★★☆", "label": "..." } }
}
```

---

#### ③ `/analysis/received_vulnerability` — 被打球弱点マップ

自分が被打球して失点したラリーにおける被打球ゾーン別失点率。  
`opponent_vulnerability` は相手失点ゾーンで視点が逆なため別エンドポイント。

```
GET パラメータ: player_id, result?, tournament_level?, date_from?, date_to?
```

```json
{
  "success": true,
  "data": {
    "zones": {
      "BL": { "loss_count": 15, "total_count": 22, "loss_rate": 0.682 },
      "BR": { "loss_count": 10, "total_count": 19, "loss_rate": 0.526 }
    },
    "danger_zones": ["BL", "BC"]
  },
  "meta": { "sample_size": 98, "confidence": {...} }
}
```

---

#### ④ `/analysis/flash_advice` — 速報5+6+7ルール

試合中インターバル/セット間で使う短い助言を5項目（高confidence時6/7項目）生成。

```
GET パラメータ: match_id, as_of_set, as_of_rally_num?, player_id
```

5項目を常に生成（カテゴリ順）:
1. `danger` — 直近5ラリー失点率が高いゾーン/ショット
2. `opportunity` — 直近で得点率が高いショット/配球
3. `pattern` — セット全体の失点前シーケンス傾向
4. `opponent` — 相手の直近多用ショット
5. `next_action` — danger + opportunity を統合した1文推奨

confidence >= medium の場合のみ6/7項目追加:
- 6. `trend` — このセットの前半/後半勝率比較
- 7. `fatigue_signal` — 長ラリー後のパフォーマンス低下シグナル

```json
{
  "success": true,
  "data": {
    "items": [
      { "category": "danger",      "title": "直近の失点パターン",
        "body": "クリア後のスマッシュで3/5失点", "priority": 1 },
      { "category": "opportunity", "title": "有効な攻め口",
        "body": "バック奥へのドロップで勝率70%", "priority": 2 },
      { "category": "pattern",     "title": "ラリー傾向",
        "body": "3球目以降で崩れるラリーが多い", "priority": 3 },
      { "category": "opponent",    "title": "相手の多用ショット",
        "body": "直近5ラリーでクロスネットを多用", "priority": 4 },
      { "category": "next_action", "title": "次に試す戦術",
        "body": "相手バック前を優先して配球を試みる", "priority": 5 }
    ],
    "item_count": 5,
    "extended_items_included": false
  },
  "meta": { "sample_size": 28, "confidence": {...} }
}
```

---

### 3.2 新規フロントエンドコンポーネント

| ファイル | 内容 |
|---|---|
| `PreWinPatterns.tsx` | PreLossPatterns構造に準拠、WIN色系で統一 |
| `EffectiveDistributionMap.tsx` | CourtDiagram + 有効ゾーンTop3ハイライト |
| `ReceivedVulnerabilityMap.tsx` | CourtDiagram + 弱点ゾーンTop2ハイライト（player向け=「重点強化ポイント」表現） |
| `FlashAdvicePanel.tsx` | 速報カード群（danger=赤/opportunity=青/next_action=金枠強調） |

---

### 3.3 タブ追加（DashboardPage）

現在の10タブ構成に3タブ追加:

```
概要 | ショット | ラリー | 遷移 | 詳細 | 空間 | 時間 | [速報★] [反省★] [成長★] | 相手 | ダブルス | 詳細解析
```

#### 反省タブ（`review`）

```
試合選択ドロップダウン
├── 被打球弱点マップ（ReceivedVulnerabilityMap）
├── 有効配球マップ（EffectiveDistributionMap）
├── 失点前パターン（PreLossPatterns 再利用）
├── 得点前パターン（PreWinPatterns）
├── セット比較（SetComparison 再利用）
└── 次回アクション（analyst/coach限定、player=伸びしろ変換）
```

#### 速報タブ（`flash`）

```
試合 + セット + 地点指定
├── FlashAdvicePanel（5〜7カード）
└── ロール制御: player = next_action + opportunity のみ表示
```

---

### 3.4 ロール出し分けルール（Phase 1）

| ロール | 表示内容 |
|---|---|
| analyst | 全セクション・「弱点」表現・数値フル |
| coach | analyst同等（速報はnext_action優先） |
| player | 弱点→「伸びしろ」、danger→「重点強化ポイント」、EPV/詳細数値非表示 |

---

## 4. Phase 2: 継続成長ビュー + ダブルス相性強化 + **ペア両選手監視**

### 4.1 ダブルスペア両選手同時監視（新規要件）

#### 背景

現状: ダッシュボードは単一選手選択（`player_id`）のみ。  
課題: 自チームのダブルスペア（選手AとB、両方が `is_target=True`）を同時に監視できない。  
現在のDoublesAnalysisは1選手視点でパートナー情報を表示するだけで、両選手を対等に並べた"チームビュー"が存在しない。

#### 解決方針

ダッシュボードに「ペアモード」を追加する:
- 選手セレクターに「ペアモード切替」トグルを追加
- ペアモード有効時: 選手Aドロップダウン + 選手Bドロップダウン
- ペアモード有効時は `partner_id` を分析コンポーネントに渡す
- 既存の単一選手分析タブはそのままペアのメイン選手（A）で継続表示
- ダブルスタブ（`f_doubles`）+ 成長タブ（`growth`）で両選手の比較ビューを追加表示

#### 新規バックエンドエンドポイント

**`/analysis/pair_combined`** — ペア両選手合算解析

```
GET パラメータ: player_a_id, player_b_id, result?, tournament_level?, date_from?, date_to?
```

両選手が同一試合（ダブルス）に出場したラリーのみを対象に:
- ペア合算勝率
- ゾーン別ペア配球効率（AとBのストロークを合算）
- ペア内ストローク分担比率
- ペア共通の失点前パターン
- ペア共通の有効ショット

```json
{
  "success": true,
  "data": {
    "pair_win_rate": 0.63,
    "pair_match_count": 8,
    "shared_matches": [5, 7, 9, 11, 14, 16, 18, 20],
    "combined_zone_effectiveness": { "BL": 0.61, "NR": 0.57, ... },
    "stroke_share": { "player_a": 0.52, "player_b": 0.48 },
    "common_loss_pattern": "...",
    "common_win_shot": "smash"
  },
  "meta": { "sample_size": 180, "confidence": {...} }
}
```

#### フロントエンド変更

- `DashboardPage.tsx`: ペアモードトグル + 選手B選択UI追加
- `PairCombinedView.tsx`: 両選手合算ビュー（新規コンポーネント）
- DoublesAnalysisタブ: ペアモード時に `PairCombinedView` を優先表示

---

### 4.2 継続成長ビュー

#### 新規バックエンドエンドポイント

**`/analysis/growth_timeline`** — 試合軸×指標の時系列

```
GET パラメータ: player_id, metric(win_rate/avg_rally_length/serve_win_rate), window_size=3
```

```json
{
  "data": {
    "points": [
      { "match_id": 1, "date": "2025-01-15", "value": 0.52, "moving_avg": null },
      { "match_id": 3, "date": "2025-02-20", "value": 0.58, "moving_avg": 0.57 }
    ],
    "trend": "improving",
    "trend_delta": 0.05
  },
  "meta": { "sample_size": 8, "confidence": {...} }
}
```

**`/analysis/growth_judgment`** — 成長判定

```
GET パラメータ: player_id, min_matches=5
```

判定ロジック:
- 試合数 < min_matches → `pending`（判定保留）
- 指標改善数 >= 2 かつ悪化なし → `improving`
- 改善・悪化が拮抗 → `stable`
- 悪化数 >= 2 → `declining`

```json
{
  "data": {
    "judgment": "improving",
    "judgment_ja": "改善傾向",
    "metrics": {
      "win_rate":         { "trend": "improving", "delta": +0.04 },
      "avg_rally_length": { "trend": "stable",    "delta": -0.2  },
      "serve_win_rate":   { "trend": "improving", "delta": +0.06 }
    },
    "match_count": 7,
    "min_matches_required": 5
  }
}
```

**`/analysis/partner_timeline`** — ペア別試合ごとの勝率推移

```
GET パラメータ: player_id, partner_id
```

---

#### 新規フロントエンドコンポーネント

| ファイル | 内容 |
|---|---|
| `GrowthJudgmentCard.tsx` | 成長判定バッジ（改善=青/横ばい=グレー/悪化=赤/保留=黄） |
| `GrowthTimeline.tsx` | Recharts LineChart（試合軸・移動平均線付き） |
| `PartnerTimeline.tsx` | ペア選択後の時系列折れ線 |
| `PairCombinedView.tsx` | ペアモード時の合算ビュー |

#### 成長タブ（`growth`）構成

```
GrowthJudgmentCard（総合判定）
├── GrowthTimeline（win_rate）
├── GrowthTimeline（serve_win_rate）
└── ダブルス選手のみ:
    ├── PartnerTimeline（ペア選択）
    └── PairCombinedView（ペアモード時）
```

---

## 5. Phase 3: 相手タイプ別相性 + ペア別プレースタイル

### 新規バックエンドエンドポイント

- **`/analysis/opponent_type_affinity`** — 相手タイプ（攻撃型/守備型/バランス型）別勝率
- **`/analysis/pair_playstyle`** — ペア別プレースタイル分類（前衛主体/後衛主体/バランス型）

### 新規フロントエンドコンポーネント

- `OpponentTypeAffinity.tsx`
- `PairPlaystyle.tsx`

---

## 6. UI タブ構成（最終形）

```typescript
type TabKey =
  | 'overview' | 'shots' | 'rally' | 'matrix'
  | 'b_detail' | 'c_spatial' | 'd_time'
  | 'flash'    // Phase 1: 速報
  | 'review'   // Phase 1: 反省
  | 'growth'   // Phase 2: 成長
  | 'e_opponent' | 'f_doubles' | 'g_markov'
```

---

## 7. i18n 追加キー（ja.json）

```json
"flash": {
  "title": "速報",
  "set_select": "セット",
  "rally_select": "地点",
  "categories": {
    "danger":      "注意：失点パターン",
    "opportunity": "好機：有効な攻め",
    "pattern":     "傾向：ラリー展開",
    "opponent":    "相手の傾向",
    "next_action": "次に試す戦術"
  },
  "extended_label": "高確信度の追加示唆"
},
"review": {
  "title": "反省",
  "match_select": "試合を選択",
  "vulnerability_map": "被打球弱点マップ",
  "effective_map": "有効配球マップ",
  "pre_win": "得点前パターン",
  "next_action_section": "次回アクション",
  "weakness_label": "重点強化ポイント",
  "growth_hint": "伸びしろ"
},
"growth": {
  "title": "成長",
  "judgment": {
    "improving": "改善傾向",
    "stable":    "横ばい",
    "declining": "悪化傾向",
    "pending":   "判定保留"
  },
  "pending_reason": "試合数が不足しています（最低{min}試合必要）",
  "pair_mode": "ペアモード",
  "pair_select_b": "パートナー選択"
}
```

---

## 8. 既存コンポーネント再利用マップ

| 新機能 | 再利用元 | 変更 |
|---|---|---|
| 反省ページ・失点前 | `PreLossPatterns.tsx` | そのままインポート |
| 反省ページ・セット比較 | `SetComparison.tsx` | そのままインポート |
| 得点前パターン | `PreLossPatterns.tsx` のスタイル・構造 | winner条件反転で新規作成 |
| 有効配球マップ | `CourtDiagram` + 新エンドポイント | 既存コート図に新データを渡す |
| 被打球弱点マップ | `CourtDiagram` + 新エンドポイント | 同上 |
| 速報パネル | `SetIntervalSummary.tsx` のカードレイアウト | 参考にして新規作成 |
| 成長タイムライン | `ScoreProgression.tsx` のLineChart構造 | 参考にして新規作成 |
| ペア合算ビュー | `DoublesAnalysis.tsx` の統計表示 | 参考にして新規作成 |

---

## 9. 実装順序（Phase 1 詳細）

```
1. backend: pre_win_patterns      （最小コスト・pre_lossの転用）
2. backend: effective_distribution_map
3. backend: received_vulnerability
4. frontend: PreWinPatterns.tsx
5. frontend: EffectiveDistributionMap.tsx
6. frontend: ReceivedVulnerabilityMap.tsx
7. frontend: 反省タブ追加（上記3 + PreLossPatterns + SetComparison再利用）
8. backend: flash_advice
9. frontend: FlashAdvicePanel.tsx
10. frontend: 速報タブ追加
```

---

## 10. 注意事項

1. **VulnerabilityMap**: `opponent_vulnerability` は相手視点 → 反省ページ用に `received_vulnerability` を新設
2. **ConfidenceBadge**: 全新規コンポーネントで必須（CLAUDE.md規則）
3. **速報タブとアノテーター連携**: 試合中利用を考慮し、アノテーターの現在試合IDを速報タブのデフォルト値として渡せる設計（URLパラメータまたはContext経由）
4. **ペアモード**: `is_target=True` の選手が複数いる場合のみペアモードが意味を持つ。フィルタ: `sortedPlayers.filter(p => p.is_target)` で対象候補を絞る
5. **player向けロール変換**: RoleGuard + i18n `review.weakness_label` / `review.growth_hint` で対応（ハードコード禁止）
