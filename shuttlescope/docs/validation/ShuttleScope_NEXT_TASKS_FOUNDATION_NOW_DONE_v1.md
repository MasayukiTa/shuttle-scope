# ShuttleScope Next Tasks Foundation Now — 実装完了 v1

## 日付: 2026-04-10

## 実装対象

`ShuttleScope_NEXT_TASKS_FOUNDATION_NOW_v1.md` に従って
Workstream A（メタデータレジストリ統合）と Workstream B（AnnotatorPage 分解）を実装した。

---

## Workstream A: Analysis Metadata Registry（完了）

### 新規ファイル

**`backend/analysis/analysis_registry.py`**（新規）

- `RegistryEntry` TypedDict を定義（全フィールド型付き）
- `_RAW` リストで全 30 analysis_type を網羅
- `TIER_MIN_SAMPLES` / `TIER_OUTPUT_POLICY` も一元管理
- `ANALYSIS_REGISTRY` dict を起動時に構築
- 公開 API:
  - `get_analysis_meta(analysis_type) → RegistryEntry`
  - `get_tier(analysis_type) → str`
  - `list_registry_entries() → list[RegistryEntry]`

### 解決した不整合

旧来の分散状態（3ファイル間の不整合）を統一した:

| 問題 | 旧状態 | 新状態 |
|------|--------|--------|
| epv_state, state_action, hazard_fatigue, counterfactual_v2, bayes_matchup, opponent_policy, doubles_role | EVIDENCE_META にあるが ANALYSIS_TIERS にない | ANALYSIS_REGISTRY で tier=research として統一 |
| shot_quality, movement, bayesian_rt | ANALYSIS_TIERS にあるが EVIDENCE_META にない | ANALYSIS_REGISTRY で evidence_level 含む全フィールド定義 |
| `_infer_tier()` ローカル関数 | analysis_spine.py に独自実装 | 削除、registry に委譲 |

### 追加フィールド

既存フィールドに加え、新たに `page` / `section` を追加:
- `page`: "dashboard" | "analyst"
- `section`: "overview" | "advanced" | "research" | "spine_rs1" 〜 "spine_rs5"

### 更新ファイル

**`backend/analysis/response_meta.py`**
- `analysis_tiers.py` と `analysis_meta.py` からのインポートを削除
- `analysis_registry.get_analysis_meta()` / `TIER_OUTPUT_POLICY` に委譲
- 出力 dict のフィールドは変更なし（後方互換）

**`backend/routers/analysis_spine.py`**
- `from backend.analysis.analysis_registry import list_registry_entries` を追加
- `/analysis/meta/evidence` エンドポイントを registry ベースに更新
  - `EVIDENCE_META` イテレーションを廃止
  - レスポンスに `page`, `section` フィールドを追加
  - `_infer_tier()` ローカル関数を削除

### 既存ファイル（変更なし）

- `analysis_meta.py` — EVIDENCE_META は後方互換のため維持
- `analysis_tiers.py` — ANALYSIS_TIERS は後方互換のため維持
- `promotion_rules.py` — 変更なし

### 検証

```
python -c "
from backend.analysis.analysis_registry import get_analysis_meta, get_tier, list_registry_entries
print('entries:', len(list_registry_entries()))  # 30
print('epv_state tier:', get_tier('epv_state'))  # research
print('shot_quality tier:', get_tier('shot_quality'))  # advanced
print('unknown tier:', get_tier('unknown'))  # research (fallback)
"
```

```
python -c "
from backend.analysis.response_meta import build_response_meta
m = build_response_meta('epv_state', 100)
assert m['tier'] == 'research'
assert m['evidence_level'] == 'directional'
assert m['min_recommended_sample'] == 50
assert m['conclusion_allowed'] == False  # research tier
"
```

- `npm run build` ✓
- `npx vitest run` ✓（34 tests passed）

---

## Workstream B: AnnotatorPage 分解（Step 1 + Step 2 完了）

### AnnotatorPage サイズ

| フェーズ | 行数 |
|----------|------|
| 分解前 | 3307 行 |
| Step 1 後 | 3177 行 |
| Step 2 後 | **3114 行** |
| 削減 | **-193 行** |

### Step 1: useCVJobs + AnnotatorVideoPane（完了）

#### 新規ファイル

**`src/hooks/annotator/useCVJobs.ts`**（新規）

抽出した関心:
- TrackNet バッチジョブ状態（jobId, job, shuttleFrames, shuttleOverlayVisible, tracknetArtifactAt）
- YOLO バッチジョブ状態（jobId, job, yoloFrames, yoloOverlayVisible, yoloArtifactMeta）
- ポーリングエフェクト（TrackNet × 1、YOLO × 1）
- ハンドラ（handleTracknetBatch, handleYoloBatch）
- 動画時間追跡エフェクト（timeupdate → currentVideoSec）
- videoContainerRef（オーバーレイ座標計算用）

型定義:
- `TracknetJob` export 型
- `YoloJob` export 型
- `CVJobsResult` export インターフェース
- `Options` インターフェース（matchId, match, tracknetEnabled, yoloEnabled, tracknetBackend, queryClient, t, videoRef）

