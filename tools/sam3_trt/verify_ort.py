import json, os, sys, traceback
import numpy as np
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
ONNX = sys.argv[1] if len(sys.argv) > 1 else BENCH + "/sam3_enc_518_fix.onnx"
out = {"onnx": ONNX}
try:
    os.add_dll_directory(r"C:/Users/kiyus/Desktop/github/shuttle-scope/shuttlescope/backend/.venv/Lib/site-packages/torch/lib")
    import onnxruntime as ort
    ref = np.load(BENCH + "/enc_ref.npz")
    x = ref["sample"].astype(np.float32)
    so = ort.SessionOptions(); so.log_severity_level = 3
    prov = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    sess = ort.InferenceSession(ONNX, so, providers=prov)
    out["providers"] = sess.get_providers()
    iname = sess.get_inputs()[0].name
    onames = [o.name for o in sess.get_outputs()]
    out["input_name"] = iname; out["output_names"] = onames
    res = sess.run(None, {iname: x})
    # outputs are positional: vision_features, fpn0, fpn1, fpn2, pos0, pos1, pos2
    pos = {"vision_features": res[0], "fpn0": res[1], "fpn1": res[2], "fpn2": res[3]}
    def cmp(a, b):
        a = a.astype(np.float64); b = b.astype(np.float64)
        diff = np.abs(a - b)
        rel = diff.mean() / (np.abs(a).mean() + 1e-8)
        corr = np.corrcoef(a.flatten(), b.flatten())[0, 1]
        return {"rel_mean": round(float(rel), 5), "corr": round(float(corr), 5), "max_abs": round(float(diff.max()), 4)}
    comp = {}
    comp["vision_features"] = cmp(ref["vision_features"], pos["vision_features"])
    comp["fpn0"] = cmp(ref["fpn0"], pos["fpn0"])
    comp["fpn1"] = cmp(ref["fpn1"], pos["fpn1"])
    comp["fpn2"] = cmp(ref["fpn2"], pos["fpn2"])
    out["compare"] = comp
    out["worst_rel"] = round(max(v["rel_mean"] for v in comp.values()), 5)
    out["PASS"] = out["worst_rel"] < 1e-2
    print("ORTVERIFY_JSON", json.dumps(out, default=str))
    with open(BENCH + "/verify_ort_result.json", "w") as f:
        json.dump(out, f, indent=1, default=str)
except Exception as e:
    traceback.print_exc(); print("ORTVERIFY_FAIL", repr(e))
