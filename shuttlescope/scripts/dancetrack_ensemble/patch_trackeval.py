"""Patch deprecated numpy aliases (np.float/np.int/np.bool/np.object) in TrackEval
so it runs under numpy >= 1.24. Word-boundary safe (won't touch np.float64 etc.).
"""
import os, re
TE = r"C:\Users\kiyus\Desktop\dancetrack\eval\TrackEval\trackeval"
repls = [
    (re.compile(r"np\.float\b(?!\d)(?!ing)"), "float"),
    (re.compile(r"np\.int\b(?!\d)(?!p\b)(?!eger)(?!c\b)"), "int"),
    (re.compile(r"np\.bool\b(?!_)(?!8)"), "bool"),
    (re.compile(r"np\.object\b(?!_)"), "object"),
    (re.compile(r"np\.str\b(?!_)"), "str"),
]
n_files = 0
n_sub = 0
for dp, dn, fn in os.walk(TE):
    for f in fn:
        if not f.endswith(".py"):
            continue
        p = os.path.join(dp, f)
        src = open(p, encoding="utf-8").read()
        orig = src
        for rx, rep in repls:
            src, k = rx.subn(rep, src)
            n_sub += k
        if src != orig:
            open(p, "w", encoding="utf-8").write(src)
            n_files += 1
            print("patched", p)
print(f"files={n_files} subs={n_sub}")
