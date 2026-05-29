import os, json, time, glob, traceback
os.environ.setdefault("KMP_DUPLICATE_LIB_OK","TRUE")
import numpy as np
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"; E2E=BENCH+"/e2e"; IMG=518
out={}
def sync(): import torch; torch.cuda.synchronize()
try:
    import tensorrt as trt
    torchlib=r"C:/Users/kiyus/Desktop/github/shuttle-scope/shuttlescope/backend/.venv/Lib/site-packages/torch/lib"
    os.add_dll_directory(r"C:/TensorRT/TensorRT-10.16.1.11/lib"); os.add_dll_directory(torchlib)
    import torch
    from ultralytics.models.sam.predict import SAM3SemanticPredictor
    LOG=trt.Logger(trt.Logger.WARNING)
    with open(BENCH+"/sam3_enc_518_fix_notactic.plan","rb") as f, trt.Runtime(LOG) as rt:
        enc_eng=rt.deserialize_cuda_engine(f.read())
    enc_ctx=enc_eng.create_execution_context()
    enc_out_names=["vision_features","fpn0","fpn1","fpn2","pos0","pos1","pos2"]
    def enc_trt(x):
        x=x.contiguous().float(); enc_ctx.set_input_shape("pixel_values",tuple(x.shape))
        enc_ctx.set_tensor_address("pixel_values",x.data_ptr()); b={}
        for n in enc_out_names:
            t=torch.empty(tuple(enc_ctx.get_tensor_shape(n)),dtype=torch.float32,device="cuda").contiguous()
            b[n]=t; enc_ctx.set_tensor_address(n,t.data_ptr())
        enc_ctx.execute_async_v3(torch.cuda.current_stream().cuda_stream); torch.cuda.synchronize(); return b
    with open(E2E+"/sam3_dec_notactic.plan","rb") as f, trt.Runtime(LOG) as rt:
        dec_eng=rt.deserialize_cuda_engine(f.read())
    dec_ctx=dec_eng.create_execution_context()
    dec_in=["tgt","memory","pos","valid_ratios","memory_text","text_attention_mask"]; dec_out=["hs","ref_boxes","presence"]
    def dec_trt(tgt,memory,pos,vr,mt,tam):
        feeds={"tgt":tgt,"memory":memory,"pos":pos,"valid_ratios":vr,"memory_text":mt,"text_attention_mask":tam}
        for n in dec_in:
            t=feeds[n].contiguous(); dec_ctx.set_input_shape(n,tuple(t.shape)); dec_ctx.set_tensor_address(n,t.data_ptr()); feeds[n]=t
        o={}
        for n in dec_out:
            t=torch.empty(tuple(dec_ctx.get_tensor_shape(n)),dtype=torch.float32,device="cuda").contiguous()
            o[n]=t; dec_ctx.set_tensor_address(n,t.data_ptr())
        dec_ctx.execute_async_v3(torch.cuda.current_stream().cuda_stream); torch.cuda.synchronize()
        return o["hs"],o["ref_boxes"],o["presence"]

    pred=SAM3SemanticPredictor(overrides=dict(model=BENCH+"/sam3.pt",imgsz=IMG,conf=0.25,save=False,verbose=False,half=False))
    pred.setup_model(model=None); pm=pred.model.eval(); bb=pm.backbone; dec=pm.transformer.decoder
    frames=sorted(glob.glob(BENCH+"/frames/*.png"))
    with torch.no_grad(): _=pred(source=frames[0],text=["person"])

    def enc_hook(samples):
        b=enc_trt(samples)
        return {"vision_features":b["vision_features"],"vision_pos_enc":[b["pos0"],b["pos1"],b["pos2"]],"backbone_fpn":[b["fpn0"],b["fpn1"],b["fpn2"]]}
    odec=dec.forward
    def dec_hook(*a,**k):
        try:
            tgt=k["tgt"];memory=k["memory"]
            if k.get("reference_boxes") is None and tuple(tgt.shape)==(200,1,256) and tuple(memory.shape)==(1369,1,256):
                hs,ref,pres=dec_trt(tgt,memory,k["pos"],k["valid_ratios"],k["memory_text"],k["text_attention_mask"]); return hs,ref,pres,None
        except Exception: pass
        return odec(*a,**k)
    bb.forward_image=enc_hook; dec.forward=dec_hook

    T={}
    def wrap(obj,name,key):
        orig=getattr(obj,name)
        def w(*a,**k):
            sync();t0=time.time();r=orig(*a,**k);sync();T.setdefault(key,[]).append((time.time()-t0)*1000);return r
        setattr(obj,name,w); return orig
    wrap(bb,"forward_image","encoder_trt")
    wrap(pm,"_encode_prompt","geometry_encoder")
    wrap(pm,"_run_encoder","transformer_encoder")
    wrap(pm,"_run_decoder","decoder_trt")
    wrap(pm,"_run_segmentation_heads","seg_head")
    wrap(pm,"forward_grounding","forward_grounding")
    # also time predictor.preprocess and postprocess
    wrap(pred,"preprocess","preprocess")
    wrap(pred,"postprocess","postprocess")
    with torch.no_grad():
        T.clear(); tot=[]
        for f in frames[:8]:
            sync();t0=time.time();_=pred(source=f,text=["person"]);sync();tot.append((time.time()-t0)*1000)
    T["full_total"]=tot
    out["per_stage"]={k:{"med_ms":round(float(np.median(v)),2),"n":len(v)} for k,v in T.items()}
    print("PH_JSON", json.dumps(out,default=str))
    with open(E2E+"/prof_hybrid.json","w") as f: json.dump(out,f,indent=1,default=str)
except Exception as e:
    traceback.print_exc(); print("FAIL", repr(e))
