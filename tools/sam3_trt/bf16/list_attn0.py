import onnx
m = onnx.load(r"C:/Users/kiyus/Desktop/sam3_bench/sam3_enc_518_fix.onnx", load_external_data=False)
# print all node names under blocks.0/attn and any Sin/Cos/Mod (RoPE)
for n in m.graph.node:
    if "blocks.0/attn" in n.name:
        print(n.op_type, n.name)
print("=== RoPE-ish ops (first block) ===")
for n in m.graph.node:
    if n.op_type in ("Sin","Cos","Mod") and ("blocks.0" in n.name or "trunk" in n.name):
        print(n.op_type, n.name)
