import os, glob, traceback, json, time
os.environ.setdefault("KMP_DUPLICATE_LIB_OK","TRUE")
import torch
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
IMG = 518
out = {}
try:
    from ultralytics.models.sam.predict import SAM3SemanticPredictor
    pred = SAM3SemanticPredictor(overrides=dict(model=BENCH+"/sam3.pt", imgsz=IMG, conf=0.25, save=False, verbose=False, half=False))
    pred.setup_model(model=None)
    pm = pred.model.eval()
    frames = sorted(glob.glob(BENCH + "/frames/*.png"))

    # timing accumulators per top-level module
    times = {}
    shapes = {}
    def mk_hook(name):
        def pre(mod, inp):
            torch.cuda.synchronize(); mod._t0 = time.time()
        def post(mod, inp, outp):
            torch.cuda.synchronize()
            dt = (time.time()-mod._t0)*1000
            times.setdefault(name, []).append(dt)
            if name not in shapes:
                def descr(x):
                    if torch.is_tensor(x): return list(x.shape)
                    if isinstance(x,(list,tuple)): return [descr(e) for e in x][:6]
                    if isinstance(x,dict): return {k:descr(v) for k,v in list(x.items())[:8]}
                    return type(x).__name__
                shapes[name] = {"in": [descr(i) for i in inp], "out": descr(outp)}
        return pre, post

    handles=[]
    for n,m in pm.named_children():
        pre,post = mk_hook(n)
        handles.append(m.register_forward_pre_hook(pre))
        handles.append(m.register_forward_hook(post))

    with torch.no_grad():
        _ = pred(source=frames[0], text=["person"])  # warm
        # reset
        times.clear()
        for f in frames[:6]:
            _ = pred(source=f, text=["person"])

    import numpy as np
    summary = {}
    for k,v in times.items():
        summary[k] = {"med_ms": round(float(np.median(v)),2), "n_calls": len(v), "calls_per_frame": round(len(v)/6,2)}
    out["per_stage_med_ms"] = summary
    out["shapes"] = shapes
    print("PROF_JSON", json.dumps(out, default=str)[:6000])
    with open(BENCH+"/e2e/prof_stages.json","w") as f: json.dump(out,f,indent=1,default=str)
except Exception as e:
    traceback.print_exc(); print("FAIL", repr(e))
