import onnx, sys, collections
m = onnx.load(r"C:/Users/kiyus/Desktop/sam3_bench/sam3_enc_518_fix.onnx", load_external_data=False)
g = m.graph
ctr = collections.Counter(n.op_type for n in g.node)
print("OPCOUNTS", dict(ctr))
# show ConvTranspose, and ops likely sensitive
for op in ["ConvTranspose","LayerNormalization","Softmax","ReduceMean","Pow","Sqrt"]:
    names = [n.name for n in g.node if n.op_type==op]
    print(f"--- {op} ({len(names)}) ---")
    for nm in names[:8]: print("  ", nm)
