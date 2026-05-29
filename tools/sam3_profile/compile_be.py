import os, sys, json, time, statistics
os.environ.setdefault("PYTHONUTF8","1")
BENCH=r"C:/Users/kiyus/Desktop/sam3_bench"
IMG=518
BE=sys.argv[1] if len(sys.argv)>1 else "cudagraphs"
N=int(sys.argv[2]) if len(sys.argv)>2 else 20
import torch, numpy as np
from ultralytics.models.sam.predict import SAM3SemanticPredictor
FRAME=r"C:/Users/kiyus/Desktop/github/shuttle-scope/shuttlescope/backend/.venv/Lib/site-packages/ultralytics/assets/bus.jpg"
def make():
    p=SAM3SemanticPredictor(overrides=dict(model=BENCH+"/sam3.pt",imgsz=IMG,conf=0.25,save=False,verbose=False,half=False))
    p.setup_model(model=None); return p,p.model.eval()
def gm(res):
    m=res[0].masks; return None if m is None else m.data.detach().cpu().numpy().astype(bool)
def bench(pred,n,warm):
    ts=[]; m0=None
    with torch.no_grad():
        for _ in range(warm): pred(source=FRAME,text=["person"]); torch.cuda.synchronize()
        for i in range(n):
            t=time.perf_counter(); r=pred(source=FRAME,text=["person"]); torch.cuda.synchronize()
            ts.append((time.perf_counter()-t)*1000.0)
            if i==0: m0=gm(r)
    return statistics.median(ts),m0
def biou(A,B):
    if A is None or B is None: return None
    o=[]
    for a in A:
        b_=0.0
        for b in B:
            u=np.logical_or(a,b).sum()
            if u>0: b_=max(b_,np.logical_and(a,b).sum()/u)
        o.append(float(b_))
    return o
res={"backend":BE,"N":N}
pred,pm=make(); e,em=bench(pred,N,3)
res["eager_ms_med"]=round(e,2); res["eager_fps"]=round(1000/e,2)
del pred,pm; torch.cuda.empty_cache()
pred,pm=make()
try:
    pm.backbone.forward_image=torch.compile(pm.backbone.forward_image, backend=BE)
    pm.transformer.decoder=torch.compile(pm.transformer.decoder, backend=BE)
    c,cm=bench(pred,N,6)
    res["compiled_ms_med"]=round(c,2); res["compiled_fps"]=round(1000/c,2); res["speedup_x"]=round(e/c,3)
    iou=biou(em,cm)
    if iou: res["mask_iou_mean"]=round(float(np.mean(iou)),4); res["mask_iou_min"]=round(float(np.min(iou)),4)
except Exception:
    import traceback; res["err"]=traceback.format_exc()[-1200:]
print("BE_JSON "+json.dumps(res))
with open(BENCH+"/profile/compile_be_%s.json"%BE,"w") as f: json.dump(res,f,indent=2)
