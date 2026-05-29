import os, sys, json, time, statistics
os.environ.setdefault("PYTHONUTF8","1")
BENCH=r"C:/Users/kiyus/Desktop/sam3_bench"
IMG=518
N=int(sys.argv[1]) if len(sys.argv)>1 else 20
import torch
from ultralytics.models.sam.predict import SAM3SemanticPredictor
FRAME=r"C:/Users/kiyus/Desktop/github/shuttle-scope/shuttlescope/backend/.venv/Lib/site-packages/ultralytics/assets/bus.jpg"

pred=SAM3SemanticPredictor(overrides=dict(model=BENCH+"/sam3.pt",imgsz=IMG,conf=0.25,save=False,verbose=False,half=False))
pred.setup_model(model=None)
pm=pred.model.eval()

# modules to hook via forward_hook (their __call__ IS invoked)
MOD_STAGES={
 "geometry_encoder": pm.geometry_encoder,
 "transformer.encoder": pm.transformer.encoder,
 "transformer.decoder": pm.transformer.decoder,
 "dot_prod_scoring": pm.dot_prod_scoring,
 "segmentation_head": pm.segmentation_head,
}
cur={}; acc={}
_t={}
def mk_pre(name):
    def f(m,i): torch.cuda.synchronize(); _t[name]=time.perf_counter()
    return f
def mk_post(name):
    def f(m,i,o): torch.cuda.synchronize(); cur[name]=cur.get(name,0.0)+(time.perf_counter()-_t[name])*1000.0
    return f
for n,m in MOD_STAGES.items():
    if m is None: continue
    m.register_forward_pre_hook(mk_pre(n)); m.register_forward_hook(mk_post(n))

# wrap methods: backbone.forward_image (encoder), backbone.forward_text, predictor preprocess/postprocess
import types
def timed_method(obj, attr, label, store):
    orig=getattr(obj,attr)
    def w(*a,**k):
        torch.cuda.synchronize(); t=time.perf_counter()
        r=orig(*a,**k); torch.cuda.synchronize(); store[label]=store.get(label,0.0)+(time.perf_counter()-t)*1000.0
        return r
    setattr(obj,attr,w)
timed_method(pm.backbone,"forward_image","image_encoder",cur)
timed_method(pm.backbone,"forward_text","text_encoder",cur)

pre_ms=[]; post_ms=[]; total_ms=[]
orig_pre=pred.preprocess; orig_post=pred.postprocess
def wpre(im):
    torch.cuda.synchronize(); t=time.perf_counter(); r=orig_pre(im); torch.cuda.synchronize()
    wpre.last=(time.perf_counter()-t)*1000.0; return r
def wpost(*a,**k):
    torch.cuda.synchronize(); t=time.perf_counter(); r=orig_post(*a,**k); torch.cuda.synchronize()
    wpost.last=(time.perf_counter()-t)*1000.0; return r
pred.preprocess=wpre; pred.postprocess=wpost

ALL=["image_encoder","text_encoder","geometry_encoder","transformer.encoder","transformer.decoder","dot_prod_scoring","segmentation_head"]
per={k:[] for k in ALL}
def run_once():
    cur.clear(); wpre.last=0.0; wpost.last=0.0
    torch.cuda.synchronize(); t=time.perf_counter()
    res=pred(source=FRAME, text=["person"])
    torch.cuda.synchronize(); return res,(time.perf_counter()-t)*1000.0

with torch.no_grad():
    for _ in range(3): run_once()
with torch.no_grad():
    for i in range(N):
        res,tot=run_once()
        for k in ALL: per[k].append(cur.get(k,0.0))
        pre_ms.append(wpre.last); post_ms.append(wpost.last); total_ms.append(tot)

def med(x): return round(statistics.median(x),2)
rows={"preprocess":med(pre_ms)}
for k in ALL: rows[k]=med(per[k])
rows["postprocess"]=med(post_ms)
tot=med(total_ms); summed=sum(rows.values())
out={"frame":FRAME,"img":IMG,"N":N,"total_ms_med":tot,"stage_sum_ms":round(summed,2),
     "unaccounted_ms":round(tot-summed,2),"fps_med":round(1000.0/tot,2),"stages":{}}
for k,v in rows.items(): out["stages"][k]={"ms":v,"pct_of_total":round(100*v/tot,1)}
try: out["n_masks_frame"]=int(res[0].masks.data.shape[0]) if res[0].masks is not None else 0
except: out["n_masks_frame"]=-1
print("PROF_JSON "+json.dumps(out))
with open(BENCH+"/profile/stage_profile.json","w") as f: json.dump(out,f,indent=2)
