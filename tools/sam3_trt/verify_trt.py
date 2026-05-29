import json, os, sys, traceback
import numpy as np, torch
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
PLAN = sys.argv[1] if len(sys.argv) > 1 else BENCH + "/sam3_enc_518_fix_fp16.plan"
TAG  = sys.argv[2] if len(sys.argv) > 2 else "fp16"
out = {"plan": PLAN, "tag": TAG}
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
    out_names = ["vision_features", "fpn0", "fpn1", "fpn2", "pos0", "pos1", "pos2"]
    ctx.set_input_shape("pixel_values", tuple(x.shape))
    ctx.set_tensor_address("pixel_values", x.data_ptr())
    bufs = {}
    for n in out_names:
        t = torch.empty(tuple(ctx.get_tensor_shape(n)), dtype=torch.float32, device="cuda").contiguous()
        bufs[n] = t; ctx.set_tensor_address(n, t.data_ptr())
    ctx.execute_async_v3(torch.cuda.current_stream().cuda_stream)
    torch.cuda.synchronize()

    def cmp(a_np, b_t):
        a = torch.from_numpy(a_np).float().cuda(); b = b_t.float()
        d = (a - b).abs()
        rel = (d.mean() / (a.abs().mean() + 1e-8)).item()
        relmax = (d.max() / (a.abs().max() + 1e-8)).item()
        af = a.flatten(); bf = b.flatten()
        corr = torch.corrcoef(torch.stack([af, bf]))[0, 1].item()
        return {"shape": list(a.shape), "rel_mean": round(rel, 5),
                "rel_max": round(relmax, 5), "corr": round(corr, 5),
                "max_abs": round(d.max().item(), 4)}
    comp = {}
    comp["vision_features"] = cmp(ref["vision_features"], bufs["vision_features"])
    comp["fpn0"] = cmp(ref["fpn0"], bufs["fpn0"])
    comp["fpn1"] = cmp(ref["fpn1"], bufs["fpn1"])
    comp["fpn2"] = cmp(ref["fpn2"], bufs["fpn2"])
    out["compare"] = comp
    worst = max(v["rel_mean"] for v in comp.values())
    out["worst_rel_mean"] = round(worst, 5)
    out["PASS"] = worst < 1e-2
    print("VERIFY_JSON", json.dumps(out, default=str))
    with open(BENCH + f"/verify_{TAG}_result.json", "w") as f:
        json.dump(out, f, indent=1, default=str)
except Exception as e:
    traceback.print_exc(); print("VERIFY_FAIL", repr(e))
    with open(BENCH + f"/verify_{TAG}_result.json", "w") as f:
        json.dump({"FAIL": repr(e)}, f)
