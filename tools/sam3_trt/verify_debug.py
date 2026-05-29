import json, os, sys, traceback
import numpy as np, torch
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
PLAN = BENCH + "/sam3_enc_518_fix_fp32.plan"
out = {}
try:
    import tensorrt as trt
    os.add_dll_directory(r"C:/TensorRT/TensorRT-10.16.1.11/lib")
    os.add_dll_directory(r"C:/Users/kiyus/Desktop/github/shuttle-scope/shuttlescope/backend/.venv/Lib/site-packages/torch/lib")
    ref = np.load(BENCH + "/enc_ref.npz")
    x = torch.from_numpy(ref["sample"]).float().cuda().contiguous()
    TRT_LOGGER = trt.Logger(trt.Logger.WARNING)
    with open(PLAN, "rb") as f, trt.Runtime(TRT_LOGGER) as rt:
        engine = rt.deserialize_cuda_engine(f.read())
    ctx = engine.create_execution_context()
    ctx.set_input_shape("pixel_values", tuple(x.shape))
    ctx.set_tensor_address("pixel_values", x.data_ptr())
    bufs = {}
    onames = ["vision_features","fpn0","fpn1","fpn2","pos0","pos1","pos2"]
    for n in onames:
        t = torch.empty(tuple(ctx.get_tensor_shape(n)), dtype=torch.float32, device="cuda").contiguous()
        bufs[n]=t; ctx.set_tensor_address(n, t.data_ptr())
    ctx.execute_async_v3(torch.cuda.current_stream().cuda_stream); torch.cuda.synchronize()
    vf_trt = bufs["vision_features"].float().cpu().numpy()
    vf_ref = ref["vision_features"]
    out["vf_ref_shape"]=list(vf_ref.shape); out["vf_trt_shape"]=list(vf_trt.shape)
    out["vf_ref_mean"]=float(vf_ref.mean()); out["vf_trt_mean"]=float(vf_trt.mean())
    out["vf_ref_std"]=float(vf_ref.std()); out["vf_trt_std"]=float(vf_trt.std())
    out["vf_ref_first8"]=vf_ref.flatten()[:8].tolist()
    out["vf_trt_first8"]=vf_trt.flatten()[:8].tolist()
    # pos check (TRT pos vs ref? ref has no pos saved; skip)
    # Is it a spatial transpose? try comparing vf_ref vs vf_trt transposed on HxW
    a=vf_ref[0]; b=vf_trt[0]  # [256,37,37]
    def corr(u,v):
        u=u.flatten().astype(np.float64); v=v.flatten().astype(np.float64)
        return float(np.corrcoef(u,v)[0,1])
    out["corr_direct"]=round(corr(a,b),4)
    out["corr_HW_transposed"]=round(corr(a, b.transpose(0,2,1)),4)
    out["corr_per_channel_mean"]=round(float(np.mean([corr(a[c],b[c]) for c in range(256)])),4)
    # maybe channels permuted: corr of channel-mean maps
    print("DBG_JSON", json.dumps(out, default=str))
except Exception as e:
    traceback.print_exc(); print("DBG_FAIL", repr(e))
