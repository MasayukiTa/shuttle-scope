import json, glob, os, traceback
import numpy as np, torch
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
OUT = BENCH + "/trt_samples"
os.makedirs(OUT, exist_ok=True)
IMG = 518
out = {}
try:
    import tensorrt as trt
    os.add_dll_directory(r"C:/TensorRT/TensorRT-10.16.1.11/lib")
    os.add_dll_directory(r"C:/Users/kiyus/Desktop/github/shuttle-scope/shuttlescope/backend/.venv/Lib/site-packages/torch/lib")
    from PIL import Image
    from ultralytics.models.sam.predict import SAM3SemanticPredictor
    LOG = trt.Logger(trt.Logger.ERROR)
    with open(BENCH + "/sam3_enc_518_fix_notactic.plan","rb") as f, trt.Runtime(LOG) as rt:
        engine = rt.deserialize_cuda_engine(f.read())
    ctx = engine.create_execution_context()
    onames = ["vision_features","fpn0","fpn1","fpn2","pos0","pos1","pos2"]
    def trt_infer(x):
        x=x.contiguous().float(); ctx.set_input_shape("pixel_values", tuple(x.shape)); ctx.set_tensor_address("pixel_values", x.data_ptr())
        b={}
        for n in onames:
            t=torch.empty(tuple(ctx.get_tensor_shape(n)),dtype=torch.float32,device="cuda").contiguous(); b[n]=t; ctx.set_tensor_address(n,t.data_ptr())
        ctx.execute_async_v3(torch.cuda.current_stream().cuda_stream); torch.cuda.synchronize(); return b
    pred = SAM3SemanticPredictor(overrides=dict(model=BENCH+"/sam3.pt", imgsz=IMG, conf=0.25, save=False, verbose=False, half=False))
    pred.setup_model(model=None); pm=pred.model.eval(); bb=pm.backbone
    frames = sorted(glob.glob(BENCH+"/frames/*.png"))
    sel = [frames[0], frames[7], frames[15], frames[24]]
    with torch.no_grad(): _=pred(source=frames[0], text=["person"])
    def get_masks(res):
        m=res[0].masks
        return None if m is None else m.data.detach().cpu().numpy().astype(bool)
    def union_overlay(path, masks, color):
        img=np.array(Image.open(path).convert("RGB")); H,W=img.shape[:2]
        o=img.astype(np.float32)
        if masks is not None:
            for m in masks:
                mm=m if m.shape==(H,W) else (np.array(Image.fromarray(m.astype(np.uint8)*255).resize((W,H)))>127)
                o[mm]=0.5*o[mm]+0.5*np.array(color,np.float32)
        return o.clip(0,255).astype(np.uint8)
    def best_iou(A,B):
        if A is None or B is None: return None
        ious=[]
        for a in A:
            best=0.0
            for b in B:
                i=np.logical_and(a,b).sum(); u=np.logical_or(a,b).sum()
                if u>0: best=max(best,i/u)
            ious.append(best)
        return ious
    orig=bb.forward_image
    summ={}
    for idx,fp in enumerate(sel):
        bb.forward_image=orig
        with torch.no_grad(): rpt=pred(source=fp, text=["person"]); torch.cuda.synchronize()
        mpt=get_masks(rpt)
        def hooked(s):
            b=trt_infer(s); return {"vision_features":b["vision_features"],"vision_pos_enc":[b["pos0"],b["pos1"],b["pos2"]],"backbone_fpn":[b["fpn0"],b["fpn1"],b["fpn2"]]}
        bb.forward_image=hooked
        with torch.no_grad(): rhy=pred(source=fp, text=["person"]); torch.cuda.synchronize()
        bb.forward_image=orig
        mhy=get_masks(rhy)
        ious=best_iou(mpt,mhy)
        miou=float(np.mean(ious)) if ious else None
        pti=union_overlay(fp,mpt,(0,255,0)); hyi=union_overlay(fp,mhy,(255,80,0))
        H=pti.shape[0]; sep=np.full((H,8,3),255,np.uint8)
        Image.fromarray(np.concatenate([pti,sep,hyi],axis=1)).save(OUT+f"/sample{idx}_{os.path.basename(fp)}_pt_vs_trt.png")
        summ[os.path.basename(fp)]={"pt_masks":0 if mpt is None else len(mpt),"hy_masks":0 if mhy is None else len(mhy),"mean_iou":round(miou,4) if miou else None}
    out["samples"]=summ; out["saved"]=sorted(os.listdir(OUT))
    print("SAMPLES_JSON", json.dumps(out, default=str))
    with open(BENCH+"/samples_result.json","w") as f: json.dump(out,f,indent=1,default=str)
except Exception as e:
    traceback.print_exc(); print("SAMPLES_FAIL", repr(e))
    with open(BENCH+"/samples_result.json","w") as f: json.dump({"FAIL":repr(e)},f)
