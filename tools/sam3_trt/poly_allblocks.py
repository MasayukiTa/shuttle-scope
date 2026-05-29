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
    vid = {vi.name: (vi.type.tensor_type.elem_type, tuple(d.dim_value for d in vi.type.tensor_type.shape.dim)) for vi in list(im.graph.value_info)+list(im.graph.output)}
    existing = {o.name for o in g.output}
    # last residual add of each block: shape [1,*,*,1024] or [1,*,1024]; pick Add nodes whose output is float 4D ending 1024
    cand = []
    for o in by_out:
        mt = re.match(r"^/trunk/blocks\.(\d+)/Add(_\d+)?_output_0$", o)
        if mt:
            dt, sh = vid.get(o, (0, ()))
            if dt == TensorProto.FLOAT and len(sh) >= 2 and sh[-1] == 1024:
                cand.append((int(mt.group(1)), o, sh))
    # for each block keep the one with the highest Add index (final residual)
    best = {}
    for bi, o, sh in cand:
        k = bi
        if k not in best or o > best[k][0]:
            best[k] = (o, sh)
    picks = [best[k][0] for k in sorted(best)]
    out["n_blocks_probed"] = len(picks)
    out["picks"] = picks
    for p in picks:
        if p not in existing:
            g.output.append(helper.make_tensor_value_info(p, TensorProto.FLOAT, None))
    sub = BENCH + "/sam3_allblk_probed.onnx"
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
    pp = trt.OnnxParser(net, LOG)
    with open(sub, "rb") as f: pp.parse(f.read())
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
                cmp[nm] = {"corr": round(float(np.corrcoef(a,bb)[0,1]),4), "rel": round(float(np.abs(a-bb).mean()/(np.abs(a).mean()+1e-8)),4)}
    out["cmp"] = cmp
    print("ALLBLK_JSON", json.dumps(out, default=str))
    with open(BENCH+"/poly_allblk_result.json","w") as f: json.dump(out, f, indent=1, default=str)
except Exception as e:
    traceback.print_exc(); print("ALLBLK_FAIL", repr(e))
    with open(BENCH+"/poly_allblk_result.json","w") as f: json.dump({"FAIL": repr(e), "partial": out}, f, default=str)
