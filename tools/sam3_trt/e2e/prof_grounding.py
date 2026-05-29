import os, glob, traceback, json, time
os.environ.setdefault("KMP_DUPLICATE_LIB_OK","TRUE")
import torch, numpy as np
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
IMG = 518
out = {}
def sync(): torch.cuda.synchronize()
try:
    from ultralytics.models.sam.predict import SAM3SemanticPredictor
    pred = SAM3SemanticPredictor(overrides=dict(model=BENCH+"/sam3.pt", imgsz=IMG, conf=0.25, save=False, verbose=False, half=False))
    pred.setup_model(model=None)
    pm = pred.model.eval()
    frames = sorted(glob.glob(BENCH + "/frames/*.png"))

    T = {}
    def wrap(obj, name, key):
        orig = getattr(obj, name)
        def w(*a, **k):
            sync(); t0=time.time()
            r = orig(*a, **k)
            sync(); T.setdefault(key, []).append((time.time()-t0)*1000)
            return r
        setattr(obj, name, w)
        return orig

    # backbone.forward_image = encoder
    wrap(pm.backbone, "forward_image", "encoder")
    wrap(pm, "_encode_prompt", "geometry_encoder")
    wrap(pm, "_run_encoder", "transformer_encoder")
    wrap(pm, "_run_decoder", "transformer_decoder")
    wrap(pm, "_run_segmentation_heads", "seg_head")

    # also wrap whole inference for postproc estimate: forward_grounding total
    wrap(pm, "forward_grounding", "forward_grounding_total")

    with torch.no_grad():
        _ = pred(source=frames[0], text=["person"])  # warm
        T.clear()
        tot=[]
        for f in frames[:8]:
            sync(); t0=time.time()
            _ = pred(source=f, text=["person"])
            sync(); tot.append((time.time()-t0)*1000)
    T["full_predict_total"] = tot

    summary = {k: {"med_ms": round(float(np.median(v)),2), "n": len(v)} for k,v in T.items()}
    # postproc/overhead = full - forward_grounding - encoder roughly; report explicitly
    out["per_stage"] = summary
    print("PROFG_JSON", json.dumps(out, default=str))
    with open(BENCH+"/e2e/prof_grounding.json","w") as f: json.dump(out,f,indent=1,default=str)
except Exception as e:
    traceback.print_exc(); print("FAIL", repr(e))
