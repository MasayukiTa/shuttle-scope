# Tracker churn tuning — 2026-05-29

## 背景 / 問題
match33 の 30s クリップ (≈900 frame, コート上 4 選手) で person tracker が
**363 個** の unique track_id を生成 (per-court 48/52/58/55)。同一選手に ~90 回
新 ID が振られ identity continuity が崩壊。ReID Tier3 (thresh 0.85, grace 300) は救済できず。

> 注: 初回計測 423 はモデル/コートフィルタ条件差。今回の baseline は
> `yolov8n_v2_finetuned_dyn.onnx` + court_calibration(match33) で **363**。

## 根本原因
standalone ByteTracker (`backend/cv/byte_tracker.py`) の関連付けは pure-IoU。
受理条件は `IoU >= match_thresh_high`。旧既定 `match_thresh_high=0.8` は
**IoU>=0.8** を要求し、badminton の高速移動選手では lost track の Kalman 予測 box と
再検出 box が重ならず再関連付け失敗 → 毎フレーム新 track_id 乱立。
これが churn の主因。

## Sweep 結果 (SS_YOLO_BYTETRACK=0, standalone ByteTracker)
| config | match_high / low / unconf | track_high | new_track | buffer | unique_ids | per-court | note |
|---|---|---|---|---|---|---|---|
| baseline | 0.8 / 0.5 / 0.7 | 0.25 | 0.25 | 120 | **363** | 48/52/58/55 | 重度 churn |
| A | 0.5 / 0.5 / 0.7 | 0.25 | 0.25 | 120 | 85 | 3/6/9/8 | match_high 緩和で激減 |
| B | 0.3 / 0.5 / 0.7 | 0.25 | 0.25 | 120 | 58 | 2/6/5/5 | |
| C | 0.3 / 0.3 / 0.4 | 0.25 | 0.25 | 120 | 58 | 2/6/5/5 | =B (low/unconf 緩和は無効) |
| D | 0.3 / 0.5 / 0.7 | 0.25 | 0.25 | 150 | 57 | 2/6/5/5 | buffer 増は微差 |
| E | 0.2 / 0.5 / 0.7 | 0.25 | 0.25 | 120 | 54 | 3/6/4/4 | |
| **F (採用)** | **0.3 / 0.5 / 0.7** | **0.20** | **0.30** | **150** | **47** | **2/5/5/5** | 最良 |

## 採用 config "F" (新既定値 / env で上書き可)
- `SS_PERSON_BT_MATCH_HIGH=0.3`  (旧 0.8) — 最大効果
- `SS_PERSON_BT_TRACK_HIGH=0.20` (旧 0.25) — 弱め検出も 1st-stage に投入し継続
- `SS_PERSON_BT_NEW_TRACK=0.30`  (旧 0.25) — 弱い偽 box から新 ID を起こしにくく
- `SS_PERSON_BT_TRACK_BUFFER=150`(旧 120)
- match_low=0.5 / match_unconf=0.7 は据置 (旧と同じ)

## Before / After
- unique track_ids: **363 -> 47** (7.7x 削減)
- per-court: 48/52/58/55 -> **2/5/5/5**

## 誤マージ (wrong-merge) リスク
各 occupied quadrant で **>=2** の unique_id が残存 → 2 実選手を 1 に潰す collapse は
発生していない。env で全旧値に即復元可能なため安全側。
さらに攻める場合 (match_high<0.3 等) は同一ユニフォーム teammate の取り違えに注意。

## 付随修正
`backend/yolo/bytetrack.yaml` に `fuse_score: true` 追加
(ultralytics `.track()` path の fuse_score 欠落クラッシュ回避)。

## 再現コマンド (labeled video)
```
cd C:/Users/kiyus/Desktop/wt-churn/shuttlescope
set SS_YOLO_BYTETRACK=0
set DATABASE_URL=sqlite:///C:/Users/kiyus/Desktop/github/shuttle-scope/shuttlescope/backend/db/shuttlescope.db
<venv>/python.exe scripts/generate_tracking_debug_video.py ^
  --video <videos>/fd425688-db28-401e-a57b-7af2d6114a4e.mp4 ^
  --start-sec 120 --duration-sec 30 --match-type doubles --match-id 33 ^
  --model <models>/yolov8n_v2_finetuned_dyn.onnx --reid on --out churn_F.mp4
```
新既定値が config F なので env 上書き不要。旧挙動は
`SS_PERSON_BT_MATCH_HIGH=0.8 SS_PERSON_BT_TRACK_HIGH=0.25 SS_PERSON_BT_NEW_TRACK=0.25 SS_PERSON_BT_TRACK_BUFFER=120` で復元。
