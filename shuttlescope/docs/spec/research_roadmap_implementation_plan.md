# Research Roadmap Implementation Plan

**Source:** `private_docs/ShuttleScope_RESEARCH_ROADMAP_v1.md`  
**Priority order per §4 of the roadmap**

---

## Implementation Priority Order

| # | Roadmap Category | Implementation Name | Backend Endpoint | Frontend Component | Integration Target |
|---|---|---|---|---|---|
| 1 | 3.3 Opponent-Adaptive Tactical Modeling | 対戦相手別ショット有効性 | `/analysis/opponent_adaptive_shots` | `OpponentAdaptiveShots.tsx` | `e_opponent` tab |
| 2 | 3.4 Doubles Pair Interaction Modeling | ペアシナジースコア | `/analysis/pair_synergy` | `PairSynergyCard.tsx` | `f_doubles` tab |
| 3 | 3.1 Sequential Representation Learning | ラリー3連ショットパターン | `/analysis/rally_sequence_patterns` | `RallySequencePatterns.tsx` | `review` tab |
| 4 | 3.5 Advanced Uncertainty and Calibration | 信頼度キャリブレーション | `/analysis/confidence_calibration` | `ConfidenceCalibration.tsx` | `overview` tab (bottom) |
| 5 | 3.7 Recommendation Ranking | 推奨アドバイスランキング | `/analysis/recommendation_ranking` | `RecommendationRanking.tsx` | `flash` tab |
| 6 | 3.2 Counterfactual Tactical Evaluation | 反事実的ショット比較 | `/analysis/counterfactual_shots` | `CounterfactualShots.tsx` | new `h_research` tab |
| 7 | 3.6 Continuous Spatial Modeling | コート密度ヒートマップ | `/analysis/spatial_density` | `SpatialDensityMap.tsx` | `c_spatial` tab + `h_research` tab |

---

## Detailed Spec Per Feature

### 1. Opponent-Adaptive Shots (`/analysis/opponent_adaptive_shots`)

**Logic:**
- For each opponent the player has faced, compute per-shot-type win rate
- Win = rally winner is the player's side
- Return top opponents (by match count) with their per-shot breakdown
- Highlight shots that outperform global average for that player

**Response shape:**
```json
{
  "data": {
    "global_shot_winrates": {"smash": 0.65, ...},
    "opponents": [
      {
        "opponent_id": 1,
        "opponent_name": "佐藤 花子",
        "match_count": 5,
        "shot_effectiveness": [
          {"shot_type": "smash", "shot_label": "スマッシュ", "count": 20, "win_rate": 0.75, "lift": 0.10},
          ...
        ]
      }
    ]
  },
  "meta": {"sample_size": N, "confidence": {...}}
}
```

**UI:** horizontal bar chart per opponent, color = perfColor(win_rate), lift badge

---

### 2. Pair Synergy (`/analysis/pair_synergy`)

**Logic:**
- Find all matches for each unique pair the player played with
- Compute pair win rate vs player's overall win rate (singles + doubles)
- Synergy score = pair_win_rate - player_avg_win_rate
- Include rally length, stroke sharing, playstyle summary

**Response shape:**
```json
{
  "data": {
    "player_avg_win_rate": 0.55,
    "pairs": [
      {
        "partner_id": 2, "partner_name": "田中",
        "match_count": 8, "win_rate": 0.72,
        "synergy_score": 0.17,
        "avg_rally_length": 9.2,
        "stroke_share": 0.48
      }
    ]
  }
}
```

**UI:** synergy score bar, win rate badge, sorted by synergy_score desc

---

### 3. Rally Sequence Patterns (`/analysis/rally_sequence_patterns`)

**Logic:**
- Extract 3-shot sequences (trigrams) from all rallies
- Track: does this sequence appear in win rallies or loss rallies?
- Win/loss from player's perspective
- Return top 8 win-associated sequences and top 8 loss-associated sequences
- Filter: sequence must appear ≥5 times

**Response shape:**
```json
{
  "data": {
    "win_sequences": [
      {"sequence": ["smash", "defensive", "smash"], "labels": ["スマッシュ","ディフェンス","スマッシュ"],
       "count": 15, "win_rate": 0.87, "win_count": 13}
    ],
    "loss_sequences": [...],
    "total_rallies": 250
  }
}
```

**UI:** two columns (勝ちパターン / 負けパターン), sequence shown as pill chain

---

### 4. Confidence Calibration (`/analysis/confidence_calibration`)

**Logic:**
- Gather sample sizes for all key metrics for this player
- Group into buckets: <30, 30-100, 100-300, 300+
- For each bucket, compute expected confidence level
- Return distribution of how many metrics fall into each tier

