"""A/B badminton tracker eval: ByteTrack baseline vs Hybrid-SORT + court-quadrant
offline stitch, on match33 (fd425688) sec120-150, identical detections.

Detector: yolov8n_v2_finetuned_dyn.onnx (single class, output [1,5,8400]).
Same detections fed to BOTH trackers (fair A/B, DanceTrack methodology).
Metric without GT: unique track_id count per court side after each method, plus
a labeled video (A/B big labels) for qualitative C/D crossover assessment.

Outputs to C:/Users/kiyus/Desktop/badminton_track/.
"""
import os, sys, time
import cv2
import numpy as np

sys.path.insert(0, r"C:/Users/kiyus/Desktop/badminton_track")          # byte_tracker_ss
sys.path.insert(0, r"C:/Users/kiyus/Desktop/wt-badminton/shuttlescope")  # backend.cv

VID = r"C:/Users/kiyus/Desktop/github/shuttle-scope/shuttlescope/videos/fd425688-db28-401e-a57b-7af2d6114a4e.mp4"
MODEL = r"C:/Users/kiyus/Desktop/github/shuttle-scope/shuttlescope/backend/models/yolov8n_v2_finetuned_dyn.onnx"
OUT = r"C:/Users/kiyus/Desktop/badminton_track"
START_S, END_S = 120.0, 150.0
STRIDE = 2          # process every 2nd frame (~30fps) to keep CPU eval tractable
CONF = float(os.environ.get("EVAL_CONF", "0.15"))  # prod MIN_CONF default; 0.30 starves the detector
NMS_IOU = 0.50
INP = 640

os.makedirs(OUT, exist_ok=True)


def log(m):
    print(m, flush=True)


def nms(boxes, scores, iou_thr):
    idx = scores.argsort()[::-1]
    keep = []
    while len(idx):
        i = idx[0]; keep.append(i)
        if len(idx) == 1:
            break
        xx1 = np.maximum(boxes[i,0], boxes[idx[1:],0])
        yy1 = np.maximum(boxes[i,1], boxes[idx[1:],1])
        xx2 = np.minimum(boxes[i,2], boxes[idx[1:],2])
        yy2 = np.minimum(boxes[i,3], boxes[idx[1:],3])
        w = np.maximum(0, xx2-xx1); h = np.maximum(0, yy2-yy1)
        inter = w*h
        a1 = (boxes[i,2]-boxes[i,0])*(boxes[i,3]-boxes[i,1])
        a2 = (boxes[idx[1:],2]-boxes[idx[1:],0])*(boxes[idx[1:],3]-boxes[idx[1:],1])
        iou = inter/(a1+a2-inter+1e-6)
        idx = idx[1:][iou <= iou_thr]
    return keep


def detect(sess, iname, frame):
    """Return Nx5 pixel x1,y1,x2,y2,score."""
    h, w = frame.shape[:2]
    img = cv2.resize(frame, (INP, INP))[:, :, ::-1].transpose(2,0,1).astype(np.float32)/255.0
    raw = sess.run(None, {iname: img[None]})[0][0]   # (5,8400)
    if raw.shape[0] != 5:
        raw = raw.T
    cx, cy, bw, bh, sc = raw[0], raw[1], raw[2], raw[3], raw[4]
    m = sc >= CONF
    if not m.any():
        return np.empty((0,5), np.float32)
    cx, cy, bw, bh, sc = cx[m], cy[m], bw[m], bh[m], sc[m]
    x1 = (cx - bw/2)/INP*w; y1 = (cy - bh/2)/INP*h
    x2 = (cx + bw/2)/INP*w; y2 = (cy + bh/2)/INP*h
    boxes = np.stack([x1,y1,x2,y2], 1)
    keep = nms(boxes, sc, NMS_IOU)
    out = np.concatenate([boxes[keep], sc[keep,None]], 1).astype(np.float32)
    # coarse court-ROI filter on foot_point (bbox bottom-center): drops
    # spectators / line judges so the A/B is about the 4 players. This stands
    # in for the prod court-polygon filter (calibration not loaded in eval).
    if len(out):
        fx = (out[:,0]+out[:,2])/2/w
        fy = out[:,3]/h
        inside = (fx>=0.16)&(fx<=0.84)&(fy>=0.36)&(fy<=0.82)
        out = out[inside]
    return out


