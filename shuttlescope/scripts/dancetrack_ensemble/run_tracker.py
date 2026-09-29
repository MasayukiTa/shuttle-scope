"""Unified MOT-format runner for DanceTrack val.

Consumes cached detections (eval/dets/<seq>.npy, rows [frame,x1,y1,x2,y2,score])
so EVERY tracker sees identical boxes. Emits MOT-format results to
eval/trackers/<name>/data/<seq>.txt with lines:
  frame,id,x1,y1,w,h,score,-1,-1,-1

Trackers:
  bytetrack : our standalone ByteTracker (config-F churn-tuned defaults)
  ocsort    : OC-SORT (noahcao/OC_SORT), observation-centric, no ReID
  hybrid    : Hybrid-SORT (ymzis69/HybridSORT) non-ReID (TCM + 4-corner velocity + score cue)
  ensemble  : bytetrack-base + swap-guard (online) + offline tracklet stitch  [see ensemble.py]

Usage:
  python run_tracker.py --tracker bytetrack [--name byte] [--only seqA,seqB]
"""
import os, sys, argparse, glob, time
import numpy as np

DT = r"C:\Users\kiyus\Desktop\dancetrack"
VAL = os.path.join(DT, "val")
DETS = os.path.join(DT, "eval", "dets")
TRK_ROOT = os.path.join(DT, "eval", "trackers")
OC_SORT = os.path.join(DT, "eval", "OC_SORT")
HYBRID = os.path.join(DT, "eval", "HybridSORT")


def load_dets(seq):
    arr = np.load(os.path.join(DETS, seq + ".npy"))
    if arr.size == 0:
        return {}
    by = {}
    for r in arr:
        fid = int(r[0])
        by.setdefault(fid, []).append(r[1:6])  # x1,y1,x2,y2,score
    return {k: np.array(v, dtype=np.float32) for k, v in by.items()}


def num_frames(seq):
    img1 = os.path.join(VAL, seq, "img1")
    return len([f for f in os.listdir(img1) if f.lower().endswith(".jpg")])


def img_hw(seq):
    # read seqinfo.ini for imWidth/imHeight
    p = os.path.join(VAL, seq, "seqinfo.ini")
    w = h = None
    for line in open(p, encoding="utf-8", errors="ignore"):
        line = line.strip()
        if line.lower().startswith("imwidth"):
            w = int(line.split("=")[1])
        elif line.lower().startswith("imheight"):
            h = int(line.split("=")[1])
    return h, w


# ---------- tracker factories ----------
def make_bytetracker():
    import byte_tracker_ss as bt
    # config-F churn-tuned defaults
    return ("ss", bt.ByteTracker(
        track_high_thresh=0.20, track_low_thresh=0.10, new_track_thresh=0.30,
        track_buffer=150, match_thresh_high=0.3, match_thresh_low=0.5,
        match_thresh_unconfirmed=0.7), bt)


def make_ocsort():
    sys.path.insert(0, OC_SORT)
    from trackers.ocsort_tracker.ocsort import OCSort
    # DanceTrack defaults from OC_SORT run script: det_thresh 0.6 (high split),
    # iou 0.3, delta_t 3, inertia 0.2, use_byte True, max_age 30
    return ("oc", OCSort(det_thresh=0.6, iou_threshold=0.3, delta_t=3,
                         inertia=0.2, use_byte=True, max_age=30, min_hits=3), None)


def make_hybrid(det_thresh=0.6):
    sys.path.insert(0, HYBRID)
    from trackers.hybrid_sort_tracker.hybrid_sort import Hybrid_Sort
    from types import SimpleNamespace
    args = SimpleNamespace(
        track_thresh=det_thresh,
        iou_thresh=0.3,
        TCM_first_step=True,
        TCM_byte_step=True,
        TCM_first_step_weight=1.0,
        TCM_byte_step_weight=1.0,
        kalman_GPR=False,
        EG_weight_high_score=1.3,
        EG_weight_low_score=1.2,
        high_score_matching_thresh=0.8,
        low_score_matching_thresh=0.5,
        with_longterm_reid=False,
        with_longterm_reid_correction=False,
        longterm_reid_weight=0.0,
        longterm_reid_weight_low=0.0,
        longterm_reid_correction_thresh=1.0,
        longterm_reid_correction_thresh_low=1.0,
        longterm_bank_length=30,
        adapfs=False,
    )
    return ("hybrid", Hybrid_Sort(args, det_thresh=det_thresh, iou_threshold=0.3,
                                  delta_t=3, inertia=0.2, use_byte=True,
                                  max_age=30, min_hits=3, asso_func="iou"), None)


def run_seq(kind, tracker, mod, seq, out_path):
    dets = load_dets(seq)
    nf = num_frames(seq)
    h, w = img_hw(seq)
    lines = []
    for fid in range(1, nf + 1):
        fr = dets.get(fid, np.zeros((0, 5), np.float32))
        if kind == "ss":
            ds = [mod.Detection(bbox=tuple(d[:4]), score=float(d[4])) for d in fr]
            tracks = tracker.update(ds, frame_id=fid)
            for t in tracks:
                x1, y1, x2, y2 = t.xyxy
                lines.append((fid, t.track_id, x1, y1, x2 - x1, y2 - y1, t.score))
        else:
            # oc / hybrid: update(output_results[x1y1x2y2 score], img_info, img_size)
            out = tracker.update(fr if fr.shape[0] else np.empty((0, 5), np.float32),
                                 (h, w), (h, w))  # img_info==img_size -> scale=1
            for row in out:
                x1, y1, x2, y2, tid = row[0], row[1], row[2], row[3], int(row[4])
                lines.append((fid, tid, x1, y1, x2 - x1, y2 - y1, 1.0))
    with open(out_path, "w") as f:
        for (fid, tid, x, y, ww, hh, sc) in lines:
            f.write(f"{fid},{tid},{x:.2f},{y:.2f},{ww:.2f},{hh:.2f},{sc:.4f},-1,-1,-1\n")
    return len(lines), len(set(l[1] for l in lines))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tracker", required=True, choices=["bytetrack", "ocsort", "hybrid"])
    ap.add_argument("--name", default=None)
    ap.add_argument("--only", default=None)
    ap.add_argument("--det_thresh", type=float, default=0.6,
                    help="high/low split for ocsort/hybrid (ensemble lowers this for det recall)")
    args = ap.parse_args()
    name = args.name or args.tracker
    out_dir = os.path.join(TRK_ROOT, name, "data")
    os.makedirs(out_dir, exist_ok=True)

    seqs = sorted([d for d in os.listdir(VAL) if os.path.isdir(os.path.join(VAL, d))])
    if args.only:
        seqs = [s for s in seqs if s in args.only.split(",")]

    print(f"tracker={name} seqs={len(seqs)}", flush=True)
    for i, seq in enumerate(seqs):
        # fresh tracker per sequence
        if args.tracker == "bytetrack":
            kind, trk, mod = make_bytetracker()
        elif args.tracker == "ocsort":
            kind, trk, mod = make_ocsort()
        else:
            kind, trk, mod = make_hybrid(det_thresh=args.det_thresh)
        t0 = time.time()
        n, nid = run_seq(kind, trk, mod, seq, os.path.join(out_dir, seq + ".txt"))
        print(f"[{i+1}/{len(seqs)}] {seq} rows={n} ids={nid} {time.time()-t0:.1f}s", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
