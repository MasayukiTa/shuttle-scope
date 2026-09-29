"""Vendored Hybrid-SORT association (appearance-free).

Sourced verbatim from ymzis69/HybridSORT (the same code validated on DanceTrack
val in scripts/dancetrack_ensemble: HOTA 46.2 / AssA 30.9, best association-only
non-ReID tracker we measured). Files:

  association.py            - weak-cue cost terms: Height-Modulated IoU (hmiou),
                              4-corner velocity direction consistency, and the
                              Track-Confidence-Modulated (TCM) score-difference term.
  kalmanfilter_score_new.py - score-augmented constant-velocity Kalman filter.
  hybrid_sort.py            - Hybrid_Sort tracker (TCM first step + BYTE second
                              step + OCR re-association). ReID disabled.

We use it appearance-free on purpose: badminton doubles partners wear identical
uniforms, so ReID embeddings are useless (proven). Only motion + box-geometry +
detection-confidence cues are used.

Heavy deps (filterpy for the Kalman, optional lap for assignment) are imported
lazily by the tracker so importing the ShuttleScope backend never requires them
unless SS_PERSON_TRACKER=hybrid is actually selected.
"""
