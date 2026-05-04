# 打者チームツールチップ / TrackNet DB保存 / YOLO ROI拡張マージン
**Date:** 2026-04-11

---

## 1. 打者ボタン・ストロークに所属チームのホバー表示

### 変更ファイル
- `src/pages/AnnotatorPage.tsx`
- `src/components/annotation/StrokeHistory.tsx`

### 実装内容

**打者切り替えボタン（AnnotatorPage）**

player_a / player_b の各ボタンに `title` 属性を追加。

```tsx
title={match?.player_a?.team ? `所属: ${match.player_a.team}` : match?.player_a?.name ?? 'A'}
```

チーム名未設定の場合は選手名をフォールバックとして表示。

**ストロークヒストリー（StrokeHistory）**

`playerATeam?: string` / `playerBTeam?: string` props を追加。  
各ストロークの打者名 span に `title={teamTooltip}` を追加。

```tsx
function resolveTeamTooltip(player: string): string | undefined {
  if (player === 'player_a' || player === 'partner_a') return playerATeam ? `所属: ${playerATeam}` : undefined
  if (player === 'player_b' || player === 'partner_b') return playerBTeam ? `所属: ${playerBTeam}` : undefined
  return undefined
}
// ...
<span title={teamTooltip}>{num}{playerLabel}:{shotLabel}...</span>
```

AnnotatorPage 側の `<StrokeHistory>` 呼び出しに `playerATeam={match?.player_a?.team}` / `playerBTeam={match?.player_b?.team}` を追加。

---

## 2. TrackNet解析結果のDB保存

### 変更ファイル
- `backend/routers/video_import.py`

### 実装内容

これまで TrackNet のシャトル軌跡は `job["_tracknet_track"]`（メモリのみ）に保持され、DBに保存されていなかった。YOLO と同様に `MatchCVArtifact` に保存する `_save_tracknet_artifact()` 関数を追加。

| フィールド | 値 |
|---|---|
| `artifact_type` | `"tracknet_track"` |
| `data` | track points の JSON 配列 |
| `summary` | `{"point_count": N, "backend": "..."}` |
| `frame_count` | track point 数 |
| `backend_used` | 使用バックエンド名 |

再実行時は既存レコードを上書き（upsert）。

---

## 3. YOLO ROIフィルタの拡張マージン

### 変更ファイル
- `backend/routers/video_import.py`

### 実装内容

コートキャリブレーションの `roi_polygon`（4コーナー厳密ポリゴン）をそのまま使うと、ベースライン際・奥側サービスライン付近のプレイヤーが除外される問題があった。

`_expand_polygon()` を追加し、centroid から **8%外側** に拡張したポリゴンをフィルタに使用する。

```python
_ROI_EXPAND_MARGIN = 0.08  # コードで調整可能

def _expand_polygon(polygon, margin=_ROI_EXPAND_MARGIN):
    cx = sum(p[0] for p in polygon) / len(polygon)
    cy = sum(p[1] for p in polygon) / len(polygon)
    return [[cx + (px-cx)*(1+margin), cy + (py-cy)*(1+margin)] for px, py in polygon]
```

- キャリブレーション未設定の場合はフィルタ自体が無効（全検出を使用）
- TrackNet は ROI フィルタなし（シャトルはコート外にも飛ぶため）

---

## 4. サーブ自動切り替えの確認（実装済み）

ユーザーからの質問: 「初期サーブ登録後、以降はルールに従い自動でサーバーが選ばれるか？」

→ `annotationStore.ts:360` に `currentPlayer: winner` が実装済み。ラリー確定時に勝者を次のサーバーとして自動セット（ラリーポイント制）。手動切り替えも常に可能。

---

## 残り（人間検証が必要）

- 実映像で奥側プレイヤーが 8% マージンで拾えるか確認（調整が必要なら `_ROI_EXPAND_MARGIN` を変更）
- TrackNet 保存データが CV アシスト候補パイプラインで正しく参照されるか確認（MatchCVArtifact の artifact_type が `"tracknet_track"` であることを確認）
