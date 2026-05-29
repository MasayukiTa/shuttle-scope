import json, time, traceback, os, glob, math
import torch, torch.nn as nn
import torch.nn.functional as F
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
IMG = 518
out = {}
try:
    import ultralytics.models.sam.modules.utils as U

    def apply_rotary_enc_real(xq, xk, freqs_cis, repeat_freqs_k=False):
        fc_r = torch.view_as_real(freqs_cis)
        cos = fc_r[..., 0]; sin = fc_r[..., 1]
        def rope(x, c0, s0):
            x1 = x[..., 0::2]; x2 = x[..., 1::2]
            sh = [1] * (x.ndim - 2) + list(c0.shape)
            c = c0.view(*sh); s = s0.view(*sh)
            return torch.stack((x1 * c - x2 * s, x1 * s + x2 * c), dim=-1).flatten(-2)
        xq_out = rope(xq, cos, sin)
        if xk.shape[-2] == 0:
            return xq_out.type_as(xq), xk
        if repeat_freqs_k and (r := xk.shape[-2] // xq.shape[-2]) > 1:
            cos2 = cos.repeat(r, 1); sin2 = sin.repeat(r, 1)
        else:
            cos2, sin2 = cos, sin
        xk_out = rope(xk, cos2, sin2)
        return xq_out.type_as(xq), xk_out.type_as(xk)

    def get_abs_pos_static(abs_pos, has_cls_token, hw, retain_cls_token=False, tiling=False):
        h, w = 37, 37
        if has_cls_token:
            cls_pos = abs_pos[:, :1]; abs_pos = abs_pos[:, 1:]
        size = 24
        if size != h or size != w:
            new_abs_pos = abs_pos.reshape(1, size, size, -1).permute(0, 3, 1, 2)
            if tiling:
                rh = h // size + 1; rw = w // size + 1
                new_abs_pos = torch.cat([new_abs_pos] * rh, dim=2)
                new_abs_pos = torch.cat([new_abs_pos] * rw, dim=3)
                new_abs_pos = new_abs_pos[:, :, :h, :w]
            else:
                new_abs_pos = F.interpolate(new_abs_pos, size=(h, w), mode="bicubic", align_corners=False)
            if not retain_cls_token:
                return new_abs_pos.permute(0, 2, 3, 1)
            return torch.cat([cls_pos, new_abs_pos.permute(0,2,3,1).reshape(1,h*w,-1)], dim=1)
        if not retain_cls_token:
            return abs_pos.reshape(1, h, w, -1)
        return torch.cat([cls_pos, abs_pos], dim=1)

    from ultralytics.models.sam.predict import SAM3SemanticPredictor
    pred = SAM3SemanticPredictor(overrides=dict(model=BENCH+"/sam3.pt", imgsz=IMG, conf=0.25, save=False, verbose=False, half=False))
    pred.setup_model(model=None); pm = pred.model.eval()
    frames = sorted(glob.glob(BENCH + "/frames/*.png"))
    with torch.no_grad():
        _ = pred(source=frames[0], text=["person"])

    cap = {}; bb = pm.backbone; orig = bb.forward_image
    def hook(samples):
        if "sample" not in cap:
            cap["sample"] = samples.detach().float().cpu()
        return orig(samples)
    bb.forward_image = hook
    with torch.no_grad():
        _ = pred(source=frames[0], text=["person"])
    bb.forward_image = orig

    U.apply_rotary_enc = apply_rotary_enc_real
    import ultralytics.models.sam.sam3.vitdet as VD
    VD.apply_rotary_enc = apply_rotary_enc_real
    U.get_abs_pos = get_abs_pos_static
    VD.get_abs_pos = get_abs_pos_static

    pm_cpu = pm.float().cpu().eval(); bb = pm_cpu.backbone
    class EncWrap(nn.Module):
        def __init__(self, bb):
            super().__init__(); self.bb = bb
        def forward(self, x):
            o = self.bb.forward_image(x)
            return (o["vision_features"],) + tuple(o["backbone_fpn"]) + tuple(o["vision_pos_enc"])
    w = EncWrap(bb).eval()
    dummy = cap["sample"].cpu().float()

    onnx_path = BENCH + "/sam3_enc_518_dynamo.onnx"
    names = ["vision_features", "fpn0", "fpn1", "fpn2", "pos0", "pos1", "pos2"]
    t0 = time.time()
    with torch.no_grad():
        ep = torch.onnx.export(w, (dummy,), onnx_path,
            input_names=["pixel_values"], output_names=names,
            dynamo=True, optimize=True)
    out["export_s"] = round(time.time() - t0, 1)
    out["onnx_path"] = onnx_path
    out["onnx_mb"] = round(os.path.getsize(onnx_path) / 1e6, 1)
    print("DYNAMO_JSON", json.dumps(out, default=str))
    with open(BENCH + "/dynamo_export_result.json", "w") as f:
        json.dump(out, f, indent=1, default=str)
except Exception as e:
    traceback.print_exc(); print("DYNAMO_FAIL", repr(e))
    with open(BENCH + "/dynamo_export_result.json", "w") as f:
        json.dump({"FAIL": repr(e)}, f)
