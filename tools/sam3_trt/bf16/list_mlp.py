import onnx
m = onnx.load(r"C:/Users/kiyus/Desktop/sam3_bench/sam3_enc_518_fix.onnx", load_external_data=False)
mm = [n.name for n in m.graph.node if n.op_type=="MatMul"]
# categorize by suffix
import collections
cat = collections.Counter()
for nm in mm:
    if "qkv" in nm: cat["qkv"]+=1
    elif "/proj/" in nm: cat["proj"]+=1
    elif "mlp" in nm or "fc" in nm: cat["mlp"]+=1
    elif "/attn/MatMul" in nm: cat["attn_qkav"]+=1
    else: cat["other"]+=1
print(cat)
# show the non-attn matmuls (mlp/fc names) sample
print("--- block0 matmuls ---")
for nm in mm:
    if "blocks.0" in nm: print(nm)
