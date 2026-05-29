import os, glob, traceback, json
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
    # top-level children
    out["model_type"] = type(pm).__name__
    out["children"] = [(n, type(m).__name__) for n,m in pm.named_children()]
    # parameter counts per top module
    pc = {}
    for n,m in pm.named_children():
        pc[n] = sum(p.numel() for p in m.parameters())
    out["param_counts"] = pc
    print("PROBE_JSON", json.dumps(out, default=str)[:4000])
    with open(BENCH+"/e2e/probe_struct.json","w") as f: json.dump(out,f,indent=1,default=str)
except Exception as e:
    traceback.print_exc(); print("FAIL", repr(e))
