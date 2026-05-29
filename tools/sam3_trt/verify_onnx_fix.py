import onnx, json, re, io, sys
from onnx import numpy_helper
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
p = BENCH + "/sam3_enc_518_fix.onnx"
m = onnx.load(p)
g = m.graph
prod = {o: n for n in g.node for o in n.output}
def cval(name):
    n = prod.get(name)
    if n and n.op_type == "Constant":
        for a in n.attribute:
            if a.name == "value":
                return numpy_helper.to_array(a.t).tolist()
    return None
root_re = re.compile(r"^/trunk/[A-Za-z]+(_\d+)?$")
roots = [f"{n.op_type}:{n.name}" for n in g.node if root_re.match(n.name)]
n_if = sum(1 for n in g.node if root_re.match(n.name) and n.op_type=="If")
tile = prod.get("/trunk/Tile_output_0")
res = {"root_nodes": roots, "root_If_count": n_if}
if tile:
    res["tile_repeats_const"] = cval(tile.input[1]) if len(tile.input)>1 else None
# ORT shape inference: capture warnings about Concat merge
try:
    import onnxruntime as ort
    so = ort.SessionOptions()
    so.log_severity_level = 1  # warnings
    # redirect: ORT logs to stderr; just try to create session (CPU) and see if it errors
    sess = ort.InferenceSession(p, so, providers=["CPUExecutionProvider"])
    res["ort_session_created"] = True
    res["ort_inputs"] = [i.name for i in sess.get_inputs()]
except Exception as e:
    res["ort_error"] = repr(e)[:300]
print("ONNXFIX_JSON", json.dumps(res, default=str)[:3000])
with open(BENCH + "/onnx_fix_check.json","w") as f:
    json.dump(res, f, indent=1, default=str)
