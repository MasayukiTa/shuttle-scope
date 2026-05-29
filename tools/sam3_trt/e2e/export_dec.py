import os, glob, traceback, json
os.environ.setdefault("KMP_DUPLICATE_LIB_OK","TRUE")
import torch, numpy as np
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
E2E = BENCH + "/e2e"
IMG = 518
out = {}
try:
    from ultralytics.models.sam.predict import SAM3SemanticPredictor
    pred = SAM3SemanticPredictor(overrides=dict(model=BENCH+"/sam3.pt", imgsz=IMG, conf=0.25, save=False, verbose=False, half=False))
    pred.setup_model(model=None)
    pm = pred.model.eval()
    dec = pm.transformer.decoder
    frames = sorted(glob.glob(BENCH + "/frames/*.png"))
    # warm so caches (coord_cache etc) are built and freqs ready
    with torch.no_grad():
        _ = pred(source=frames[0], text=["person"])

    d = np.load(E2E + "/dec_inputs.npz")
    dev = "cuda"
    tgt = torch.tensor(d["tgt"], device=dev)
    memory = torch.tensor(d["memory"], device=dev)
    pos = torch.tensor(d["pos"], device=dev)
    spatial_shapes = torch.tensor(d["spatial_shapes"], device=dev)
    valid_ratios = torch.tensor(d["valid_ratios"], device=dev)
    memory_text = torch.tensor(d["memory_text"], device=dev)
    text_attention_mask = torch.tensor(d["text_attention_mask"], device=dev)

    class DecWrap(torch.nn.Module):
        def __init__(self, dec):
            super().__init__(); self.dec = dec
        def forward(self, tgt, memory, pos, valid_ratios, memory_text, text_attention_mask):
            hs, ref, presence, _ = self.dec(
                tgt=tgt, memory=memory, memory_key_padding_mask=None, pos=pos,
                reference_boxes=None, spatial_shapes=self._ss, valid_ratios=valid_ratios,
                tgt_mask=None, memory_text=memory_text, text_attention_mask=text_attention_mask,
                apply_dac=False,
            )
            if presence is None:
                presence = torch.zeros(1, device=hs.device)
            return hs, ref, presence
    wrap = DecWrap(dec).eval()
    wrap._ss = spatial_shapes  # int64 constant baked in (37x37)

    # PyTorch reference output
    with torch.no_grad():
        ref_hs, ref_ref, ref_pres = wrap(tgt, memory, pos, valid_ratios, memory_text, text_attention_mask)
    np.savez(E2E+"/dec_ref.npz",
             hs=ref_hs.detach().cpu().numpy(), ref=ref_ref.detach().cpu().numpy(),
             pres=ref_pres.detach().cpu().numpy())
    out["ref_shapes"]={"hs":list(ref_hs.shape),"ref":list(ref_ref.shape),"pres":list(ref_pres.shape)}

    # Export to ONNX on CPU, opset17, static shapes
    # clear device-bound coord caches so they rebuild on CPU
    dec.compilable_cord_cache = None
    dec.compilable_stored_size = None
    try: dec.coord_cache.clear()
    except Exception: pass
    wrap_cpu = DecWrap(dec.cpu()).eval()
    wrap_cpu._ss = spatial_shapes.cpu()
    inps = (tgt.cpu(), memory.cpu(), pos.cpu(), valid_ratios.cpu(), memory_text.cpu(), text_attention_mask.cpu())
    onnx_path = E2E + "/sam3_dec.onnx"
    with torch.no_grad():
        torch.onnx.export(
            wrap_cpu, inps, onnx_path,
            input_names=["tgt","memory","pos","valid_ratios","memory_text","text_attention_mask"],
            output_names=["hs","ref_boxes","presence"],
            opset_version=17, do_constant_folding=True, dynamo=False,
        )
    out["onnx_exported"]=True
    out["onnx_size_mb"]=round(os.path.getsize(onnx_path)/1e6,1)
    print("EXP_JSON", json.dumps(out, default=str))
    with open(E2E+"/export_dec.json","w") as f: json.dump(out,f,indent=1,default=str)
except Exception as e:
    traceback.print_exc(); print("FAIL", repr(e))
    with open(E2E+"/export_dec.json","w") as f: json.dump({"FAIL":repr(e)},f)
