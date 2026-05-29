import os, json, traceback
os.environ.setdefault("KMP_DUPLICATE_LIB_OK","TRUE")
import numpy as np
E2E = r"C:/Users/kiyus/Desktop/sam3_bench/e2e"
out = {}
try:
    import tensorrt as trt
    torchlib = r"C:/Users/kiyus/Desktop/github/shuttle-scope/shuttlescope/backend/.venv/Lib/site-packages/torch/lib"
    os.add_dll_directory(r"C:/TensorRT/TensorRT-10.16.1.11/lib")
    os.add_dll_directory(torchlib)
    import torch
    d = np.load(E2E+"/dec_inputs.npz"); ref = np.load(E2E+"/dec_ref.npz")
    LOG = trt.Logger(trt.Logger.WARNING)
    with open(E2E+"/sam3_dec_notactic.plan","rb") as f, trt.Runtime(LOG) as rt:
        eng = rt.deserialize_cuda_engine(f.read())
    ctx = eng.create_execution_context()
    in_names=["tgt","memory","pos","valid_ratios","memory_text","text_attention_mask"]
    out_names=["hs","ref_boxes","presence"]
    ins={}
    for n in in_names:
        arr = d[n]
        t = torch.tensor(arr, device="cuda")
        if t.dtype==torch.bool: t=t  # keep bool
        ins[n]=t.contiguous()
        ctx.set_input_shape(n, tuple(t.shape))
        ctx.set_tensor_address(n, ins[n].data_ptr())
    outs={}
    for n in out_names:
        shp=tuple(ctx.get_tensor_shape(n))
        t=torch.empty(shp, dtype=torch.float32, device="cuda").contiguous()
        outs[n]=t; ctx.set_tensor_address(n, t.data_ptr())
    ctx.execute_async_v3(torch.cuda.current_stream().cuda_stream); torch.cuda.synchronize()
    refs={"hs":ref["hs"],"ref_boxes":ref["ref"],"presence":ref["pres"]}
    for n in out_names:
        a=outs[n].cpu().numpy().astype(np.float64); b=refs[n].astype(np.float64)
        rel=np.abs(a-b).max()/(np.abs(b).max()+1e-9)
        corr=np.corrcoef(a.ravel(),b.ravel())[0,1]
        out[n]={"max_abs":float(np.abs(a-b).max()),"rel":float(rel),"corr":float(corr)}
    print("VTRT_JSON", json.dumps(out))
    with open(E2E+"/verify_dec_trt.json","w") as f: json.dump(out,f,indent=1)
except Exception as e:
    traceback.print_exc(); print("FAIL", repr(e))
