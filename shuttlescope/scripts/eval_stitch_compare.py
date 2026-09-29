"""HSV vs OSNet 比較 + quadrant 制約緩和実験。

usage: python eval_compare.py <hsv_dir> <osnet_dir>
出力: stitch_compare/compare_result.json
"""
import json, sys
from pathlib import Path
from collections import Counter, defaultdict
import numpy as np

ROOT = Path(r"C:/Users/kiyus/Desktop/wt-stitch/shuttlescope")
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from backend.cv.tracklet_stitcher import (
    load_tracklets, stitch, StitchConfig, SIDE_OF_COURT, _mark_background, _extrap_end, _cosine,
)

HSV_DIR = Path(sys.argv[1]); OSNET_DIR = Path(sys.argv[2])
RES = Path(r"C:/Users/kiyus/Desktop/stitch_compare/compare_result.json")


def side_counts(tl):
    c = Counter()
    for t in tl:
        if t.dom_court >= 0:
            c[SIDE_OF_COURT[t.dom_court]] += 1
    return {"far": c[0], "near": c[1]}


def cos(a, b):
    if a is None or b is None: return None
    a = a.ravel().astype(np.float32); b = b.ravel().astype(np.float32)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-9 or nb < 1e-9: return None
    return float(np.dot(a, b) / (na * nb))


def cosine_separation(tl):
    """背景除去後 player tracklet の quadrant 別 pair cosine 分布。"""
    cfg = StitchConfig(); _mark_background(tl, cfg)
    pl = [t for t in tl if not t.is_background and t.rep_emb is not None
          and t.dom_court >= 0 and np.linalg.norm(t.rep_emb) > 1e-6 and t.n_frames >= 5]
    same_q, cross_q_same_side, opp = [], [], []
    for i in range(len(pl)):
        for j in range(i + 1, len(pl)):
            c = cos(pl[i].rep_emb, pl[j].rep_emb)
            if c is None: continue
            if pl[i].dom_court == pl[j].dom_court: same_q.append(c)
            elif SIDE_OF_COURT[pl[i].dom_court] == SIDE_OF_COURT[pl[j].dom_court]: cross_q_same_side.append(c)
            else: opp.append(c)
    def st(xs):
        if not xs: return None
        a = np.array(xs)
        return {"n": len(xs), "mean": round(float(a.mean()), 4), "median": round(float(np.median(a)), 4),
                "p25": round(float(np.percentile(a, 25)), 4), "p75": round(float(np.percentile(a, 75)), 4)}
    return {"n_player_tracklets": len(pl), "same_quadrant": st(same_q),
            "same_side_cross_quadrant_TEAMMATE": st(cross_q_same_side), "opposite_side": st(opp)}


