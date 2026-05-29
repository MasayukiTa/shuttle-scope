import os, sys, json, time, statistics
os.environ.setdefault("PYTHONUTF8","1")
os.environ["TORCHINDUCTOR_CACHE_DIR"]=r"C:/Users/kiyus/Desktop/sam3_bench/triton/inductor_cache"
BENCH=r"C:/Users/kiyus/Desktop/sam3_bench"
IMG=518
N=int(sys.argv[1]) if len(sys.argv)>1 else 20
import torch, numpy as np
torch.set_float32_matmul_precision("high")
import torch._dynamo as dynamo
dynamo.config.cache_size_limit = 64  # allow a few shape variants without bailing
from ultralytics.models.sam.predict import SAM3SemanticPredictor
FRAME=r"C:/Users/kiyus/Desktop/github/shuttle-scope/shuttlescope/backend/.venv/Lib/site-packages/ultralytics/assets/bus.jpg"

def make():
    p=SAM3SemanticPredictor(overrides=dict(model=BENCH+"/sam3.pt",imgsz=IMG,conf=0.25,save=False,verbose=False,half=False))
    p.setup_model(model=None); return p, p.model.eval()
def get_masks(res):
    m=res[0].masks
    return None if m is None else m.data.detach().cpu().numpy().astype(bool)
def bench(pred,n,warm):
    ts=[]
    with torch.no_grad():
        for _ in range(warm): pred(source=FRAME,text=["person"]); torch.cuda.synchronize()
        m0=None
        for i in range(n):
            t=time.perf_counter(); res=pred(source=FRAME,text=["person"]); torch.cuda.synchronize()
            ts.append((time.perf_counter()-t)*1000.0)
            if i==0: m0=get_masks(res)
    return statistics.median(ts), m0
def best_iou(A,B):
    if A is None or B is None: return None
    out=[]
    for a in A:
        best=0.0
        for b in B:
            u=np.logical_or(a,b).sum()
            if u>0: best=max(best, np.logical_and(a,b).sum()/u)
        out.append(float(best))
    return out

res={"N":N,"config":"decoder-only inductor default dynamic=True no-cudagraphs"}
pred,pm=make()
e_ms,e_masks=bench(pred,N,3)
res["eager_ms_med"]=round(e_ms,2); res["eager_fps"]=round(1000/e_ms,2)
res["eager_nmasks"]=0 if e_masks is None else len(e_masks)
del pred,pm; torch.cuda.empty_cache(); dynamo.reset()

pred,pm=make()
try:
    pm.transformer.decoder=torch.compile(pm.transformer.decoder, dynamic=True)  # default backend=inductor, no cudagraphs
except Exception as ex:
    res["compile_err"]=repr(ex)
try:
    c_ms,c_masks=bench(pred,N,warm=8)
    res["compiled_ms_med"]=round(c_ms,2); res["compiled_fps"]=round(1000/c_ms,2)
    res["speedup_x"]=round(e_ms/c_ms,3)
    ious=best_iou(e_masks,c_masks)
    if ious:
        res["mask_iou_mean"]=round(float(np.mean(ious)),4); res["mask_iou_min"]=round(float(np.min(ious)),4)
    res["recompiles"]=len(getattr(dynamo.utils,"counters",{}).get("recompiles",{})) if hasattr(dynamo,"utils") else -1
except Exception as ex:
    import traceback; res["bench_err"]=traceback.format_exc()[-1500:]
print("DEC_JSON "+json.dumps(res))
with open(BENCH+"/triton/decoder_dyn_result.json","w") as f: json.dump(res,f,indent=2)
