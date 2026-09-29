"""Offline post-association layer for the ENSEMBLE (tracker-agnostic).

Operates on a MOT-format file (frame,id,x,y,w,h,score,...) and applies two
mechanisms borrowed from ShuttleScope branches, generalized (no court priors):

  (1) SWAP-GUARD  (from cv/person_tracker.py _apply_swap_guard):
      For each frame, find near track pairs whose constant-velocity predicted
      centroids cross. Compare current-vs-swapped assignment prediction error;
      if swapping reduces total error by >= margin, relabel via an alias map.
      Fixes crossover ID swaps that pure-IoU/Kalman trackers make.

  (2) TRACKLET STITCHER (from cv/tracklet_stitcher.py, court priors removed):
      Greedy offline gap-bridging. For each fragment (tracklet) try to attach
      it to an earlier tracklet whose constant-velocity extrapolation lands near
      the fragment's start, within a time gap and spatial-jump budget. Merges
      fragments of the same identity that the online tracker split on occlusion.
      No appearance cue here (motion-only) since DanceTrack uniforms are uniform.

Usage:
  python postprocess.py --in <trackers/NAME/data> --out <trackers/NAME_pp/data>
                        [--no-swap] [--no-stitch] [--only seqA,seqB]
"""
import os, argparse
from collections import defaultdict, deque
import numpy as np

# ---- swap-guard params (from person_tracker defaults) ----
SWAP_MARGIN = float(os.environ.get("PP_SWAP_MARGIN", "0.30"))
SWAP_HISTORY = int(os.environ.get("PP_SWAP_HISTORY", "5"))
SWAP_MAX_PAIR_DIST = float(os.environ.get("PP_SWAP_MAX_DIST", "120.0"))
# ---- stitch params (generalized from tracklet_stitcher) ----
# Defaults = tuned winner on DanceTrack val (HOTA 47.00). Larger gap/jump budget
# bridges DanceTrack's long occlusions + fast motion better than the conservative
# badminton-court defaults.
STITCH_MAX_GAP = int(os.environ.get("PP_STITCH_MAX_GAP", "180"))
STITCH_MAX_JUMP = float(os.environ.get("PP_STITCH_MAX_JUMP", "350.0"))
STITCH_JUMP_PER_GAP = float(os.environ.get("PP_STITCH_JUMP_PER_GAP", "4.0"))
STITCH_EXTRAP_HIST = int(os.environ.get("PP_STITCH_EXTRAP_HIST", "8"))


def read_mot(path):
    rows = []
    for line in open(path):
        line = line.strip()
        if not line:
            continue
        p = line.split(",")
        f, i = int(float(p[0])), int(float(p[1]))
        x, y, w, h = float(p[2]), float(p[3]), float(p[4]), float(p[5])
        sc = float(p[6]) if len(p) > 6 else 1.0
        rows.append([f, i, x, y, w, h, sc])
    return rows


def write_mot(path, rows):
    rows = sorted(rows, key=lambda r: (r[0], r[1]))
    with open(path, "w") as fo:
        for f, i, x, y, w, h, sc in rows:
            fo.write(f"{f},{i},{x:.2f},{y:.2f},{w:.2f},{h:.2f},{sc:.4f},-1,-1,-1\n")


def _centroid(r):
    return r[2] + r[4] / 2.0, r[3] + r[5] / 2.0


def _predict(hist):
    """Constant-velocity prediction of next centroid from a deque of (cx,cy)."""
    if not hist:
        return None
    if len(hist) == 1:
        return hist[-1]
    (x0, y0), (x1, y1) = hist[-2], hist[-1]
    return (x1 + (x1 - x0), y1 + (y1 - y0))


def swap_guard(rows):
    """Relabel ids to fix crossover swaps. Returns new rows."""
    by_frame = defaultdict(list)
    for r in rows:
        by_frame[r[0]].append(r)
    alias = {}              # output relabel: raw_id -> canonical_id
    hist = defaultdict(lambda: deque(maxlen=SWAP_HISTORY))  # canonical_id -> centroid hist

    def canon(i):
        return alias.get(i, i)

    out = []
    for f in sorted(by_frame):
        frame_rows = by_frame[f]
        # apply current alias
        cur = []
        for r in frame_rows:
            cid = canon(r[1])
            cur.append((cid, r))
        # predicted centroids per canonical id (from history)
        preds = {cid: _predict(hist[cid]) for cid, _ in cur}
        obs = {cid: _centroid(r) for cid, r in cur}
        cids = [cid for cid, _ in cur]
        # evaluate near pairs for beneficial swap
        for a_i in range(len(cids)):
            for b_i in range(a_i + 1, len(cids)):
                a, b = cids[a_i], cids[b_i]
                pa, pb = preds.get(a), preds.get(b)
                if pa is None or pb is None:
                    continue
                ca, cb = obs[a], obs[b]
                d = np.hypot(pa[0] - pb[0], pa[1] - pb[1])
                if d > SWAP_MAX_PAIR_DIST:
                    continue
                err_cur = np.hypot(ca[0] - pa[0], ca[1] - pa[1]) + np.hypot(cb[0] - pb[0], cb[1] - pb[1])
                err_swap = np.hypot(ca[0] - pb[0], ca[1] - pb[1]) + np.hypot(cb[0] - pa[0], cb[1] - pa[1])
                if err_swap < err_cur * (1.0 - SWAP_MARGIN):
                    # swap canonical labels for a and b going forward
                    _swap_alias(alias, a, b)
                    # also swap their histories so prediction stays continuous
                    hist[a], hist[b] = hist[b], hist[a]
        # re-apply alias after potential swaps, update history + emit
        for _, r in cur:
            cid = canon(r[1])
            hist[cid].append(_centroid(r))
            out.append([r[0], cid, r[2], r[3], r[4], r[5], r[6]])
    return out