def main():
    t0 = time.time()
    sess = __import__("onnxruntime").InferenceSession(MODEL, providers=["CPUExecutionProvider"])
    iname = sess.get_inputs()[0].name
    cap = cv2.VideoCapture(VID)
    fps = cap.get(cv2.CAP_PROP_FPS)
    f_start, f_end = int(START_S*fps), int(END_S*fps)
    log(f"fps={fps:.2f} frames {f_start}..{f_end} stride={STRIDE}")

    # --- pass 1: cache detections (so both trackers see identical boxes) ---
    cap.set(cv2.CAP_PROP_POS_FRAMES, f_start)
    dets_by_idx = {}
    frames_idx = []
    fi = f_start
    while fi <= f_end:
        ok, frame = cap.read()
        if not ok:
            break
        if (fi - f_start) % STRIDE == 0:
            dets_by_idx[fi] = detect(sess, iname, frame)
            frames_idx.append(fi)
            if len(frames_idx) % 100 == 0:
                log(f"  detected {len(frames_idx)} frames ({time.time()-t0:.0f}s)")
        fi += 1
    cap.release()
    H, W = 1080, 1920
    log(f"cached dets for {len(frames_idx)} frames in {time.time()-t0:.0f}s")

    # --- ByteTrack baseline ---
    import byte_tracker_ss as bt
    bytetrk = bt.ByteTracker(track_high_thresh=0.25, track_low_thresh=0.10,
                             new_track_thresh=0.25, track_buffer=120)
    byte_records = []  # frame_idx, track_id, cx_n, cy_n, x1,y1,x2,y2, side
    for k, fi in enumerate(frames_idx):
        d = dets_by_idx[fi]
        ds = [bt.Detection(bbox=tuple(r[:4]), score=float(r[4])) for r in d]
        tracks = bytetrk.update(ds, frame_id=k+1)
        for t in tracks:
            x1,y1,x2,y2 = t.xyxy
            cxn = (x1+x2)/2/W; cyn = (y1+y2)/2/H
            byte_records.append(dict(frame=fi, track_id=int(t.track_id),
                cx=cxn, cy=cyn, x1=x1, y1=y1, x2=x2, y2=y2,
                side="left" if cxn < 0.5 else "right", confidence=float(t.score)))

    # --- Hybrid-SORT ---
    os.environ["SS_PERSON_TRACKER"] = "hybrid"
    from backend.cv.person_tracker import try_build_hybrid_tracker
    from backend.cv.tracklet_stitcher import stitch_tracks
    hyb = try_build_hybrid_tracker(min_hits=2, max_age=60)  # few players, confirm fast
    assert hyb is not None
    hyb_records = []
    for fi in frames_idx:
        d = dets_by_idx[fi]
        out = hyb.update(d if len(d) else np.empty((0,5),np.float32), H, W)
        for row in np.asarray(out).reshape(-1,5):
            x1,y1,x2,y2,tid = row
            cxn=(x1+x2)/2/W; cyn=(y1+y2)/2/H
            hyb_records.append(dict(frame=int(fi), track_id=int(tid),
                cx=cxn, cy=cyn, x1=x1, y1=y1, x2=x2, y2=y2,
                side="left" if cxn<0.5 else "right", confidence=1.0))

    # --- offline court-quadrant stitch on hybrid ---
    hyb_stitched = stitch_tracks(hyb_records, use_swap_guard=False,
                                 use_stitch=True, court_quadrant=True)

    # --- unique-id metrics per side ---
    def per_side(recs):
        out = {"left": set(), "right": set()}
        for r in recs:
            out[r["side"]].add(r["track_id"])
        return {k: len(v) for k, v in out.items()}, len(set(r["track_id"] for r in recs))

    bm, bt_tot = per_side(byte_records)
    hm, hy_tot = per_side(hyb_records)
    sm, st_tot = per_side(hyb_stitched)

    report = []
    report.append(f"=== Badminton match33 sec{int(START_S)}-{int(END_S)} A/B (identical dets) ===")
    report.append(f"frames processed: {len(frames_idx)} (stride {STRIDE}, ~{fps/STRIDE:.0f}fps)")
    report.append(f"detector: yolov8n_v2_finetuned_dyn.onnx conf>={CONF} nms_iou={NMS_IOU}")
    report.append("")
    report.append("UNIQUE TRACK_ID COUNT (lower=more stable; target ~2 per side, ~4 total):")
    report.append(f"  ByteTrack baseline      : left={bm['left']:3d} right={bm['right']:3d}  total={bt_tot}")
    report.append(f"  Hybrid-SORT (no stitch) : left={hm['left']:3d} right={hm['right']:3d}  total={hy_tot}")
    report.append(f"  Hybrid + court-stitch   : left={sm['left']:3d} right={sm['right']:3d}  total={st_tot}")
    rtext = "\n".join(report)
    log("\n"+rtext)
    open(os.path.join(OUT, "metrics.txt"), "w", encoding="utf-8").write(rtext+"\n")

    # --- render labeled video from Hybrid+stitch ---
    render(hyb_stitched, frames_idx, f_start, fps)
    log(f"TOTAL {time.time()-t0:.0f}s DONE")


