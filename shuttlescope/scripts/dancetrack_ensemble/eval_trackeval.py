"""Run TrackEval (HOTA/CLEAR/Identity) on DanceTrack val for given tracker(s).

Emits a compact summary line per tracker:
  <name> HOTA=.. DetA=.. AssA=.. MOTA=.. IDF1=.. IDSW=.. IDs=..

Reads TrackEval's pedestrian_summary.txt that the lib writes per tracker.
"""
import os, sys, argparse

DT = r"C:\Users\kiyus\Desktop\dancetrack"
VAL = os.path.join(DT, "val")
TRK = os.path.join(DT, "eval", "trackers")
TE = os.path.join(DT, "eval", "TrackEval")
SEQMAP = os.environ.get("SEQMAP_OVERRIDE", os.path.join(DT, "eval", "dancetrack-val.seqmap"))

sys.path.insert(0, TE)
import trackeval  # noqa: E402


def run(trackers):
    eval_config = trackeval.Evaluator.get_default_eval_config()
    eval_config["USE_PARALLEL"] = False
    eval_config["NUM_PARALLEL_CORES"] = 1
    eval_config["PRINT_CONFIG"] = False
    eval_config["PRINT_RESULTS"] = False
    eval_config["OUTPUT_SUMMARY"] = True
    eval_config["OUTPUT_DETAILED"] = False
    eval_config["PLOT_CURVES"] = False
    eval_config["TIME_PROGRESS"] = False

    ds_config = trackeval.datasets.MotChallenge2DBox.get_default_dataset_config()
    ds_config["GT_FOLDER"] = VAL
    ds_config["TRACKERS_FOLDER"] = TRK
    ds_config["BENCHMARK"] = "dancetrack"
    ds_config["SPLIT_TO_EVAL"] = "val"
    ds_config["SKIP_SPLIT_FOL"] = True
    ds_config["DO_PREPROC"] = False  # DanceTrack: no distractor preprocessing
    ds_config["SEQMAP_FILE"] = SEQMAP
    ds_config["TRACKERS_TO_EVAL"] = trackers
    ds_config["PRINT_CONFIG"] = False

    metrics_config = {"METRICS": ["HOTA", "CLEAR", "Identity"], "THRESHOLD": 0.5,
                      "PRINT_CONFIG": False}

    evaluator = trackeval.Evaluator(eval_config)
    dataset_list = [trackeval.datasets.MotChallenge2DBox(ds_config)]
    metrics_list = []
    for metric in [trackeval.metrics.HOTA, trackeval.metrics.CLEAR, trackeval.metrics.Identity]:
        metrics_list.append(metric(metrics_config))
    output_res, _ = evaluator.evaluate(dataset_list, metrics_list)

    res = output_res["MotChallenge2DBox"]
    for trk in trackers:
        c = res[trk]["COMBINED_SEQ"]["pedestrian"]
        hota = c["HOTA"]
        clear = c["CLEAR"]
        ident = c["Identity"]
        import numpy as np
        def mean(x):
            return float(np.mean(x)) if hasattr(x, "__len__") else float(x)
        print(f"RESULT {trk} "
              f"HOTA={mean(hota['HOTA'])*100:.2f} "
              f"DetA={mean(hota['DetA'])*100:.2f} "
              f"AssA={mean(hota['AssA'])*100:.2f} "
              f"MOTA={clear['MOTA']*100:.2f} "
              f"IDF1={ident['IDF1']*100:.2f} "
              f"IDSW={int(clear['IDSW'])} "
              f"MT={int(clear['MT'])} ML={int(clear['ML'])} "
              f"FP={int(clear['CLR_FP'])} FN={int(clear['CLR_FN'])} "
              f"Frag={int(clear['Frag'])}", flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--trackers", required=True, help="comma list of tracker folder names")
    a = ap.parse_args()
    run(a.trackers.split(","))
