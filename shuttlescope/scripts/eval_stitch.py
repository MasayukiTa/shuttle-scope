import argparse, json, sys
from pathlib import Path
# worktree: scripts/ から backend.cv をimport。ローカル単体実行時は同ディレクトリも許容。
_here = Path(__file__).resolve().parent
sys.path.insert(0, str(_here))
sys.path.insert(0, str(_here.parent))  # shuttlescope/ (backend package)
try:
    from backend.cv.tracklet_stitcher import load_tracklets, stitch, StitchConfig, SIDE_OF_COURT
except Exception:
    from tracklet_stitcher import load_tracklets, stitch, StitchConfig, SIDE_OF_COURT

_ap = argparse.ArgumentParser()
_ap.add_argument("--data-dir", default=None, help="tracklets.json + npz があるディレクトリ")
_args, _ = _ap.parse_known_args()
base = Path(_args.data_dir) if _args.data_dir else _here
tl = load_tracklets(base / "tracklets.json", base / "tracklet_embeddings.npz")
meta = json.loads((base / "tracklets.json").read_text(encoding="utf-8"))
print("raw tracklets (before):", len(tl), " reid_kind:", meta.get("reid_kind"))

# per-side raw count (before)
from collections import Counter
raw_side = Counter()
for t in tl:
    if t.dom_court >= 0:
        raw_side[SIDE_OF_COURT[t.dom_court]] += 1
print("raw player-court tracklets per side: far(0,1)=%d near(2,3)=%d" % (raw_side[0], raw_side[1]))

cfg = StitchConfig()
res = stitch(tl, cfg)
d = res["diag"]
print("\n=== AFTER STITCH ===")
for k, v in d.items():
    print(" ", k, "=", v)

# mapping summary
print("\nstable_id -> #raw_tracks merged:")
inv = Counter(v for v in res["mapping"].values())
for sid in sorted(inv):
    print("  stable %s : %d raw tracks" % (sid, inv[sid]))

# emit mapping json
out = {"mapping": {str(k): v for k, v in res["mapping"].items()}, "diag": d, "config": res["config"]}
(base / "stitch_mapping.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
print("\nwrote stitch_mapping.json")
