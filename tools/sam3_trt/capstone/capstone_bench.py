import os, json, time, glob, traceback
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
import numpy as np
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
CAP = BENCH + "/capstone"
IMG = 518
ENC_FP32 = BENCH + "/sam3_enc_518_fix_notactic.plan"
ENC_LINFP16 = BENCH + "/bf16/sam3_enc_linfp16.plan"
DEC_PLAN = BENCH + "/e2e/sam3_dec_notactic.plan"

out = {}
def sync():
    import torch; torch.cuda.synchronize()

try:
    import tensorrt as trt
    torchlib = r"C:/Users/kiyus/Desktop/github/shuttle-scope/shuttlescope/backend/.venv/Lib/site-packages/torch/lib"
    os.add_dll_directory(r"C:/TensorRT/TensorRT-10.16.1.11/lib")
    os.add_dll_directory(torchlib)
    import torch
    from ultralytics.models.sam.predict import SAM3SemanticPredictor

    LOG = trt.Logger(trt.Logger.WARNING)
    enc_out_names = ["vision_features", "fpn0", "fpn1", "fpn2", "pos0", "pos1", "pos2"]

    class EncRunner:
        """TRT encoder with persistent IO buffers + optional CUDA graph capture."""
        def __init__(self, plan, use_cuda_graph=True):
            with open(plan, "rb") as f, trt.Runtime(LOG) as rt:
                self.eng = rt.deserialize_cuda_engine(f.read())
            self.ctx = self.eng.create_execution_context()
            self.use_graph = use_cuda_graph
            self.graph = None
            self.inp = torch.empty((1, 3, IMG, IMG), dtype=torch.float32, device="cuda").contiguous()
            self.ctx.set_input_shape("pixel_values", tuple(self.inp.shape))
            self.ctx.set_tensor_address("pixel_values", self.inp.data_ptr())
            self.outs = {}
            for n in enc_out_names:
                t = torch.empty(tuple(self.ctx.get_tensor_shape(n)), dtype=torch.float32, device="cuda").contiguous()
                self.outs[n] = t
                self.ctx.set_tensor_address(n, t.data_ptr())
            self.stream = torch.cuda.Stream()
        def _enqueue(self):
            self.ctx.execute_async_v3(torch.cuda.current_stream().cuda_stream)
        def __call__(self, x):
            self.inp.copy_(x.contiguous().float())
            if self.use_graph:
                if self.graph is None:
                    # warmup enqueue on side stream then capture
                    with torch.cuda.stream(self.stream):
                        self._enqueue()
                    self.stream.synchronize()
                    self.graph = torch.cuda.CUDAGraph()
                    with torch.cuda.graph(self.graph, stream=self.stream):
                        self.ctx.execute_async_v3(self.stream.cuda_stream)
                self.graph.replay()
                torch.cuda.synchronize()
            else:
                self._enqueue()
                torch.cuda.synchronize()
            return self.outs

    # ---- decoder engine ----
    with open(DEC_PLAN, "rb") as f, trt.Runtime(LOG) as rt:
        dec_eng = rt.deserialize_cuda_engine(f.read())
    dec_ctx = dec_eng.create_execution_context()
    dec_in = ["tgt", "memory", "pos", "valid_ratios", "memory_text", "text_attention_mask"]
    dec_out = ["hs", "ref_boxes", "presence"]
    def dec_trt(tgt, memory, pos, valid_ratios, memory_text, text_attention_mask):
        feeds = {"tgt": tgt, "memory": memory, "pos": pos, "valid_ratios": valid_ratios,
                 "memory_text": memory_text, "text_attention_mask": text_attention_mask}
        for n in dec_in:
            t = feeds[n].contiguous(); dec_ctx.set_input_shape(n, tuple(t.shape))
            dec_ctx.set_tensor_address(n, t.data_ptr()); feeds[n] = t
        o = {}
        for n in dec_out:
            t = torch.empty(tuple(dec_ctx.get_tensor_shape(n)), dtype=torch.float32, device="cuda").contiguous()
            o[n] = t; dec_ctx.set_tensor_address(n, t.data_ptr())
        dec_ctx.execute_async_v3(torch.cuda.current_stream().cuda_stream); torch.cuda.synchronize()
        return o["hs"], o["ref_boxes"], o["presence"]

    pred = SAM3SemanticPredictor(overrides=dict(model=BENCH + "/sam3.pt", imgsz=IMG, conf=0.25, save=False, verbose=False, half=False))
    pred.setup_model(model=None)
    pm = pred.model.eval(); bb = pm.backbone; dec = pm.transformer.decoder
    frames = sorted(glob.glob(BENCH + "/frames/*.png"))
    with torch.no_grad():
        _ = pred(source=frames[0], text=["person"])

    def count_masks(res):
        try:
            m = res[0].masks; return 0 if m is None else int(m.data.shape[0])
        except Exception: return -1
    def get_masks(res):
        m = res[0].masks
        return None if m is None else m.data.detach().cpu().numpy().astype(bool)

    orig_fi = bb.forward_image
    orig_dec = dec.forward
    cur_enc = {"runner": None}
    def enc_hook(samples):
        b = cur_enc["runner"](samples)
        return {"vision_features": b["vision_features"],
                "vision_pos_enc": [b["pos0"], b["pos1"], b["pos2"]],
                "backbone_fpn": [b["fpn0"], b["fpn1"], b["fpn2"]]}
    def dec_hook(*a, **k):
        try:
            tgt = k["tgt"]; memory = k["memory"]; pos = k["pos"]; valid_ratios = k["valid_ratios"]
            memory_text = k["memory_text"]; tam = k["text_attention_mask"]
            if k.get("reference_boxes") is None and k.get("apply_dac") in (False, None) \
               and tuple(tgt.shape) == (200, 1, 256) and tuple(memory.shape) == (1369, 1, 256) \
               and tuple(memory_text.shape) == (32, 1, 256):
                hs, ref, pres = dec_trt(tgt, memory, pos, valid_ratios, memory_text, tam)
                return hs, ref, pres, None
        except Exception as ex:
            print("DEC_HOOK_FALLBACK", repr(ex))
        return orig_dec(*a, **k)

    def fps(ts):
        ts = ts[1:] if len(ts) > 1 else ts
        return round(1000.0 / np.median(ts), 2), round(float(np.median(ts)), 1)

    def best_iou(A, B):
        if A is None or B is None: return None
        r = []
        for a in A:
            best = 0.0
            for b in B:
                inter = np.logical_and(a, b).sum(); uni = np.logical_or(a, b).sum()
                if uni > 0: best = max(best, inter / uni)
            r.append(round(float(best), 3))
        return r

    def run_pass(name, enc_runner, use_dec_trt, capture_masks=False):
        bb.forward_image = orig_fi; dec.forward = orig_dec
        if enc_runner is not None:
            cur_enc["runner"] = enc_runner
            bb.forward_image = enc_hook
        if use_dec_trt:
            dec.forward = dec_hook
        torch.cuda.reset_peak_memory_stats()
        ts = []; counts = []; masks0 = None
        with torch.no_grad():
            for i, f in enumerate(frames):
                sync(); t0 = time.time(); res = pred(source=f, text=["person"]); sync()
                ts.append((time.time() - t0) * 1000); counts.append(count_masks(res))
                if i == 0 and capture_masks: masks0 = get_masks(res)
        vram = torch.cuda.max_memory_allocated() / 1e6
        bb.forward_image = orig_fi; dec.forward = orig_dec
        fp, ms = fps(ts)
        return dict(fps=fp, ms=ms, vram=round(vram, 1), counts=counts, masks0=masks0)

    # ---- per-stage encoder microbench (isolated TRT enc, graph vs no-graph) ----
    def enc_microbench(runner, n=50):
        x = torch.rand((1, 3, IMG, IMG), device="cuda")
        for _ in range(5): runner(x)
        sync(); t0 = time.time()
        for _ in range(n): runner(x)
        sync()
        return round((time.time() - t0) / n * 1000, 2)

    # PyTorch baseline (gold masks)
    r_pt = run_pass("pytorch", None, False, capture_masks=True)
    # FP32 enc TRT (no graph) + dec TRT  -> reproduces 4.27 hybrid, gold-quality
    enc_fp32_ng = EncRunner(ENC_FP32, use_cuda_graph=False)
    out["enc_fp32_micro_nograph_ms"] = enc_microbench(enc_fp32_ng)
    enc_fp32 = EncRunner(ENC_FP32, use_cuda_graph=True)
    out["enc_fp32_micro_graph_ms"] = enc_microbench(enc_fp32)
    r_fp32 = run_pass("fp32hybrid", enc_fp32, True, capture_masks=True)
    # linfp16 enc TRT (graph) + dec TRT  -> the fast integrated config
    enc_lin = EncRunner(ENC_LINFP16, use_cuda_graph=True)
    out["enc_lin_micro_graph_ms"] = enc_microbench(enc_lin)
    r_lin = run_pass("linfp16hybrid", enc_lin, True, capture_masks=True)

    out["pt"] = {k: r_pt[k] for k in ("fps", "ms", "vram", "counts")}
    out["fp32_encdec_graph"] = {k: r_fp32[k] for k in ("fps", "ms", "vram", "counts")}
    out["linfp16_encdec_graph"] = {k: r_lin[k] for k in ("fps", "ms", "vram", "counts")}

    iou_fp32 = best_iou(r_pt["masks0"], r_fp32["masks0"])
    iou_lin = best_iou(r_pt["masks0"], r_lin["masks0"])
    out["frame0_pt_n"] = 0 if r_pt["masks0"] is None else len(r_pt["masks0"])
    out["fp32_frame0_hy_n"] = 0 if r_fp32["masks0"] is None else len(r_fp32["masks0"])
    out["lin_frame0_hy_n"] = 0 if r_lin["masks0"] is None else len(r_lin["masks0"])
    if iou_fp32:
        out["fp32_frame0_mean_iou"] = round(float(np.mean(iou_fp32)), 3)
        out["fp32_frame0_min_iou"] = round(float(np.min(iou_fp32)), 3)
    if iou_lin:
        out["lin_frame0_mean_iou"] = round(float(np.mean(iou_lin)), 3)
        out["lin_frame0_min_iou"] = round(float(np.min(iou_lin)), 3)
        out["lin_frame0_iou_per_mask"] = iou_lin

    print("CAP_JSON", json.dumps(out, default=str))
    os.makedirs(CAP, exist_ok=True)
    with open(CAP + "/capstone_result.json", "w") as f:
        json.dump(out, f, indent=1, default=str)
except Exception as e:
    traceback.print_exc(); print("FAIL", repr(e))
    try:
        os.makedirs(CAP, exist_ok=True)
        with open(CAP + "/capstone_result.json", "w") as f:
            json.dump({"FAIL": repr(e)}, f)
    except Exception: pass
