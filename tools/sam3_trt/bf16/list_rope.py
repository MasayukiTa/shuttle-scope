import onnx
m = onnx.load(r"C:/Users/kiyus/Desktop/sam3_bench/sam3_enc_518_fix.onnx", load_external_data=False)
# RoPE construction usually lives in position_encoding or block-level Sin/Cos. Find Sin/Cos and their parents.
for n in m.graph.node:
    if n.op_type in ("Sin","Cos"):
        print(n.op_type, n.name)
