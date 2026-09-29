import numpy as np, glob
fs = glob.glob(r"C:\Users\kiyus\Desktop\dancetrack\eval\dets\*.npy")
a = np.concatenate([np.load(f) for f in fs]) if fs else np.zeros((0, 6))
s = a[:, 5]
print("ndet", len(s), "nfiles", len(fs))
print("frac>=0.6", round(float((s >= 0.6).mean()), 3),
      "frac>=0.4", round(float((s >= 0.4).mean()), 3),
      "frac>=0.1", round(float((s >= 0.1).mean()), 3))
print("mean", round(float(s.mean()), 3), "median", round(float(np.median(s)), 3))
