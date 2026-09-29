"""Parse RESULT lines from runall.log into a clean markdown-ish table + save."""
import re, sys, os
LOG = r"C:\Users\kiyus\Desktop\dancetrack\eval\logs\runall.log"
OUT = r"C:\Users\kiyus\Desktop\dancetrack\eval\RESULTS.txt"
rows = []
for line in open(LOG, encoding="utf-8", errors="ignore"):
    if line.startswith("RESULT "):
        d = {}
        parts = line.strip().split()
        name = parts[1]
        for kv in parts[2:]:
            if "=" in kv:
                k, v = kv.split("=")
                d[k] = v
        rows.append((name, d))
hdr = ["tracker", "HOTA", "DetA", "AssA", "MOTA", "IDF1", "IDSW", "Frag", "FP", "FN", "MT", "ML"]
lines = []
lines.append(" | ".join(hdr))
lines.append("-|-".join("-" * len(h) for h in hdr))
for name, d in rows:
    lines.append(" | ".join([name] + [d.get(k, "") for k in hdr[1:]]))
text = "\n".join(lines)
print(text)
open(OUT, "w", encoding="utf-8").write(text + "\n")
print("\nsaved", OUT)
