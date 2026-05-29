import json, os, traceback
import numpy as np
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
os.add_dll_directory(r"C:/TensorRT/TensorRT-10.16.1.11/lib")
os.add_dll_directory(r"C:/Users/kiyus/Desktop/github/shuttle-scope/shuttlescope/backend/.venv/Lib/site-packages/torch/lib")
out = {}
try:
    import onnx
    from onnx import helper
    m = onnx.load(BENCH + "/sam3_enc_518_fix.onnx")
    g = m.graph
    # pick a small set of probe tensors: output of each of the first few blocks + key ops
    # We add intermediate value_info tensors as graph outputs.
    existing_out = {o.name for o in g.output}
    # candidate intermediate names: block residual adds. Find Add nodes named /trunk/blocks.N/Add (last per block)
    probe_names = []
    # take output after block 0, 1, 2, and the rope-related concat in block0 attn
    wanted_substr = ["/trunk/blocks.0/Add_1", "/trunk/blocks.1/Add_1", "/trunk/blocks.0/attn/", "/trunk/patch_embed/", "/trunk/Add_output_0"]
    by_out = {}
    for n in g.node:
        for o in n.output:
            by_out[o] = n
    # collect a handful
    import re
    from onnx import TensorProto, shape_inference
    # infer dtypes/shapes
    im = shape_inference.infer_shapes(m)
    vi_dtype = {}
    for vi in list(im.graph.value_info) + list(im.graph.output):
        vi_dtype[vi.name] = vi.type.tensor_type.elem_type
    FLOAT = TensorProto.FLOAT
    def is_float(name):
        return vi_dtype.get(name) == FLOAT
    # the LayerNormalization outputs are reliable float per-block markers
    ln = sorted([o for o in by_out if re.match(r"^/trunk/blocks\.[0-5]/.*$", o) and by_out[o].op_type=="LayerNormalization" and is_float(o)])
    picks = []
    if is_float("/trunk/Add_output_0"):
        picks.append("/trunk/Add_output_0")
    # residual adds that are float
    fadd = sorted([o for o in by_out if re.match(r"^/trunk/blocks\.[0-3]/Add", o) and is_float(o)])
    picks += fadd
    picks += ln[:8]
    picks = list(dict.fromkeys(picks))[:14]
    out["probe_tensors"] = picks
    for p in picks:
        if p not in existing_out:
            g.output.append(helper.make_tensor_value_info(p, FLOAT, None))
    sub_path = BENCH + "/sam3_enc_fix_probed.onnx"
    onnx.save(m, sub_path, save_as_external_data=False)
    out["sub_saved"] = True

    ref = np.load(BENCH + "/enc_ref.npz")
    x = ref["sample"].astype(np.float32)

    import onnxruntime as ort
    so = ort.SessionOptions(); so.log_severity_level = 3
    sess = ort.InferenceSession(sub_path, so, providers=["CPUExecutionProvider"])
    onames = [o.name for o in sess.get_outputs()]
    ort_res = dict(zip(onames, sess.run(None, {"pixel_values": x})))

    # TRT: build engine from probed onnx (FP32) in-process
    import tensorrt as trt
    LOG = trt.Logger(trt.Logger.ERROR)
    builder = trt.Builder(LOG)
    network = builder.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
    parser = trt.OnnxParser(network, LOG)
    with open(sub_path, "rb") as f:
        ok = parser.parse(f.read())
    if not ok:
        out["parse_errors"] = [str(parser.get_error(i)) for i in range(parser.num_errors)]
    cfg = builder.create_builder_config()
    cfg.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 4 << 30)
    serialized = builder.build_serialized_network(network, cfg)
    rt = trt.Runtime(LOG)
    engine = rt.deserialize_cuda_engine(serialized)
    ctx = engine.create_execution_context()
    import torch
    xt = torch.from_numpy(x).cuda().contiguous()
    ctx.set_input_shape("pixel_values", tuple(xt.shape))
    ctx.set_tensor_address("pixel_values", xt.data_ptr())
    n_io = engine.num_io_tensors
    outs = {}
    for i in range(n_io):
        nm = engine.get_tensor_name(i)
        if engine.get_tensor_mode(nm) == trt.TensorIOMode.OUTPUT:
            shp = tuple(ctx.get_tensor_shape(nm))
            t = torch.empty(shp, dtype=torch.float32, device="cuda").contiguous()
            outs[nm] = t; ctx.set_tensor_address(nm, t.data_ptr())
    ctx.execute_async_v3(torch.cuda.current_stream().cuda_stream); torch.cuda.synchronize()

    cmp = {}
    for nm in outs:
        if nm in ort_res:
            a = ort_res[nm].astype(np.float64).flatten()
            b = outs[nm].float().cpu().numpy().astype(np.float64).flatten()
            if a.size == b.size and a.size > 1:
                corr = float(np.corrcoef(a, b)[0, 1])
                rel = float(np.abs(a - b).mean() / (np.abs(a).mean() + 1e-8))
                cmp[nm] = {"corr": round(corr, 4), "rel": round(rel, 4), "shape": list(outs[nm].shape)}
    out["layer_compare"] = cmp
    print("POLY_JSON", json.dumps(out, default=str))
    with open(BENCH + "/poly_bisect_result.json", "w") as f:
        json.dump(out, f, indent=1, default=str)
except Exception as e:
    traceback.print_exc(); print("POLY_FAIL", repr(e))
    with open(BENCH + "/poly_bisect_result.json", "w") as f:
        json.dump({"FAIL": repr(e), "partial": out}, f, default=str)
