import os, json, traceback
os.environ.setdefault("KMP_DUPLICATE_LIB_OK","TRUE")
import numpy as np
E2E = r"C:/Users/kiyus/Desktop/sam3_bench/e2e"
out = {}
try:
    import onnxruntime as ort
    d = np.load(E2E+"/dec_inputs.npz")
    ref = np.load(E2E+"/dec_ref.npz")
    sess = ort.InferenceSession(E2E+"/sam3_dec.onnx", providers=["CPUExecutionProvider"])
    feeds = {
        "tgt": d["tgt"], "memory": d["memory"], "pos": d["pos"],
        "valid_ratios": d["valid_ratios"], "memory_text": d["memory_text"],
        "text_attention_mask": d["text_attention_mask"],
    }
    o = sess.run(["hs","ref_boxes","presence"], feeds)
    names=["hs","ref_boxes","presence"]; refs=[ref["hs"],ref["ref"],ref["pres"]]
    for n,a,b in zip(names,o,refs):
        a=a.astype(np.float64); b=b.astype(np.float64)
        rel = np.abs(a-b).max()/(np.abs(b).max()+1e-9)
        corr = np.corrcoef(a.ravel(), b.ravel())[0,1]
        out[n]={"max_abs":float(np.abs(a-b).max()),"rel":float(rel),"corr":float(corr)}
    print("VONNX_JSON", json.dumps(out))
    with open(E2E+"/verify_dec_onnx.json","w") as f: json.dump(out,f,indent=1)
except Exception as e:
    traceback.print_exc(); print("FAIL", repr(e))
