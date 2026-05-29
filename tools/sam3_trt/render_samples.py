import os, glob, json, traceback
import numpy as np
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
OUT = BENCH + "/trt_samples"
os.makedirs(OUT, exist_ok=True)
try:
    from PIL import Image
    d = np.load(BENCH + "/masks_frame0.npz")
    pt = d["pt"]; hy = d["hy"]  # [N,H,W] bool
    frames = sorted(glob.glob(BENCH + "/frames/*.png"))
    img = np.array(Image.open(frames[0]).convert("RGB"))
    H, W = img.shape[:2]
    def overlay(base, masks, color):
        o = base.copy().astype(np.float32)
        for m in masks:
            mm = m
            if mm.shape != (H, W):
                mm = np.array(Image.fromarray(mm.astype(np.uint8)*255).resize((W, H))) > 127
            o[mm] = 0.5 * o[mm] + 0.5 * np.array(color, dtype=np.float32)
        return o.clip(0,255).astype(np.uint8)
    pt_img = overlay(img, pt, (0,255,0))     # PyTorch = green
    hy_img = overlay(img, hy, (255,80,0))    # TRT hybrid = orange
    # side by side with a white separator
    sep = np.full((H, 8, 3), 255, np.uint8)
    combo = np.concatenate([pt_img, sep, hy_img], axis=1)
    Image.fromarray(combo).save(OUT + "/frame0_pt_vs_trt.png")
    Image.fromarray(pt_img).save(OUT + "/frame0_pytorch.png")
    Image.fromarray(hy_img).save(OUT + "/frame0_trt_hybrid.png")
    # diff map: pixels where masks disagree (union over masks)
    def union(masks):
        u = np.zeros((H, W), bool)
        for m in masks:
            mm = m if m.shape==(H,W) else (np.array(Image.fromarray(m.astype(np.uint8)*255).resize((W,H)))>127)
            u |= mm
        return u
    up = union(pt); uh = union(hy)
    diff = np.zeros((H, W, 3), np.uint8)
    diff[up & uh] = (255,255,255)   # agree
    diff[up & ~uh] = (0,255,0)      # only PT
    diff[~up & uh] = (255,0,0)      # only TRT
    Image.fromarray(diff).save(OUT + "/frame0_diff.png")
    out = {"saved": os.listdir(OUT), "pt_masks": int(pt.shape[0]), "hy_masks": int(hy.shape[0]),
           "diff_only_pt_px": int((up & ~uh).sum()), "diff_only_hy_px": int((~up & uh).sum()),
           "agree_px": int((up & uh).sum())}
    print("RENDER_JSON", json.dumps(out, default=str))
    with open(BENCH + "/render_result.json", "w") as f:
        json.dump(out, f, indent=1, default=str)
except Exception as e:
    traceback.print_exc(); print("RENDER_FAIL", repr(e))
