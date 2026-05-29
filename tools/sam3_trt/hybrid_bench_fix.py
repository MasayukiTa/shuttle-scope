import json, time, glob, traceback, os
import numpy as np, torch
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
IMG = 518
out = {}
try:
    import tensorrt as trt
    torchlib = r"C:/Users/kiyus/Desktop/github/shuttle-scope/shuttlescope/backend/.venv/Lib/site-packages/torch/lib"
    os.add_dll_directory(r"C:/TensorRT/TensorRT-10.16.1.11/lib")
    os.add_dll_directory(torchlib)

    from ultralytics.models.sam.predict import SAM3SemanticPredictor

    # ---------- load TRT engine ----------
    TRT_LOGGER = trt.Logger(trt.Logger.WARNING)
    with open(BENCH + "/sam3_enc_518_fix_fp16.plan", "rb") as f, trt.Runtime(TRT_LOGGER) as rt:
        engine = rt.deserialize_cuda_engine(f.read())
    ctx = engine.create_execution_context()
    out_names = ["vision_features", "fpn0", "fpn1", "fpn2", "pos0", "pos1", "pos2"]

    def trt_infer(x):  # x: cuda fp32 [1,3,518,518]
        x = x.contiguous().float()
        ctx.set_input_shape("pixel_values", tuple(x.shape))
        bufs = {}
        ctx.set_tensor_address("pixel_values", x.data_ptr())
        for n in out_names:
            shp = tuple(ctx.get_tensor_shape(n))
            t = torch.empty(shp, dtype=torch.float32, device="cuda").contiguous()
            bufs[n] = t
            ctx.set_tensor_address(n, t.data_ptr())
        stream = torch.cuda.current_stream().cuda_stream
        ctx.execute_async_v3(stream)
        torch.cuda.synchronize()
        return bufs

    # ---------- setup predictor ----------
    pred = SAM3SemanticPredictor(overrides=dict(model=BENCH+"/sam3.pt", imgsz=IMG, conf=0.25, save=False, verbose=False, half=False))
    pred.setup_model(model=None)
    pm = pred.model.eval()
    bb = pm.backbone
    frames = sorted(glob.glob(BENCH + "/frames/*.png"))

    # warm to build freqs etc
    with torch.no_grad():
        _ = pred(source=frames[0], text=["person"])

    # ---------- PyTorch baseline run (capture masks) ----------
    def count_masks(res):
        try:
            m = res[0].masks
            return 0 if m is None else int(m.data.shape[0])
        except Exception:
            return -1
    def get_masks(res):
        m = res[0].masks
        if m is None: return None
        return m.data.detach().cpu().numpy().astype(bool)

    torch.cuda.reset_peak_memory_stats()
    pt_t=[]; pt_counts=[]; pt_masks0=None
    with torch.no_grad():
        for i,f in enumerate(frames):
            t0=time.time(); res=pred(source=f, text=["person"]); torch.cuda.synchronize()
            pt_t.append((time.time()-t0)*1000); pt_counts.append(count_masks(res))
            if i==0: pt_masks0=get_masks(res); pt_res0=res
    pt_vram = torch.cuda.max_memory_allocated()/1e6

    # ---------- HYBRID: patch forward_image to use TRT ----------
    orig_fi = bb.forward_image
    def hooked(samples):
        b = trt_infer(samples)
        # reconstruct the dict structure expected downstream (matches probe3 keys)
        d = {
            "vision_features": b["vision_features"],
            "vision_pos_enc": [b["pos0"], b["pos1"], b["pos2"]],
            "backbone_fpn": [b["fpn0"], b["fpn1"], b["fpn2"]],
        }
        return d
    bb.forward_image = hooked

    # check downstream consumes dict the same way; if it needs sam2_backbone_out, add it
    torch.cuda.reset_peak_memory_stats()
    hy_t=[]; hy_counts=[]; hy_masks0=None
    with torch.no_grad():
        for i,f in enumerate(frames):
            t0=time.time(); res=pred(source=f, text=["person"]); torch.cuda.synchronize()
            hy_t.append((time.time()-t0)*1000); hy_counts.append(count_masks(res))
            if i==0: hy_masks0=get_masks(res); hy_res0=res
    hy_vram = torch.cuda.max_memory_allocated()/1e6
    bb.forward_image = orig_fi

    def fps(ts):
        ts=ts[1:] if len(ts)>1 else ts  # drop first (warm)
        return round(1000.0/np.median(ts),2), round(float(np.median(ts)),1)

    out["pt_fps"], out["pt_ms_med"] = fps(pt_t)
    out["hy_fps"], out["hy_ms_med"] = fps(hy_t)
    out["pt_vram_mb"]=round(pt_vram,1); out["hy_vram_mb"]=round(hy_vram,1)
    out["pt_counts"]=pt_counts; out["hy_counts"]=hy_counts

    # ---------- mask correctness: best-match IoU between PT and hybrid masks on frame0 ----------
    def best_iou(A,B):
        if A is None or B is None: return None
        ious=[]
        for a in A:
            best=0.0
            for b in B:
                inter=np.logical_and(a,b).sum(); uni=np.logical_or(a,b).sum()
                if uni>0: best=max(best, inter/uni)
            ious.append(round(float(best),3))
        return ious
    out["frame0_pt_nmasks"]=0 if pt_masks0 is None else len(pt_masks0)
    out["frame0_hy_nmasks"]=0 if hy_masks0 is None else len(hy_masks0)
    ious = best_iou(pt_masks0, hy_masks0)
    out["frame0_mask_iou_per_pt_mask"]=ious
    if ious: out["frame0_mean_best_iou"]=round(float(np.mean(ious)),3); out["frame0_min_best_iou"]=round(float(np.min(ious)),3)

    # save arrays for visualization
    np.savez(BENCH+"/masks_frame0.npz",
             pt=(pt_masks0 if pt_masks0 is not None else np.zeros((0,1,1),bool)),
             hy=(hy_masks0 if hy_masks0 is not None else np.zeros((0,1,1),bool)))
    out["frame0_path"]=frames[0]
    print("HYBRID_JSON", json.dumps(out, default=str))
    with open(BENCH + "/hybrid_fix_result.json", "w") as f:
        json.dump(out, f, indent=1, default=str)
except Exception as e:
    traceback.print_exc(); print("HYBRID_FAIL", repr(e))
    try:
        with open(BENCH + "/hybrid_fix_result.json", "w") as f:
            json.dump({"FAIL": repr(e)}, f)
    except Exception: pass
