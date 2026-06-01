"""Coerce HybridSORT predict() score returns to python floats so the
'trk[:] = [...]' assignment (which expects scalars) works under numpy where
kf.x is shape (dim_x,1). Behavior-preserving (only flattens 1-elem arrays).
Also harden the trk[:] assignment to use float() on the bbox/score elements.
"""
import re
P = r"C:\Users\kiyus\Desktop\dancetrack\eval\HybridSORT\trackers\hybrid_sort_tracker\hybrid_sort.py"
s = open(P, encoding="utf-8").read()
orig = s

# 1) predict() returns: wrap np.clip(...) score terms with float(...)
s = s.replace(
    "return self.history[-1], np.clip(self.kf.x[3], self.args.track_thresh, 1.0), np.clip(self.confidence, 0.1, self.args.track_thresh)",
    "return self.history[-1], float(np.clip(self.kf.x[3], self.args.track_thresh, 1.0)), float(np.clip(self.confidence, 0.1, self.args.track_thresh))")
s = s.replace(
    "return self.history[-1], np.clip(self.kf.x[3], self.args.track_thresh, 1.0), np.clip(self.confidence - (self.confidence_pre - self.confidence), 0.1, self.args.track_thresh)",
    "return self.history[-1], float(np.clip(self.kf.x[3], self.args.track_thresh, 1.0)), float(np.clip(self.confidence - (self.confidence_pre - self.confidence), 0.1, self.args.track_thresh))")

# 2) harden the trk[:] assignment block: replace the try/except with explicit float coercion
old_block = """            pos, kalman_score, simple_score = self.trackers[t].predict()
            try:
                trk[:] = [pos[0][0], pos[0][1], pos[0][2], pos[0][3], kalman_score, simple_score[0]]
            except:
                trk[:] = [pos[0][0], pos[0][1], pos[0][2], pos[0][3], kalman_score, simple_score]"""
new_block = """            pos, kalman_score, simple_score = self.trackers[t].predict()
            ss = float(np.asarray(simple_score).ravel()[0])
            ks = float(np.asarray(kalman_score).ravel()[0])
            trk[:] = [float(pos[0][0]), float(pos[0][1]), float(pos[0][2]), float(pos[0][3]), ks, ss]"""
s = s.replace(old_block, new_block)

if s == orig:
    print("NO CHANGE - patterns not found!")
else:
    open(P, "w", encoding="utf-8").write(s)
    print("patched hybrid_sort.py")