**Response shape:**
```json
{
  "data": {
    "distribution": [
      {"tier": "データ不足 (<30)", "count": 3, "ratio": 0.25},
      {"tier": "低信頼 (30-100)", "count": 4, "ratio": 0.33},
      {"tier": "中信頼 (100-300)", "count": 3, "ratio": 0.25},
      {"tier": "高信頼 (300+)", "count": 2, "ratio": 0.17}
    ],
    "total_metrics": 12,
    "overall_quality": "低〜中",
    "min_matches_for_high": 20,
    "current_match_count": 8
  }
}
```

**UI:** donut-style bar showing data quality distribution, guidance text

---

### 5. Recommendation Ranking (`/analysis/recommendation_ranking`)

**Logic:**
- Compute multiple potential advice signals from existing data
- Score each: `priority_score = log(sample_size+1)/log(200) * |effect_size|`
- effect_size = win_rate difference from 0.5 baseline, or growth delta
- Return top 7 ranked items

**Response shape:**
```json
{
  "data": {
    "items": [
      {
        "rank": 1, "category": "shot",
        "title": "スマッシュの継続強化",
        "body": "スマッシュ時の勝率75%（全体比+22%）。優先度高。",
        "priority_score": 0.82,
        "sample_size": 120,
        "confidence_level": "★★★"
      }
    ]
  }
}
```

**UI:** ranked list cards with rank badge, priority bar, confidence stars

---

### 6. Counterfactual Shots (`/analysis/counterfactual_shots`)

**Logic:**
- For each common "context" (previous shot type), compare win rates of different shot responses
- Context = the shot the opponent just hit
- Minimum 5 observations per shot choice per context
- Compute lift = best_choice_win_rate - second_best_win_rate
- Return top 5 highest-lift contexts

**Response shape:**
```json
{
  "data": {
    "comparisons": [
      {
        "context_label": "スマッシュへの返球",
        "prev_shot": "smash",
        "choices": [
          {"shot_type": "drop", "label": "ドロップ", "count": 30, "win_rate": 0.65},
          {"shot_type": "lob", "label": "ロブ", "count": 45, "win_rate": 0.45},
          {"shot_type": "defensive", "label": "ディフェンス", "count": 25, "win_rate": 0.40}
        ],
        "recommended": "drop",
        "lift": 0.20,
        "interpretation": "スマッシュへの返球ではドロップがロブより20%高い勝率"
      }
    ]
  }
}
```

**UI:** accordion per context, horizontal bar chart per choice, recommended badge

---

### 7. Spatial Density (`/analysis/spatial_density`)

**Logic:**
- Map 9 court zones to centroid coordinates (30×60 grid space)
- Count strokes per zone
- Spread each zone's count as gaussian kernel (σ=4 cells)
- Normalize grid to 0–1
- Return as flat 2D array

**Response shape:**
```json
{
  "data": {
    "grid": [[0.0, 0.1, ...], ...],
    "grid_width": 30, "grid_height": 60,
    "zone_counts": {"BL": 45, "BC": 23, ...}
  }
}
```

**UI:** SVG court overlay with color fill per cell using seqBlue scale

---

## Tab Integration

| Tab | Added Components |
|---|---|
| `overview` | `ConfidenceCalibration` (bottom section) |
| `c_spatial` | `SpatialDensityMap` (above/alongside existing heatmap) |
| `review` | `RallySequencePatterns` |
| `flash` | `RecommendationRanking` |
| `e_opponent` | `OpponentAdaptiveShots` |
| `f_doubles` | `PairSynergyCard` |
| `h_research` (new) | `CounterfactualShots` + `SpatialDensityMap` (both types) + roadmap summary |

---

## Color Rules

- Win rate / performance metrics: `perfColor(rate)` (blue=good, red=bad)
- Density / frequency heatmaps: `seqBlue(ratio)` (white→deep blue)
- Single-series bars: `BAR` (#8db0fe)
- Positive/negative semantics: `WIN` / `LOSS`
- Multiple categories: `catColor(i)`
- All components must import from `@/styles/colors`
- No amber / cyan / purple / green custom colors in components

## Player-Safe Rules

- Never show raw win rates or "weakness" framing to `player` role
- Use `伸びしろ` language for growth areas
- Wrap player-restricted content in `<RoleGuard roles={['analyst','coach']}>`
- Counterfactual analysis: analyst/coach only
- Recommendation ranking: coach phrasing for coach, player-safe for player

## Confidence Rules

- Every endpoint must include `meta.sample_size` and `meta.confidence`
- Every component must show `<ConfidenceBadge sampleSize={N} />`
- Empty state: `<NoDataMessage sampleSize={N} minRequired={M} unit="試合" />`