def stitch_relaxed(tl, app_thresh, max_per_side=2):
    """quadrant hard 制約を外し、SIDE 内で appearance+motion クラスタリング。
    各 side について fragment を貪欲連結し、できた chain を side 内で
    representative embedding の cosine で凝集 (>app_thresh は同一選手)。
    side ごとに最大 max_per_side identity を返す。stable_id: far=0,1 near=2,3。"""
    cfg = StitchConfig(); _mark_background(tl, cfg)
    players = [t for t in tl if not t.is_background]
    mapping = {}
    side_id_base = {0: 0, 1: 2}
    diag_side = {}
    for side in (0, 1):
        frags = sorted([t for t in players if t.dom_court >= 0 and SIDE_OF_COURT[t.dom_court] == side],
                       key=lambda t: t.start_frame)
        # 1) motion+appearance greedy chain (quadrant 無視)
        chains = []
        for fr in frags:
            best, bc = None, None
            for ch in chains:
                tail = ch["tail"]
                gap = fr.start_frame - tail.end_frame
                if gap < 0 or gap > cfg.max_gap_frames: continue
                ex, ey, vx, vy = _extrap_end(tail, cfg.extrap_history)
                px, py = ex + vx * gap, ey + vy * gap
                dist = float(np.hypot(fr.cxs[0] - px, fr.cys[0] - py))
                allow = cfg.max_jump_px + cfg.jump_per_gap_px * gap
                if dist > allow: continue
                c = _cosine(tail.rep_emb, fr.rep_emb)
                if c is not None and c < app_thresh: continue
                cost = dist / max(allow, 1.0) + (0.0 if c is None else (1.0 - c)) + gap / (cfg.max_gap_frames + 1)
                if bc is None or cost < bc: bc, best = cost, ch
            if best is None:
                chains.append({"tail": fr, "members": [fr.track_id], "embs": [fr.rep_emb], "wsum": fr.n_frames})
            else:
                best["members"].append(fr.track_id); best["embs"].append(fr.rep_emb)
                best["wsum"] += fr.n_frames
                if fr.end_frame > best["tail"].end_frame: best["tail"] = fr
        # 2) chain の weighted-mean embedding
        def chain_emb(ch):
            es = [e for e in ch["embs"] if e is not None and np.linalg.norm(e) > 1e-6]
            if not es: return None
            m = np.mean(np.stack(es, 0), 0); n = np.linalg.norm(m)
            return m / n if n > 1e-9 else None
        # 3) chain を frame-weight 降順、appearance で max_per_side クラスタへ凝集
        chains.sort(key=lambda c: -c["wsum"])
        clusters = []  # {"emb":vec, "members":[...]}
        for ch in chains:
            e = chain_emb(ch)
            placed = False
            if e is not None and clusters:
                sims = [(cos(e, cl["emb"]) if cl["emb"] is not None else None) for cl in clusters]
                best_i = max(range(len(clusters)), key=lambda k: (sims[k] if sims[k] is not None else -1))
                if sims[best_i] is not None and sims[best_i] >= app_thresh:
                    clusters[best_i]["members"].extend(ch["members"]); placed = True
            if not placed:
                if len(clusters) < max_per_side:
                    clusters.append({"emb": e, "members": list(ch["members"])})
                else:
                    # 既存クラスタで最も近いものへ
                    if e is not None:
                        sims = [(cos(e, cl["emb"]) if cl["emb"] is not None else -1) for cl in clusters]
                        clusters[int(np.argmax(sims))]["members"].extend(ch["members"])
                    else:
                        clusters[0]["members"].extend(ch["members"])
        diag_side[side] = {"n_frags": len(frags), "n_chains": len(chains), "n_clusters": len(clusters)}
        for k, cl in enumerate(clusters):
            sid = side_id_base[side] + k
            for tid in cl["members"]:
                mapping[tid] = sid
    for t in tl:
        if t.track_id not in mapping: mapping[t.track_id] = -1
    stable = sorted(set(v for v in mapping.values() if v >= 0))
    return {"mapping": mapping, "n_stable_ids": len(stable), "stable_ids": stable, "diag_side": diag_side}


res = {}
for name, d in [("HSV", HSV_DIR), ("OSNET", OSNET_DIR)]:
    meta = json.loads((d / "tracklets.json").read_text(encoding="utf-8"))
    tl = load_tracklets(d / "tracklets.json", d / "tracklet_embeddings.npz")
    base = stitch(tl, StitchConfig())
    # reload (stitch mutates is_background)
    tl2 = load_tracklets(d / "tracklets.json", d / "tracklet_embeddings.npz")
    sep = cosine_separation(tl2)
    tl3 = load_tracklets(d / "tracklets.json", d / "tracklet_embeddings.npz")
    relaxed = {th: stitch_relaxed(load_tracklets(d / "tracklets.json", d / "tracklet_embeddings.npz"), th)
               for th in (0.5, 0.6, 0.7, 0.8)}
    res[name] = {
        "reid_kind": meta.get("reid_kind"), "emb_dim": meta.get("emb_dim"),
        "n_raw_tracks": len(tl), "raw_side_counts": side_counts(tl),
        "baseline_hard_quadrant": {k: base["diag"][k] for k in
            ("n_background", "n_players", "n_stable_ids", "far_side_ids", "near_side_ids",
             "n_chains_per_identity", "fragments_per_identity")},
        "cosine_separation": sep,
        "relaxed_side_cluster": {str(th): {"n_stable_ids": r["n_stable_ids"], "stable_ids": r["stable_ids"],
                                            "diag_side": r["diag_side"]} for th, r in relaxed.items()},
    }

RES.write_text(json.dumps(res, indent=2), encoding="utf-8")
print(json.dumps(res, indent=2))
