import onnx, json, re
from onnx import numpy_helper
BENCH = r"C:/Users/kiyus/Desktop/sam3_bench"
m = onnx.load(BENCH + "/sam3_enc_518_fix.onnx")
g = m.graph
prod = {o: n for n in g.node for o in n.output}
cons = {}
for n in g.node:
    for i in n.input:
        cons.setdefault(i, []).append(n)
def cval(name):
    n = prod.get(name)
    if n and n.op_type == "Constant":
        for a in n.attribute:
            if a.name == "value":
                arr = numpy_helper.to_array(a.t)
                return arr.tolist() if arr.size < 16 else f"sz{arr.size}"
    for ini in g.initializer:
        if ini.name == name:
            arr = numpy_helper.to_array(ini)
            return arr.tolist() if arr.size < 16 else f"init_sz{arr.size}"
    return None
# Inspect the two problem concats by output name
for tgt in ["/trunk/Concat_output_0", "/trunk/Concat_3_output_0"]:
    n = prod.get(tgt)
    print("====", tgt, "exists:", n is not None)
    if n:
        print(" op:", n.op_type, "axis:", [a.i for a in n.attribute if a.name=="axis"])
        for inp in n.input:
            p = prod.get(inp)
            print(f"   in={inp} prod={p.op_type+':'+p.name if p else None} const={cval(inp)}")
        print(" consumers:", [c.op_type+":"+c.name for c in cons.get(n.output[0], [])])
# root trunk node list + If count
root_re = re.compile(r"^/trunk/[A-Za-z]+(_\d+)?$")
roots = [f"{x.op_type}:{x.name}" for x in g.node if root_re.match(x.name)]
print("ROOTS:", json.dumps(roots))
