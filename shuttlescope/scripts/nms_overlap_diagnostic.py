"""重なり時の人物検出を切り分ける診断ツール。

目的: 「A/B が重なると bbox が融合/逆転/多重表示される」問題が
  (1) 検出器が blob に 1 box しか出していない（=モデル/データの限界）なのか
  (2) 検出器は 2 box 出しているが NMS が潰している/緩すぎて重複が残る（=後処理調整で直る）
  なのかを **生(pre-NMS)検出を可視化して** 判定する。

env 弄りで動画を作り直す前に、まずこれで「素の検出が何を出しているか」を見る。

使用例 (prod):
  set PYTHONUTF8=1
  .venv\\Scripts\\python.exe scripts/nms_overlap_diagnostic.py \
    --video .../fd425688-...mp4 --sec 130 --frames 6 \
    --model backend/models/yolov8n_v2_finetuned_dyn.onnx \
    --out-dir C:/Users/kiyus/Desktop/match33_review/nms_diag

出力:
  - out-dir/f<idx>_raw.png    : pre-NMS の全候補 box（conf>=--conf-floor）を細線で描画
  - out-dir/f<idx>_nms045.png : 標準 NMS(IoU=0.45) 適用後
  - 標準出力 + summary.txt     : フレームごとに raw 候補数 / 各 (conf,iou) 設定での残存数
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import cv2
import numpy as np

# TRT/CUDA DLL を ORT に見せる (bench/native と同じ作法)
try:
    import torch  # noqa
    os.add_dll_directory(os.path.join(os.path.dirname(torch.__file__), "lib"))
except Exception:
    pass
try:
    import tensorrt_libs  # noqa
    os.add_dll_directory(os.path.dirname(tensorrt_libs.__file__))
except Exception:
    pass

import onnxruntime as ort  # noqa: E402


def letterbox_or_resize(frame, size):
    """inference.py に合わせ単純 resize (letterbox なし)。size=(w,h)。"""
    img = cv2.resize(frame, size)
    x = img[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
    return x[None, ...]


def decode_output(out, in_w, in_h):
    """yolov8 1-class 出力を (N,5)=[x1,y1,x2,y2,score] 正規化(0-1) に変換。

    対応 layout:
      (1,5,N)  -> 転置
      (1,N,5)  -> そのまま
    座標は cx,cy,w,h (入力ピクセル系) 前提。score は 5列目 (1-class)。
    """
    a = np.squeeze(out, 0)
    if a.shape[0] in (5, 6) and a.shape[0] < a.shape[1]:
        a = a.T  # (N,5)
    # a: (N, >=5)
    cx, cy, w, h = a[:, 0], a[:, 1], a[:, 2], a[:, 3]
    score = a[:, 4]
    x1 = (cx - w / 2) / in_w
    y1 = (cy - h / 2) / in_h
    x2 = (cx + w / 2) / in_w
    y2 = (cy + h / 2) / in_h
    boxes = np.stack([x1, y1, x2, y2, score], axis=1)
    return boxes


def iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix2 - ix1), max(0.0, iy2 - iy1)
    inter = iw * ih
    ua = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def nms(cands, iou_thr):
    cands = sorted(cands, key=lambda c: -c[4])
    kept = []
    for c in cands:
        if all(iou(c, k) <= iou_thr for k in kept):
            kept.append(c)
    return kept


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--video", required=True)
    p.add_argument("--sec", type=float, required=True, help="重なりが起きる秒")
    p.add_argument("--frames", type=int, default=6, help="--sec から連続 N フレーム")
    p.add_argument("--model", required=True)
    p.add_argument("--in-w", type=int, default=640)
    p.add_argument("--in-h", type=int, default=640)
    p.add_argument("--conf-floor", type=float, default=0.15)
    p.add_argument("--out-dir", required=True)
    args = p.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    providers = [
        ("TensorrtExecutionProvider", {"trt_fp16_enable": True}),
        "CUDAExecutionProvider", "CPUExecutionProvider",
    ]
    so = ort.SessionOptions()
    sess = ort.InferenceSession(args.model, sess_options=so, providers=providers)
    inp = sess.get_inputs()[0].name
    print("model=%s providers=%s input=%s" % (args.model, sess.get_providers(), inp))

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 59.94
    f0 = int(args.sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0)

    summary = []
    for k in range(args.frames):
        ok, frame = cap.read()
        if not ok:
            break
        H, W = frame.shape[:2]
        x = letterbox_or_resize(frame, (args.in_w, args.in_h))
        out = sess.run(None, {inp: x})[0]
        boxes = decode_output(out, args.in_w, args.in_h)
        raw = [b for b in boxes if b[4] >= args.conf_floor]
        # pre-NMS 描画
        rawimg = frame.copy()
        for b in raw:
            x1,y1,x2,y2 = int(b[0]*W),int(b[1]*H),int(b[2]*W),int(b[3]*H)
            cv2.rectangle(rawimg,(x1,y1),(x2,y2),(0,255,255),1)
            cv2.putText(rawimg,"%.2f"%b[4],(x1,max(y1-3,10)),cv2.FONT_HERSHEY_SIMPLEX,0.4,(0,255,255),1)
        cv2.putText(rawimg,"RAW(pre-NMS) cands=%d conf>=%.2f"%(len(raw),args.conf_floor),
                    (10,24),cv2.FONT_HERSHEY_SIMPLEX,0.6,(0,0,255),2)
        cv2.imwrite(os.path.join(args.out_dir,"f%02d_raw.png"%k), rawimg)
        # 標準 NMS 描画
        kept = nms([list(b) for b in raw], 0.45)
        nimg = frame.copy()
        for b in kept:
            x1,y1,x2,y2 = int(b[0]*W),int(b[1]*H),int(b[2]*W),int(b[3]*H)
            cv2.rectangle(nimg,(x1,y1),(x2,y2),(0,255,0),2)
        cv2.putText(nimg,"NMS@0.45 kept=%d"%len(kept),(10,24),
                    cv2.FONT_HERSHEY_SIMPLEX,0.6,(0,200,0),2)
        cv2.imwrite(os.path.join(args.out_dir,"f%02d_nms045.png"%k), nimg)
        # 各設定での残存数
        line = "f%02d frame=%d RAW=%d" % (k, f0+k, len(raw))
        for it in (0.30, 0.45, 0.60, 0.70):
            for cf in (0.25, 0.40):
                c = [b for b in raw if b[4] >= cf]
                line += "  nms%.2f/conf%.2f=%d" % (it, cf, len(nms([list(b) for b in c], it)))
        print(line)
        summary.append(line)

    with open(os.path.join(args.out_dir, "summary.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(summary) + "\n")
    print("DONE out-dir=%s" % args.out_dir)


if __name__ == "__main__":
    sys.exit(main())
