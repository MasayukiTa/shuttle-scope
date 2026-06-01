# Offline Tracklet-Stitching Post-Processor (2026-05-29)

バドミントン doubles の per-player 軌道解析向けに、オンライン ByteTrack
(config-F) が吐く断片化 track を **オフラインで 4 つの安定 identity** に集約する
後処理パイプラインを追加した。

## 構成

| 役割 | ファイル |
|------|----------|
| tracklet 収集 (検出 1 回 + 代表 appearance descriptor) | `shuttlescope/scripts/collect_tracklets.py` |
| stitcher 本体 (CPU, numpy のみ) | `shuttlescope/backend/cv/tracklet_stitcher.py` |
| しきい値チューニング / 評価 | `shuttlescope/scripts/eval_stitch.py` |
| stable-ID 着色 debug video 出力 | `shuttlescope/scripts/render_stitched.py` |
| 単体テスト | `shuttlescope/backend/tests/test_tracklet_stitching.py` |

検出は 1 回だけ走らせて `tracklets.json` + `tracklet_embeddings.npz` に保存し、
以降のしきい値チューニングは再検出なしで回せる。

## アルゴリズム

1. **tracklet 収集**: `PersonTracker.update_batch()` (config-F ByteTrack, 384x640
   1-class finetuned model) をクリップに 1 回通す。出力 track ごとに per-frame の
   (frame_idx, centroid, foot, bbox, court_id, conf) を記録。代表 appearance
   descriptor も計算。
2. **背景除去**: court 内 frame 比率が低く、かつ足元座標がほぼ不動の track を
   観客 / 固定誤検出として落とす (`min_court_frac=0.12`, `min_motion_px=14`)。
3. **side / quadrant anchor (HARD 制約)**: 残った player-fragment の代表 court_id
   (多数決) を identity とする。0=FL,1=FR (far side / 上半分), 2=BL,3=BR
   (near side / 下半分)。**net を跨ぐ統合は一切しない**。
4. **同 quadrant 内の貪欲連結**: fragment を開始 frame 順に並べ、既存 chain の末尾に
   対し (a) 時間ギャップ <= `max_gap_frames=90`、(b) 等速外挿予測点との距離 <=
   `max_jump_px + jump_per_gap_px*gap`、(c) appearance cosine >= `app_thresh`
   (descriptor 有効時) を満たす最小 cost の chain へ attach。各 quadrant は最終的に
   1 identity に collapse (hard cap 4)。
5. 出力: `raw_track_id -> stable_id in {0,1,2,3}` (背景は -1)。

### appearance descriptor について (正直な注記)

deploy 済みの OSNet ReID ONNX (`osnet_x0_25_reid.onnx`) は外部 weight ファイル
`*.onnx.data` が欠落しており **本環境ではロード不能**だった。そのため
`backend/cv/reid.py` の HSV 色ヒストグラム + LBP テクスチャ fallback descriptor
(571 次元, L2 正規化, cosine 比較可) を appearance 手掛かりに使用した。色ヒストが
主成分のため、異ユニフォーム相手には効くが同ユニフォーム teammate には弱い。
本実装の選手分離は appearance ではなく **court quadrant (物理的な前後左右)** が
担保するため、この弱さは致命的でない。

## 検証結果 (match 33, sec120-150, doubles, 1798 frames @ 59.94fps)

- **raw tracklets (before): 222** (うち背景 89, player 133)
  - online ByteTrack の per-frame unique track_id 報告値は ~47 だが、offline batch
    収集では分断がより細かく観測され 222 fragment となった。
- **stitch 後の stable identity: 4** (target ~4 達成)
  - far side: identity 0 (FL), 1 (FR)
  - near side: identity 2 (BL), 3 (BR)
- fragments merged per identity: `{0: 40, 1: 31, 2: 29, 3: 33}` (player 計 133 → 4)
- per side: far(0,1) raw 72 fragment → 2 identity / near(2,3) raw 67 fragment → 2 identity
- 背景 (観客・スコアボード等の静止誤検出) 89 track を除外。

`stitched.mp4` を目視確認: 4 選手がクリップ通して A(青)/B(緑)/C(赤)/D(黄) の
1 色 1 文字を保持し、観客には box が付かない。

## 単体テスト

`backend/tests/test_tracklet_stitching.py` — **4 passed**:

- `test_one_player_three_fragments_stitch_to_one` — gap を挟んだ 3 fragment → 1 identity
- `test_two_same_side_players_stay_separate` — 同 far side の FL/FR → 2 identity 維持
- `test_hard_cap_four_and_no_cross_net` — 4 quadrant → identity 4、side 制約遵守
- `test_background_static_filtered` — court 外・不動の静止誤検出を -1 に除外

## 既知の失敗 / 限界

- **quadrant 跨ぎローテーション**: doubles で選手が前後 (FL⇄BL 等) に大きく入れ替わると
  court_id が振動し、同一選手の fragment が 2 identity に分かれる。本実装は多数決
  anchor + 連結で吸収するが完全ではない。「identity = 物理的な court 領域」と解釈する
  のが正確で、「特定の人物」と厳密一致するとは限らない。
- **同ユニフォーム teammate の court-side またぎ swap** は appearance では分離不能
  (色が同一)。net を跨がない限り quadrant で分けられるが、同サイド内の前後入れ替わりは
  上記の通り限界がある。
- OSNet 不在のため appearance は弱い色ヒスト fallback。OSNet weight を正しく deploy
  すれば同サイド分離精度の向上余地あり。

## 出力物

- `C:/Users/kiyus/Desktop/stitch_compare/stitched.mp4` — stable-ID 着色 debug video
- `C:/Users/kiyus/Desktop/stitch_compare/collect/tracklets.json` + `tracklet_embeddings.npz`
- `C:/Users/kiyus/Desktop/stitch_compare/stitch_mapping.json` — raw_track_id -> stable_id
