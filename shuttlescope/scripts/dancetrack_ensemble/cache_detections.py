"""Fixed-detector pass for DanceTrack val.

Runs ONE detector (ultralytics YOLOv8x, COCO person class 0) over every val
frame and caches detections to disk so that EVERY tracker consumes identical
boxes -> metric differences = association only, not detection.

Output: eval/dets/<seq>.npy  with rows [frame_id, x1, y1, x2, y2, score]
(frame_id is 1-based, pixel xyxy).
"""
import os, sys, time
import numpy as np

VAL = r"C:\Users\kiyus\Desktop\dancetrack\val"
OUT = r"C:\Users\kiyus\Desktop\dancetrack\eval\dets"
os.makedirs(OUT, exist_ok=True)

IMGSZ = int(os.environ.get("DET_IMGSZ", "1280"))
CONF = float(os.environ.get("DET_CONF", "0.10"))
IOU = float(os.environ.get("DET_IOU", "0.70"))
WEIGHTS = os.environ.get("DET_WEIGHTS", "yolov8x.pt")
DEVICE = os.environ.get("DET_DEVICE", "0")

from ultralytics import YOLO

def main():
    model = YOLO(WEIGHTS)
    seqs = sorted([d for d in os.listdir(VAL) if os.path.isdir(os.path.join(VAL, d))])
    only = os.environ.get("DET_ONLY")
    if only:
        seqs = [s for s in seqs if s in only.split(",")]
    print(f"detector={WEIGHTS} imgsz={IMGSZ} conf={CONF} iou={IOU} device={DEVICE} seqs={len(seqs)}", flush=True)
    for si, s in enumerate(seqs):
        out_path = os.path.join(OUT, s + ".npy")
        if os.path.exists(out_path) and os.environ.get("DET_FORCE") != "1":
            print(f"[{si+1}/{len(seqs)}] {s} cached, skip", flush=True)
            continue
        img1 = os.path.join(VAL, s, "img1")
        frames = sorted([f for f in os.listdir(img1) if f.lower().endswith(".jpg")])
        rows = []
        t0 = time.time()
        BATCH = int(os.environ.get("DET_BATCH", "8"))
        for b0 in range(0, len(frames), BATCH):
            chunk = frames[b0:b0 + BATCH]
            paths = [os.path.join(img1, fn) for fn in chunk]
            results = model.predict(paths, imgsz=IMGSZ, conf=CONF, iou=IOU, classes=[0],
                                    device=DEVICE, verbose=False)
            for j, r in enumerate(results):
                fid = b0 + j + 1  # 1-based
                if r.boxes is not None and len(r.boxes) > 0:
                    xyxy = r.boxes.xyxy.cpu().numpy()
                    conf = r.boxes.conf.cpu().numpy()
                    for bb, c in zip(xyxy, conf):
                        rows.append([fid, float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3]), float(c)])
        arr = np.array(rows, dtype=np.float32) if rows else np.zeros((0, 6), np.float32)
        np.save(out_path, arr)
        dt = time.time() - t0
        print(f"[{si+1}/{len(seqs)}] {s} frames={len(frames)} dets={len(arr)} {dt:.1f}s "
              f"({len(frames)/max(dt,1e-6):.1f}fps)", flush=True)
    print("DONE", flush=True)

if __name__ == "__main__":
    main()
