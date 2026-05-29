import os, json, time, glob, traceback
os.environ.setdefault("KMP_DUPLICATE_LIB_OK","TRUE")
import numpy as np
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
E2E = BENCH + "/e2e"
IMG = 518
out = {}
def sync(): import torch; torch.cuda.synchronize()
try:
    import tensorrt as trt
    torchlib = r"C:/Users/kiyus/Desktop/github/shuttle-scope/shuttlescope/backend/.venv/Lib/site-packages/torch/lib"
    os.add_dll_directory(r"C:/TensorRT/TensorRT-10.16.1.11/lib")
    os.add_dll_directory(torchlib)
    import torch
    from ultralytics.models.sam.predict import SAM3SemanticPredictor

    LOG = trt.Logger(trt.Logger.WARNING)
    # ---- encoder engine ----
    with open(BENCH+"/sam3_enc_518_fix_notactic.plan","rb") as f, trt.Runtime(LOG) as rt:
        enc_eng = rt.deserialize_cuda_engine(f.read())
    enc_ctx = enc_eng.create_execution_context()
    enc_out_names=["vision_features","fpn0","fpn1","fpn2","pos0","pos1","pos2"]
    def enc_trt(x):
        x=x.contiguous().float(); enc_ctx.set_input_shape("pixel_values", tuple(x.shape))
        enc_ctx.set_tensor_address("pixel_values", x.data_ptr()); b={}
        for n in enc_out_names:
            t=torch.empty(tuple(enc_ctx.get_tensor_shape(n)),dtype=torch.float32,device="cuda").contiguous()
            b[n]=t; enc_ctx.set_tensor_address(n,t.data_ptr())
        enc_ctx.execute_async_v3(torch.cuda.current_stream().cuda_stream); torch.cuda.synchronize()
        return b
    # ---- decoder engine ----
    with open(E2E+"/sam3_dec_notactic.plan","rb") as f, trt.Runtime(LOG) as rt:
        dec_eng = rt.deserialize_cuda_engine(f.read())
    dec_ctx = dec_eng.create_execution_context()
    dec_in=["tgt","memory","pos","valid_ratios","memory_text","text_attention_mask"]
    dec_out=["hs","ref_boxes","presence"]
    def dec_trt(tgt,memory,pos,valid_ratios,memory_text,text_attention_mask):
        feeds={"tgt":tgt,"memory":memory,"pos":pos,"valid_ratios":valid_ratios,
               "memory_text":memory_text,"text_attention_mask":text_attention_mask}
        for n in dec_in:
            t=feeds[n].contiguous(); dec_ctx.set_input_shape(n,tuple(t.shape))
            dec_ctx.set_tensor_address(n,t.data_ptr()); feeds[n]=t
        o={}
        for n in dec_out:
            t=torch.empty(tuple(dec_ctx.get_tensor_shape(n)),dtype=torch.float32,device="cuda").contiguous()
            o[n]=t; dec_ctx.set_tensor_address(n,t.data_ptr())
        dec_ctx.execute_async_v3(torch.cuda.current_stream().cuda_stream); torch.cuda.synchronize()
        return o["hs"], o["ref_boxes"], o["presence"]

    pred = SAM3SemanticPredictor(overrides=dict(model=BENCH+"/sam3.pt", imgsz=IMG, conf=0.25, save=False, verbose=False, half=False))
    pred.setup_model(model=None)
    pm = pred.model.eval(); bb=pm.backbone; dec=pm.transformer.decoder
    frames = sorted(glob.glob(BENCH + "/frames/*.png"))
    with torch.no_grad(): _=pred(source=frames[0], text=["person"])

    def count_masks(res):
        try:
            m=res[0].masks; return 0 if m is None else int(m.data.shape[0])
        except Exception: return -1
    def get_masks(res):
        m=res[0].masks
        return None if m is None else m.data.detach().cpu().numpy().astype(bool)

    # ---------- PyTorch baseline ----------
    torch.cuda.reset_peak_memory_stats()
    pt_t=[]; pt_counts=[]; pt_masks0=None
    with torch.no_grad():
        for i,f in enumerate(frames):
            sync(); t0=time.time(); res=pred(source=f, text=["person"]); sync()
            pt_t.append((time.time()-t0)*1000); pt_counts.append(count_masks(res))
            if i==0: pt_masks0=get_masks(res)
    pt_vram=torch.cuda.max_memory_allocated()/1e6

    # ---------- hooks ----------
    orig_fi=bb.forward_image
    def enc_hook(samples):
        b=enc_trt(samples)
        return {"vision_features":b["vision_features"],
                "vision_pos_enc":[b["pos0"],b["pos1"],b["pos2"]],
                "backbone_fpn":[b["fpn0"],b["fpn1"],b["fpn2"]]}
    orig_dec=dec.forward
    def dec_hook(*a, **k):
        # only handle our exact single-prompt path; fall back otherwise
        try:
            tgt=k["tgt"]; memory=k["memory"]; pos=k["pos"]; valid_ratios=k["valid_ratios"]
            memory_text=k["memory_text"]; tam=k["text_attention_mask"]
            if k.get("reference_boxes") is None and k.get("apply_dac") in (False,None) \
               and tuple(tgt.shape)==(200,1,256) and tuple(memory.shape)==(1369,1,256) \
               and tuple(memory_text.shape)==(32,1,256):
                hs,ref,pres=dec_trt(tgt,memory,pos,valid_ratios,memory_text,tam)
                return hs, ref, pres, None
        except Exception as ex:
            print("DEC_HOOK_FALLBACK", repr(ex))
        return orig_dec(*a, **k)

    # ---------- hybrid: encoder TRT only ----------
    bb.forward_image=enc_hook
    torch.cuda.reset_peak_memory_stats()
    encq_t=[]; encq_counts=[]
    with torch.no_grad():
        for i,f in enumerate(frames):
            sync(); t0=time.time(); res=pred(source=f, text=["person"]); sync()
            encq_t.append((time.time()-t0)*1000); encq_counts.append(count_masks(res))

    # ---------- hybrid: encoder + decoder TRT ----------
    dec.forward=dec_hook
    torch.cuda.reset_peak_memory_stats()
    hy_t=[]; hy_counts=[]; hy_masks0=None
    with torch.no_grad():
        for i,f in enumerate(frames):
            sync(); t0=time.time(); res=pred(source=f, text=["person"]); sync()
            hy_t.append((time.time()-t0)*1000); hy_counts.append(count_masks(res))
            if i==0: hy_masks0=get_masks(res)
    hy_vram=torch.cuda.max_memory_allocated()/1e6
    bb.forward_image=orig_fi; dec.forward=orig_dec

    def fps(ts):
        ts=ts[1:] if len(ts)>1 else ts
        return round(1000.0/np.median(ts),2), round(float(np.median(ts)),1)
    out["pt_fps"],out["pt_ms"]=fps(pt_t)
    out["encTRT_fps"],out["encTRT_ms"]=fps(encq_t)
    out["encdecTRT_fps"],out["encdecTRT_ms"]=fps(hy_t)
    out["pt_vram_mb"]=round(pt_vram,1); out["hy_vram_mb"]=round(hy_vram,1)
    out["pt_counts"]=pt_counts; out["encTRT_counts"]=encq_counts; out["hy_counts"]=hy_counts

    def best_iou(A,B):
        if A is None or B is None: return None
        r=[]
        for a in A:
            best=0.0
            for b in B:
                inter=np.logical_and(a,b).sum(); uni=np.logical_or(a,b).sum()
                if uni>0: best=max(best, inter/uni)
            r.append(round(float(best),3))
        return r
    out["frame0_pt_n"]=0 if pt_masks0 is None else len(pt_masks0)
    out["frame0_hy_n"]=0 if hy_masks0 is None else len(hy_masks0)
    ious=best_iou(pt_masks0,hy_masks0)
    if ious:
        out["frame0_mean_iou"]=round(float(np.mean(ious)),3)
        out["frame0_min_iou"]=round(float(np.min(ious)),3)
    print("E2E_JSON", json.dumps(out, default=str))
    with open(E2E+"/e2e_result.json","w") as f: json.dump(out,f,indent=1,default=str)
except Exception as e:
    traceback.print_exc(); print("FAIL", repr(e))
    try:
        with open(E2E+"/e2e_result.json","w") as f: json.dump({"FAIL":repr(e)},f)
    except Exception: pass
