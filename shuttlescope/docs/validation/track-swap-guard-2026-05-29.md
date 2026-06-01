# Track Swap Guard 検証 (2026-05-29)

ブランチ: `feat/track-swap-prevention` (worktree `wt-track-swap`)

## 目的
ダブルスで **同一ユニフォームの teammate** (PlayerC/D) が経路交差時に
track_id を取り違える問題を、appearance ではなく **motion/position 連続性**
だけで補正する。Appearance ReID は C/D が見分けられないため無効。

## 実装したアルゴリズム (motion-only, per-frame pairwise)
ByteTrack が ID を付与した **後**、court 割当の **前** に動作する post-association guard。

1. 出力 track_id ごとに直近 K=`SS_PERSON_SWAP_GUARD_HISTORY` (既定 5) frame の
   centroid 履歴を deque で保持。
2. 等速 (constant-velocity) 外挿で各 track の次フレーム予測 centroid を算出
   (直近 2 点の差分を速度とする)。履歴 1 点なら静止予測、空なら判定不能。
3. 各ペア (出力 ID a, b) について、予測同士が
   `SS_PERSON_SWAP_GUARD_MAX_DIST` (既定 250px) 以内 = 交差の可能性がある
   ペアのみ評価。
   - `err_cur  = d(obs_a, pred_a) + d(obs_b, pred_b)`
   - `err_swap = d(obs_a, pred_b) + d(obs_b, pred_a)`
   - `err_swap < err_cur * (1 - margin)` なら ByteTrack の取り違えと判断し、
     2 つの出力 ID を alias map で相互に張り替える (履歴も同時に swap)。
4. alias は永続化。以後のフレームでも raw→出力 ID 変換が安定して効く。
   `reset_for_new_set()` で alias / 履歴をクリア (set 境界で人物配置が変わるため)。

ByteTrack 自体の Kalman 状態には手を加えず、出力段で alias 補正する非破壊設計。

## 環境変数 (既定 OFF = 挙動完全不変)
| env | 既定 | 意味 |
|-----|------|------|
| `SS_PERSON_SWAP_GUARD` | `0` | `1` で有効化 |
| `SS_PERSON_SWAP_GUARD_MARGIN` | `0.30` | swap 採用の相対マージン |
| `SS_PERSON_SWAP_GUARD_HISTORY` | `5` | 等速予測に使う centroid 数 |
| `SS_PERSON_SWAP_GUARD_MAX_DIST` | `250.0` | 評価対象ペアの最大予測間距離 (px) |

## フック箇所
`shuttlescope/backend/cv/person_tracker.py` `PersonTracker`:
- 新メソッド `_apply_swap_guard()` / `_swap_two()` / `_predict_centroid()` / `_centroid()`
- `update()` (online) と `update_batch()` (batch) の両方で、ByteTracker 出力から
  `raw_tracks` を組んだ直後・`adjudicate_court()` の直前に呼ぶ (一貫適用)。
- 新規 state: `_swap_guard_enabled` / `_swap_guard_margin` /
  `_swap_centroid_hist` / `_swap_alias`。
- `reset_for_new_set()` で swap 状態をクリア。

## ユニットテスト
`shuttlescope/backend/tests/test_person_tracker.py::TestSwapGuard` (5 件)
- `test_off_by_default_is_noop`
- `test_no_swap_when_paths_separate`
- `test_crossover_swap_is_corrected` ← 合成交差軌跡、取り違えを補正
- `test_alias_persists_across_frames`
- `test_reset_clears_swap_state`

結果: **40 passed** (ファイル全体、GPU/モデル不要の純ロジック)。

## prod smoke 比較動画
`generate_tracking_debug_video.py` で OFF / ON 比較を crossover の多いクリップに対し生成。
- video: `fd425688-db28-401e-a57b-7af2d6114a4e.mp4` の 120s から 30s
- match-type doubles / match-id 33 / 1-class onnx model
- OFF: `C:/Users/kiyus/Desktop/swapguard_compare/swapguard_OFF.mp4`
- ON : `C:/Users/kiyus/Desktop/swapguard_compare/swapguard_ON.mp4`

## 限界 (motion-only では救えないケース)
- **同速度・同方向で長時間並走**してから交差: 予測が両者ほぼ同一になり swap 判定が
  曖昧 (margin で発火を抑制するため、誤補正より未補正側に倒す設計)。
- **完全 occlusion 中の交差**: 検出欠落 → 予測履歴が途切れ、復帰時に判定不能。
  これは ReID Tier 3 (court 単位) の担当領域。
- **3 人以上が同時に同一点へ集まる**密集: pairwise per-frame では大域最適でなく
  局所判定のため取り違えが残りうる (v1 では多フレーム大域最適化は非対応)。
- 急加速・急停止で等速モデルが外れるフレームでは一時的に予測誤差が増えるが、
  margin と max-dist ガードで誤補正は抑制。