**`src/components/annotator/AnnotatorVideoPane.tsx`**（新規）

抽出した関心:
- `<div ref={videoContainerRef}>` + VideoPlayer
- PlayerPositionOverlay（YOLO フレームが存在する場合）
- ShuttleTrackOverlay（シャトルフレームが存在する場合）

Props: videoRef, videoContainerRef, src, playbackRate, onPlaybackRateChange, yoloFrames, yoloOverlayVisible, currentVideoSec, shuttleFrames, shuttleOverlayVisible

#### AnnotatorPage の変更

- インポート削除: `PlayerPositionOverlay`, `ShuttleTrackOverlay`, `ShuttleFrame`
- インポート追加: `useCVJobs`, `AnnotatorVideoPane`
- CV 関連 state 宣言（13 個）を削除
- handleTracknetBatch, handleYoloBatch, 3 エフェクトを削除
- JSX: `<div ref={videoContainerRef}>` セクションを `<AnnotatorVideoPane>` に置換
- `useCVJobs({ ... })` 呼び出しを追加（match 解決後、match 宣言直下）

### Step 2: useSessionSharing（完了）

#### 新規ファイル

**`src/hooks/annotator/useSessionSharing.ts`**（新規）

抽出した関心:
- セッション状態（activeSession, showSessionModal, showDeviceManager）
- handleCreateOrGetSession（POST /sessions）
- トンネル query（tunnelStatus, refetchTunnel）+ mutation（tunnelToggle）
- tunnelBase 計算値 + rebaseUrl ヘルパー
- remoteStream / remoteStreamVideoRef + srcObject エフェクト
- localCamStream / localCamVideoRef + srcObject エフェクト
- remoteHealth 状態

型定義:
- `ActiveSession` インターフェース
- `RemoteHealth` インターフェース
- `TunnelData` インターフェース
- `SessionSharingResult` export インターフェース

Options: matchId, tunnelProvider

#### AnnotatorPage の変更

- インポート追加: `useSessionSharing`
- 削除した state: `remoteStream`, `remoteStreamVideoRef`, `remoteStreamVideoRef.current.srcObject` エフェクト, `localCamStream`, `localCamVideoRef`, `localCamVideoRef.current.srcObject` エフェクト, `remoteHealth`（+ setters）
- 削除した state: `activeSession`, `showSessionModal`, `showDeviceManager`
- 削除したクエリ: `tunnelStatus` useQuery（tunnel-status）
- 削除したミューテーション: `tunnelToggle` useMutation
- 削除した計算値: `tunnelBase`, `rebaseUrl`
- 削除したハンドラ: `handleCreateOrGetSession`
- `useSessionSharing({ matchId, tunnelProvider })` 呼び出しを追加

Note: `videoSourceMode` は AnnotatorPage に残す（match データ・Electron IPC・camera の3箇所から更新されるため）。DeviceManagerPanel callbacks での `setVideoSourceMode('webview')` 呼び出しは AnnotatorPage JSX のインライン callbacks に残す。

### Step 3 判断

`useSetFlow` / `useAutoSave` の抽出は実施しない:
- `handleConfirmRally` は多くの state（scoreA/B, rallyNum, pendingEndType, midGameShown など）と密に結合
- autoSave は store, initialized, autoSaveKey に依存
- これ以上の分解は props/return の数が増えてリスク増大

spec の "stop if behavior-preserving decomposition becomes risky" に従い停止。

### 検証

- `npm run build` ✓（Workstream B Step 1〜2 全て）
- `npx vitest run` ✓（34 tests passed）
- 挙動変更: なし（純粋なリファクタリング）

---

## 変更ファイルサマリー

### 新規ファイル

| ファイル | 内容 |
|----------|------|
| `backend/analysis/analysis_registry.py` | 統合レジストリ（30 analysis_type）|
| `src/hooks/annotator/useCVJobs.ts` | CV ジョブフック |
| `src/hooks/annotator/useSessionSharing.ts` | セッション共有フック |
| `src/components/annotator/AnnotatorVideoPane.tsx` | 動画 + オーバーレイコンポーネント |

### 更新ファイル

| ファイル | 変更内容 |
|----------|----------|
| `backend/analysis/response_meta.py` | registry に委譲 |
| `backend/routers/analysis_spine.py` | registry 経由で /meta/evidence を更新 |
| `src/pages/AnnotatorPage.tsx` | -193 行（CV + セッション関心を分離） |

### 変更なし

- `backend/analysis/analysis_meta.py`
- `backend/analysis/analysis_tiers.py`
- `backend/analysis/promotion_rules.py`
- dashboard / research page コンポーネント
- 既存 annotation フロー

---

## 成功基準達成確認

| 基準 | 状態 |
|------|------|
| メタデータロジックが1箇所に集約 | ✓ analysis_registry.py |
| AnnotatorPage.tsx が小さく読みやすくなった | ✓ -193 行（3307→3114）|
| auth/session 再設計を引き込まなかった | ✓ |
| アノテーション・CV ワークフローが同じ挙動 | ✓ ビルド＋テスト通過 |

Completed: 2026-04-10
