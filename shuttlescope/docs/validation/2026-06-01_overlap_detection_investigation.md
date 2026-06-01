# 重なり人物検出の調査と診断ツール (2026-06-01)

## 背景 / 問題
match33 (fd425688) で人物トラッキング動画を確認したところ、A/B が重なる箇所で
**bbox が融合 (2人→1box) / 逆転 (ID swap) / 一人に多数 box** が発生。
「重なっても検出できる」という触れ込みが疑わしい、との指摘。

## 判明事項 (重要)
1. **v2 finetune はリーク評価**:
   - 学習データ `person_finetune/data/data.yaml` の train/val は
     いずれも match33 (fd425688) から抽出したフレーム (`p2_*_f<frame>.png`)。
   - eval_summary の map50 0.70→0.91 等は **同一試合 in-distribution** の数値で、
     別試合への汎化を全く示していない。「学習≒検証」状態。
   - → 正直な評価には **別試合の動画を held-out test** にする必要がある。
2. **「一人に多数 box」は NMS 過補正 (設定ミス)**:
   - 重なり 2 人を残そうと `SS_PERSON_NMS_IOU=0.7` + `SS_PERSON_USE_SOFT_NMS=1` を併用した結果、
     **同一人物の重複 box まで残った**。NMS は IoU>閾値で重複除去するため、閾値 0.7 は緩すぎ。
   - これは結果ではなく後処理の誤設定。標準 (IoU=0.45, Soft-NMS off) に戻すべき。
3. **核心の未解決点**: 2人が完全に重なったとき、検出器が
   - 元々 2 box 出していて NMS が潰しているのか (=後処理調整で直る)
   - blob に 1 box しか出していないのか (=単一クラス box 検出の構造的限界、pose 等が必要)
   が未確認。**これを生(pre-NMS)検出で切り分ける**のが次の一手。

## 追加ツール: scripts/nms_overlap_diagnostic.py
重なりフレームで v2 モデルの **pre-NMS 生検出** を可視化し、上記の切り分けを行う。
- `f<idx>_raw.png`: conf>=floor の全候補 box (細線)
- `f<idx>_nms045.png`: 標準 NMS 後
- `summary.txt`: フレームごと raw 数 / (conf,iou) 各設定の残存数

実行 (prod):
```
set PYTHONUTF8=1
.venv\Scripts\python.exe scripts/nms_overlap_diagnostic.py ^
  --video .../videos/fd425688-...mp4 --sec 130 --frames 6 ^
  --model backend/models/yolov8n_v2_finetuned_dyn.onnx ^
  --out-dir C:/Users/kiyus/Desktop/match33_review/nms_diag
```

判定指針:
- raw に 2 つ別々の高 conf box があり nms045 で 1 つに減る → **NMS 問題**。中庸な IoU と
  same-person dedup を両立する設定 (例: class-agnostic ではなく距離/サイズ制約付き) を検討。
- raw が blob に 1 box → **検出器の限界**。rtmpose_m (prod 済) で keypoint 分離、または
  複数試合・重なり多めデータでの再学習が必要。

## 次アクション (接続復帰後)
1. nms_overlap_diagnostic.py を 1 回流して raw 検出を確認 → 上の分岐を確定。
2. sane 設定 (NMS 既定 / Soft-NMS off / v2 + swap-guard + ReID) で sample 再生成し比較。
3. 別試合動画が用意でき次第、held-out 評価へ。
