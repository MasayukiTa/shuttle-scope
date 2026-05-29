import json, time, traceback, os, glob, math
import torch, torch.nn as nn
import torch.nn.functional as F
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
IMG = 518
out = {}
try:
    import ultralytics.models.sam.modules.utils as U

    # --- Real-arithmetic RoPE replacement (KEEP from prior working exporter) ---
    def apply_rotary_enc_real(xq, xk, freqs_cis, repeat_freqs_k=False):
        fc_r = torch.view_as_real(freqs_cis)
        cos = fc_r[..., 0]; sin = fc_r[..., 1]
        def rope(x):
            xr = x.reshape(*x.shape[:-1], -1, 2)
            x1 = xr[..., 0]; x2 = xr[..., 1]
            sh = [1] * (xr.ndim - 3) + list(cos.shape)
            c = cos.view(*sh); s = sin.view(*sh)
            return torch.stack((x1 * c - x2 * s, x1 * s + x2 * c), dim=-1).flatten(-2)
        xq_out = rope(xq)
        if xk.shape[-2] == 0:
            return xq_out.type_as(xq), xk
        if repeat_freqs_k and (r := xk.shape[-2] // xq.shape[-2]) > 1:
            cos2 = cos.repeat(r, 1); sin2 = sin.repeat(r, 1)
        else:
            cos2, sin2 = cos, sin
        def rope_k(x, c0, s0):
            xr = x.reshape(*x.shape[:-1], -1, 2)
            x1 = xr[..., 0]; x2 = xr[..., 1]
            sh = [1] * (xr.ndim - 3) + list(c0.shape)
            c = c0.view(*sh); s = s0.view(*sh)
            return torch.stack((x1 * c - x2 * s, x1 * s + x2 * c), dim=-1).flatten(-2)
        xk_out = rope_k(xk, cos2, sin2)
        return xq_out.type_as(xq), xk_out.type_as(xk)

    # --- STATIC get_abs_pos for fixed 518x518 (THE BUG FIX) ---
    # Original tiling path traced `[x // y + 1 for x,y in zip((h,w), shape)]` as
    # data-dependent If/Tile-repeats Concat -> mistraced 5-elt shape vector.
    # For 518x518: pretrain grid size=24 (577=1+24*24), target h=w=37, tile factor=2.
    def get_abs_pos_static(abs_pos, has_cls_token, hw, retain_cls_token=False, tiling=False):
        # hw arrives as TRACED symbolic ints (from x.shape[1:3]); force STATIC python
        # ints for fixed 518x518 -> 37x37 token grid so tile/slice are constant-folded.
        h, w = 37, 37
        if has_cls_token:
            cls_pos = abs_pos[:, :1]
            abs_pos = abs_pos[:, 1:]
        # pos_embed is a fixed parameter: 577 = 1 + 24*24 -> grid size 24 (static)
        size = 24
        if size != h or size != w:
            C = abs_pos.shape[-1]
            new_abs_pos = abs_pos.reshape(1, size, size, -1).permute(0, 3, 1, 2)
            if tiling:
                # static repeat factors computed from python ints, not traced shapes
                rh = h // size + 1
                rw = w // size + 1
                new_abs_pos = new_abs_pos.tile([1, 1, rh, rw])[:, :, :h, :w]
            else:
                new_abs_pos = F.interpolate(new_abs_pos, size=(h, w), mode="bicubic", align_corners=False)
            if not retain_cls_token:
                return new_abs_pos.permute(0, 2, 3, 1)
            else:
                return torch.cat([cls_pos, new_abs_pos.permute(0, 2, 3, 1).reshape(1, h * w, -1)], dim=1)
        else:
            if not retain_cls_token:
                return abs_pos.reshape(1, h, w, -1)
            else:
                return torch.cat([cls_pos, abs_pos], dim=1)

    from ultralytics.models.sam.predict import SAM3SemanticPredictor
    pred = SAM3SemanticPredictor(overrides=dict(model=BENCH+"/sam3.pt", imgsz=IMG, conf=0.25, save=False, verbose=False, half=False))
    pred.setup_model(model=None)
    pm = pred.model.eval()

    frames = sorted(glob.glob(BENCH + "/frames/*.png"))
    with torch.no_grad():
        _ = pred(source=frames[0], text=["person"])
    out["warm_ok"] = True

    cap = {}
    bb = pm.backbone
    orig = bb.forward_image
    def hook(samples):
        if "in" not in cap:
            cap["in"] = {"shape": list(samples.shape), "dtype": str(samples.dtype)}
            cap["sample"] = samples.detach().float().cpu()
        return orig(samples)
    bb.forward_image = hook
    with torch.no_grad():
        _ = pred(source=frames[0], text=["person"])
    bb.forward_image = orig
    out["enc_input"] = cap["in"]

    # Patch RoPE
    U.apply_rotary_enc = apply_rotary_enc_real
    import ultralytics.models.sam.sam3.vitdet as VD
    VD.apply_rotary_enc = apply_rotary_enc_real
    # Patch get_abs_pos in utils AND in vitdet's imported namespace (it does `from ...utils import get_abs_pos`)
    U.get_abs_pos = get_abs_pos_static
    if hasattr(VD, "get_abs_pos"):
        VD.get_abs_pos = get_abs_pos_static
    out["patched_get_abs_pos_in_vitdet"] = hasattr(VD, "get_abs_pos")

    pm_cpu = pm.float().cpu().eval()
    bb = pm_cpu.backbone

    class EncWrap(nn.Module):
        def __init__(self, bb):
            super().__init__(); self.bb = bb
        def forward(self, x):
            o = self.bb.forward_image(x)
            return (o["vision_features"],) + tuple(o["backbone_fpn"]) + tuple(o["vision_pos_enc"])

    w = EncWrap(bb).eval()
    dummy = cap["sample"].cpu().float()
    with torch.no_grad():
        ref = w(dummy)
    out["n_outputs"] = len(ref)
    out["out_shapes"] = [list(t.shape) for t in ref]

    onnx_path = BENCH + f"/sam3_enc_{IMG}_fix.onnx"
    names = ["vision_features", "fpn0", "fpn1", "fpn2", "pos0", "pos1", "pos2"]
    t0 = time.time()
    with torch.no_grad():
        torch.onnx.export(w, (dummy,), onnx_path,
            input_names=["pixel_values"], output_names=names,
            opset_version=17, do_constant_folding=True, dynamo=False)
    out["export_s"] = round(time.time() - t0, 1)
    out["onnx_path"] = onnx_path
    out["onnx_mb"] = round(os.path.getsize(onnx_path) / 1e6, 1)

    # Immediate ONNX shape-inference check for the prior error
    import onnx
    try:
        mm = onnx.load(onnx_path)
        onnx.checker.check_model(mm)
        out["onnx_check"] = "ok"
    except Exception as ce:
        out["onnx_check"] = repr(ce)[:300]

    print("EXPORT_JSON", json.dumps(out, default=str))
    with open(BENCH + "/fix_export_result.json", "w") as f:
        json.dump(out, f, indent=1, default=str)
except Exception as e:
    traceback.print_exc(); print("EXPORT_FAIL", repr(e))
    try:
        with open(BENCH + "/fix_export_result.json", "w") as f:
            json.dump({"FAIL": repr(e)}, f)
    except Exception: pass