def render(records, frames_idx, f_start, fps):
    """Assign stable A/B/C/D labels by court quadrant of each track's median pos,
    then draw big labels. A/B = far side (top), C/D = near side (bottom)."""
    by_id = {}
    for r in records:
        by_id.setdefault(r["track_id"], []).append(r)
    # median position per id
    med = {}
    for tid, rs in by_id.items():
        med[tid] = (np.median([x["cx"] for x in rs]), np.median([x["cy"] for x in rs]))
    # top 4 ids by track length, split far/near by the ADAPTIVE median of their
    # own cy (camera-angle robust) rather than a fixed 0.5 net line.
    top = sorted(by_id, key=lambda i: -len(by_id[i]))[:4]
    if len(top) >= 2:
        ysplit = float(np.median([med[i][1] for i in top]))
    else:
        ysplit = 0.5
    far = sorted([i for i in top if med[i][1] < ysplit], key=lambda i: med[i][0])
    near = sorted([i for i in top if med[i][1] >= ysplit], key=lambda i: med[i][0])
    label_map = {}
    for i, tid in enumerate(far[:2]):
        label_map[tid] = "AB"[i]
    for i, tid in enumerate(near[:2]):
        label_map[tid] = "CD"[i]
    colors = {"A": (0,0,255), "B": (0,165,255), "C": (255,0,0), "D": (0,255,0)}

    rec_by_frame = {}
    for r in records:
        rec_by_frame.setdefault(r["frame"], []).append(r)

    cap = cv2.VideoCapture(VID)
    cap.set(cv2.CAP_PROP_POS_FRAMES, f_start)
    out_path = os.path.join(OUT, "hybrid_stitch.mp4")
    vw = cv2.VideoWriter(out_path, cv2.VideoWriter_fourcc(*"mp4v"),
                         fps/STRIDE, (1920,1080))
    fset = set(frames_idx)
    fi = f_start
    last = max(frames_idx)
    while fi <= last:
        ok, frame = cap.read()
        if not ok:
            break
        if fi in fset:
            for r in rec_by_frame.get(fi, []):
                lab = label_map.get(r["track_id"])
                x1,y1,x2,y2 = int(r["x1"]),int(r["y1"]),int(r["x2"]),int(r["y2"])
                if lab:
                    c = colors[lab]
                    cv2.rectangle(frame,(x1,y1),(x2,y2),c,3)
                    cv2.rectangle(frame,(x1,y1-70),(x1+70,y1),c,-1)
                    cv2.putText(frame,lab,(x1+8,y1-12),cv2.FONT_HERSHEY_SIMPLEX,
                                2.2,(255,255,255),5,cv2.LINE_AA)
                else:
                    cv2.rectangle(frame,(x1,y1),(x2,y2),(160,160,160),1)
                    cv2.putText(frame,f"#{r['track_id']}",(x1,y1-6),
                                cv2.FONT_HERSHEY_SIMPLEX,0.6,(160,160,160),2)
            vw.write(frame)
        fi += 1
    vw.release(); cap.release()
    log(f"labeled video -> {out_path}  label_map={label_map}")


if __name__ == "__main__":
    main()
