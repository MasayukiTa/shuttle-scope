"""Per-sequence HOTA/AssA/DetA/IDSW for selected trackers (strength/weakness analysis)."""
import os, sys
DT = r"C:\Users\kiyus\Desktop\dancetrack"
VAL = os.path.join(DT, "val"); TRK = os.path.join(DT, "eval", "trackers")
TE = os.path.join(DT, "eval", "TrackEval"); SEQMAP = os.path.join(DT, "eval", "dancetrack-val.seqmap")
sys.path.insert(0, TE)
import numpy as np, trackeval

trackers = sys.argv[1].split(",") if len(sys.argv) > 1 else ["bytetrack", "hybrid", "ensemble_stitchonly"]
ec = trackeval.Evaluator.get_default_eval_config()
ec.update({"USE_PARALLEL": False, "PRINT_CONFIG": False, "PRINT_RESULTS": False,
           "OUTPUT_SUMMARY": False, "OUTPUT_DETAILED": False, "PLOT_CURVES": False, "TIME_PROGRESS": False})
dc = trackeval.datasets.MotChallenge2DBox.get_default_dataset_config()
dc.update({"GT_FOLDER": VAL, "TRACKERS_FOLDER": TRK, "BENCHMARK": "dancetrack", "SPLIT_TO_EVAL": "val",
           "SKIP_SPLIT_FOL": True, "DO_PREPROC": False, "SEQMAP_FILE": SEQMAP,
           "TRACKERS_TO_EVAL": trackers, "PRINT_CONFIG": False})
mc = {"METRICS": ["HOTA", "CLEAR", "Identity"], "THRESHOLD": 0.5, "PRINT_CONFIG": False}
ev = trackeval.Evaluator(ec)
res, _ = ev.evaluate([trackeval.datasets.MotChallenge2DBox(dc)],
                     [trackeval.metrics.HOTA(mc), trackeval.metrics.CLEAR(mc), trackeval.metrics.Identity(mc)])
R = res["MotChallenge2DBox"]
seqs = sorted([d for d in os.listdir(VAL) if os.path.isdir(os.path.join(VAL, d))])
def m(x):
    return float(np.mean(x)) if hasattr(x, "__len__") else float(x)
# header
print("seq," + ",".join(f"{t}_HOTA,{t}_AssA,{t}_IDSW" for t in trackers))
for s in seqs:
    cells = [s]
    for t in trackers:
        c = R[t][s]["pedestrian"]
        cells += [f"{m(c['HOTA']['HOTA'])*100:.1f}", f"{m(c['HOTA']['AssA'])*100:.1f}", f"{int(c['CLEAR']['IDSW'])}"]
    print(",".join(cells))
