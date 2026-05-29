import json, os, traceback
import numpy as np
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
out = {}
try:
    os.add_dll_directory(r"C:/Users/kiyus/Desktop/github/shuttle-scope/shuttlescope/backend/.venv/Lib/site-packages/torch/lib")
    import onnxruntime as ort
    ref = np.load(BENCH + "/enc_ref.npz")
    x = ref["sample"].astype(np.float32)
    so = ort.SessionOptions(); so.log_severity_level = 3
    prov = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    sess = ort.InferenceSession(BENCH + "/sam3_enc_518_fix.onnx", so, providers=prov)
    out["providers"] = sess.get_providers()
    onames = [o.name for o in sess.get_outputs()]
    res = sess.run(None, {"pixel_values": x})
    d = dict(zip(onames, res))
    def cmp(a, b):
        a = a.astype(np.float64); b = b.astype(np.float64)
        diff = np.abs(a - b)
        rel = diff.mean() / (np.abs(a).mean() + 1e-8)
        corr = np.corrcoef(a.flatten(), b.flatten())[0, 1]
        return {"rel_mean": round(float(rel), 5), "corr": round(float(corr), 5), "max_abs": round(float(diff.max()), 4)}
    comp = {}
    comp["vision_features"] = cmp(ref["vision_features"], d["vision_features"])
    comp["fpn0"] = cmp(ref["fpn0"], d["fpn0"])
    comp["fpn1"] = cmp(ref["fpn1"], d["fpn1"])
    comp["fpn2"] = cmp(ref["fpn2"], d["fpn2"])
    out["compare"] = comp
    out["worst_rel"] = round(max(v["rel_mean"] for v in comp.values()), 5)
    out["PASS"] = out["worst_rel"] < 1e-2
    print("ORTVERIFY_JSON", json.dumps(out, default=str))
    with open(BENCH + "/verify_ort_result.json", "w") as f:
        json.dump(out, f, indent=1, default=str)
except Exception as e:
    traceback.print_exc(); print("ORTVERIFY_FAIL", repr(e))
