"""Build a TrackEval seqmap file for DanceTrack val.

Format (MOT-challenge seqmap):
  name
  <seq1>
  <seq2>
  ...
"""
import os
VAL = r"C:\Users\kiyus\Desktop\dancetrack\val"
OUT = r"C:\Users\kiyus\Desktop\dancetrack\eval\dancetrack-val.seqmap"
seqs = sorted([d for d in os.listdir(VAL) if os.path.isdir(os.path.join(VAL, d))])
with open(OUT, "w") as f:
    f.write("name\n")
    for s in seqs:
        f.write(s + "\n")
print("wrote", OUT, "with", len(seqs), "seqs")