def _swap_alias(alias, a, b):
    # find raw ids currently mapping to a / b (including identity)
    raws_a = [k for k, v in alias.items() if v == a]
    raws_b = [k for k, v in alias.items() if v == b]
    if alias.get(a, a) == a:
        raws_a.append(a)
    if alias.get(b, b) == b:
        raws_b.append(b)
    for k in raws_a:
        alias[k] = b
    for k in raws_b:
        alias[k] = a


def _tracklets(rows):
    """Build per-id tracklets: id -> sorted list of (frame, cx, cy)."""
    by_id = defaultdict(list)
    for r in rows:
        cx, cy = _centroid(r)
        by_id[r[1]].append((r[0], cx, cy))
    for i in by_id:
        by_id[i].sort()
    return by_id


def stitch(rows):
    """Greedy motion-only offline stitching. Returns new rows with merged ids."""
    by_id = _tracklets(rows)
    metas = []
    for i, pts in by_id.items():
        fr = np.array([p[0] for p in pts])
        cx = np.array([p[1] for p in pts])
        cy = np.array([p[2] for p in pts])
        metas.append({"id": i, "start": int(fr.min()), "end": int(fr.max()),
                      "fr": fr, "cx": cx, "cy": cy})
    metas.sort(key=lambda m: m["start"])

    def extrap_end(m):
        n = len(m["fr"])
        if n == 1:
            return m["cx"][-1], m["cy"][-1], 0.0, 0.0
        k = min(STITCH_EXTRAP_HIST, n)
        fr = m["fr"][-k:].astype(float)
        span = max(fr[-1] - fr[0], 1.0)
        vx = (m["cx"][-k:][-1] - m["cx"][-k:][0]) / span
        vy = (m["cy"][-k:][-1] - m["cy"][-k:][0]) / span
        return float(m["cx"][-1]), float(m["cy"][-1]), float(vx), float(vy)

    chains = []  # {"tail": meta, "members":[ids]}
    for m in metas:
        best, best_cost = None, None
        for ch in chains:
            tail = ch["tail"]
            gap = m["start"] - tail["end"]
            if gap < 0 or gap > STITCH_MAX_GAP:
                continue
            ex, ey, vx, vy = extrap_end(tail)
            px, py = ex + vx * gap, ey + vy * gap
            dist = float(np.hypot(m["cx"][0] - px, m["cy"][0] - py))
            allow = STITCH_MAX_JUMP + STITCH_JUMP_PER_GAP * gap
            if dist > allow:
                continue
            cost = dist / max(allow, 1.0) + gap / (STITCH_MAX_GAP + 1)
            if best_cost is None or cost < best_cost:
                best_cost, best = cost, ch
        if best is None:
            chains.append({"tail": m, "members": [m["id"]]})
        else:
            best["members"].append(m["id"])
            if m["end"] > best["tail"]["end"]:
                best["tail"] = m
    # Guard: never merge members that occupy the same frame (would create
    # duplicate ids in a timestep). Build per-member frame sets and only keep
    # a member in the chain if it does not overlap already-accepted members.
    frames_of = {m["id"]: set(m["fr"].tolist()) for m in metas}
    remap = {}
    for ch in chains:
        accepted = []
        acc_frames = set()
        # process members in start order (chain already greedy in that order)
        for mid in sorted(ch["members"], key=lambda i: min(frames_of[i])):
            if frames_of[mid] & acc_frames:
                continue  # overlaps -> leave as its own id
            accepted.append(mid)
            acc_frames |= frames_of[mid]
        canon = min(accepted) if accepted else None
        for mid in accepted:
            remap[mid] = canon
    return [[r[0], remap.get(r[1], r[1]), r[2], r[3], r[4], r[5], r[6]] for r in rows]


def dedup_frame_ids(rows):
    """Final safety: if any frame has duplicate ids, keep the highest-score box
    and drop the others (TrackEval requires frame-unique ids)."""
    by_frame = defaultdict(list)
    for r in rows:
        by_frame[r[0]].append(r)
    out = []
    for f in sorted(by_frame):
        seen = {}
        for r in sorted(by_frame[f], key=lambda x: -x[6]):
            if r[1] in seen:
                continue
            seen[r[1]] = True
            out.append(r)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="indir", required=True)
    ap.add_argument("--out", dest="outdir", required=True)
    ap.add_argument("--no-swap", action="store_true")
    ap.add_argument("--no-stitch", action="store_true")
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    seqs = sorted([f for f in os.listdir(a.indir) if f.endswith(".txt")])
    if a.only:
        keep = set(s + ".txt" for s in a.only.split(","))
        seqs = [s for s in seqs if s in keep]
    print(f"postprocess in={a.indir} swap={not a.no_swap} stitch={not a.no_stitch} seqs={len(seqs)}", flush=True)
    for s in seqs:
        rows = read_mot(os.path.join(a.indir, s))
        n0 = len(set(r[1] for r in rows))
        if not a.no_swap:
            rows = swap_guard(rows)
        if not a.no_stitch:
            rows = stitch(rows)
        rows = dedup_frame_ids(rows)  # guarantee frame-unique ids
        n1 = len(set(r[1] for r in rows))
        write_mot(os.path.join(a.outdir, s), rows)
        print(f"{s} ids {n0}->{n1}", flush=True)
    print("DONE", flush=True)


if __name__ == "__main__":
    main()
