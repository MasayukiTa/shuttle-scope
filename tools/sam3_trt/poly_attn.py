import json, os, traceback, re
import numpy as np
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
os.add_dll_directory(r"C:/TensorRT/TensorRT-10.16.1.11/lib")
os.add_dll_directory(r"C:/Users/kiyus/Desktop/github/shuttle-scope/shuttlescope/backend/.venv/Lib/site-packages/torch/lib")
out = {}
try:
    import onnx
    from onnx import helper, TensorProto, shape_inference
    m = onnx.load(BENCH + "/sam3_enc_518_fix.onnx")
    g = m.graph
    by_out = {o: n for n in g.node for o in n.output}
    im = shape_inference.infer_shapes(m)
    vi_dtype = {vi.name: vi.type.tensor_type.elem_type for vi in list(im.graph.value_info)+list(im.graph.output)}
    existing = {o.name for o in g.output}
    # all float tensors inside block0/attn, in graph order
    attn0 = [o for o in by_out if o.startswith("/trunk/blocks.0/attn/") and vi_dtype.get(o)==TensorProto.FLOAT]
    # keep a manageable spread: every other
    attn0 = attn0[::2][:12]
    # plus the block0 attn proj final (MatMul/Add producing block0/attn output) and block0/Add_2
    picks = attn0 + ["/trunk/blocks.0/Add_2_output_0"]
    picks = [p for p in dict.fromkeys(picks) if vi_dtype.get(p)==TensorProto.FLOAT or p=="/trunk/blocks.0/Add_2_output_0"]
    out["picks"] = picks
    for p in picks:
        if p not in existing:
            g.output.append(helper.make_tensor_value_info(p, TensorProto.FLOAT, None))
    sub = BENCH + "/sam3_attn_probed.onnx"
    onnx.save(m, sub, save_as_external_data=False)

    ref = np.load(BENCH + "/enc_ref.npz"); x = ref["sample"].astype(np.float32)
    import onnxruntime as ort
    so = ort.SessionOptions(); so.log_severity_level = 3
    sess = ort.InferenceSession(sub, so, providers=["CPUExecutionProvider"])
    onames = [o.name for o in sess.get_outputs()]
    ortr = dict(zip(onames, sess.run(None, {"pixel_values": x})))

    import tensorrt as trt, torch
    LOG = trt.Logger(trt.Logger.ERROR)
    b = trt.Builder(LOG); net = b.create_network(1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH))
    p = trt.OnnxParser(net, LOG)
    with open(sub, "rb") as f: p.parse(f.read())
    cfg = b.create_builder_config(); cfg.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, 4<<30)
    eng = trt.Runtime(LOG).deserialize_cuda_engine(b.build_serialized_network(net, cfg))
    ctx = eng.create_execution_context()
    xt = torch.from_numpy(x).cuda().contiguous(); ctx.set_input_shape("pixel_values", tuple(xt.shape)); ctx.set_tensor_address("pixel_values", xt.data_ptr())
    outs = {}
    for i in range(eng.num_io_tensors):
        nm = eng.get_tensor_name(i)
        if eng.get_tensor_mode(nm)==trt.TensorIOMode.OUTPUT:
            t = torch.empty(tuple(ctx.get_tensor_shape(nm)), dtype=torch.float32, device="cuda").contiguous()
            outs[nm]=t; ctx.set_tensor_address(nm, t.data_ptr())
    ctx.execute_async_v3(torch.cuda.current_stream().cuda_stream); torch.cuda.synchronize()
    cmp = {}
    for nm in outs:
        if nm in ortr:
            a = ortr[nm].astype(np.float64).flatten(); bb = outs[nm].float().cpu().numpy().astype(np.float64).flatten()
            if a.size==bb.size and a.size>1:
                cmp[nm] = {"corr": round(float(np.corrcoef(a,bb)[0,1]),4), "rel": round(float(np.abs(a-bb).mean()/(np.abs(a).mean()+1e-8)),4), "shape": list(outs[nm].shape)}
    out["cmp"] = cmp
    print("ATTN_JSON", json.dumps(out, default=str))
    with open(BENCH+"/poly_attn_result.json","w") as f: json.dump(out, f, indent=1, default=str)
except Exception as e:
    traceback.print_exc(); print("ATTN_FAIL", repr(e))
    with open(BENCH+"/poly_attn_result.json","w") as f: json.dump({"FAIL": repr(e), "partial": out}, f, default=str)
