import os, glob, traceback, json
os.environ.setdefault("KMP_DUPLICATE_LIB_OK","TRUE")
import torch, numpy as np
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
IMG = 518
out = {}
try:
    from ultralytics.models.sam.predict import SAM3SemanticPredictor
    pred = SAM3SemanticPredictor(overrides=dict(model=BENCH+"/sam3.pt", imgsz=IMG, conf=0.25, save=False, verbose=False, half=False))
    pred.setup_model(model=None)
    pm = pred.model.eval()
    dec = pm.transformer.decoder
    frames = sorted(glob.glob(BENCH + "/frames/*.png"))

    cap = {}
    orig = dec.forward
    def hook(*a, **k):
        # decoder.forward is called with kwargs from _run_decoder
        if not cap:
            cap.update(k)
            cap["_args"] = a
        return orig(*a, **k)
    dec.forward = hook
    with torch.no_grad():
        _ = pred(source=frames[0], text=["person"])
    dec.forward = orig

    def descr(x):
        if torch.is_tensor(x): return {"shape": list(x.shape), "dtype": str(x.dtype), "dev": str(x.device)}
        if x is None: return None
        if isinstance(x,(list,tuple)): return [descr(e) for e in x]
        if isinstance(x,bool): return x
        return type(x).__name__
    rec = {k: descr(v) for k,v in cap.items() if k != "_args"}
    rec["_n_positional"] = len(cap.get("_args", ()))
    out["decoder_inputs"] = rec
    # config attrs
    cfg = {}
    for attr in ["num_queries","num_o2m_queries","dac","box_refine","boxRPB","num_layers","d_model","use_normed_output_consistently","compile_mode","clamp_presence_logits"]:
        cfg[attr]=getattr(dec, attr, "MISSING")
    out["decoder_cfg"] = cfg
    # save the real input tensors for export + ref
    save = {}
    for k,v in cap.items():
        if torch.is_tensor(v): save[k]=v.detach().cpu().numpy()
    np.savez(BENCH+"/e2e/dec_inputs.npz", **save)
    out["saved_tensor_keys"]=list(save.keys())
    print("CAP_JSON", json.dumps(out, default=str))
    with open(BENCH+"/e2e/capture_dec.json","w") as f: json.dump(out,f,indent=1,default=str)
except Exception as e:
    traceback.print_exc(); print("FAIL", repr(e))
