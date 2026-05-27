# Person detection: Soft-NMS + short-track lifetime filter — 2026-05-27

## Change
- `backend/yolo/inference.py`: add Soft-NMS (Gaussian, Bodla et al. 2017) as an opt-in branch in the person NMS path.
  - Env `SS_PERSON_USE_SOFT_NMS=1` to enable (default OFF — greedy NMS unchanged).
  - Env `SS_PERSON_SOFT_NMS_SIGMA` (default 0.5) controls Gaussian width.
  - Helps the "attacker + blocker overlap at smash" case: overlapping candidates have their score decayed by IoU instead of being dropped, so the second player isn't suppressed outright.
- `backend/cv/person_tracker.py`: add short-track lifetime filter.
  - Env `SS_PERSON_TRACK_MIN_LIFETIME=N` (default 0 = disabled).
  - A track_id must accumulate N observed frames before being emitted. Suppresses single-frame FP and momentary spectator/passerby tracks.
  - Applied uniformly in both online (`update_tracks`) and batch (`update_tracks_batch`) paths, including the "no adjudicator" passthrough branch.

## Trade-off
- Soft-NMS: extra O(N²) score updates per frame; N is small for person (≤10) so cost negligible. If sigma is too aggressive, FP candidates near a real person can leak through MIN_CONF gate.
- Lifetime filter: introduces a fixed delay of (lifetime-1) frames before a true new player appears (e.g., entering court). At 30 fps, lifetime=5 → ~133 ms latency; lifetime=10 → ~333 ms.
- Both default OFF — no behaviour change for existing deployments.

## Files
- `shuttlescope/backend/yolo/inference.py` — `_get_soft_nms_config`, `_soft_nms`, dispatch in `_post_process_person`.
- `shuttlescope/backend/cv/person_tracker.py` — `_track_lifetime`, `_track_min_lifetime`, `_apply_lifetime_filter`.
- `shuttlescope/backend/tests/test_person_tracker.py` — new `TestTrackLifetimeFilter` class.

## Verification
- Unit tests: `TestTrackLifetimeFilter` (default OFF passthrough; lifetime=5 drops first 4 frames then emits; multi-track independent counters).
- Visual verification on prod video: deferred — user temporarily unable to do visual prune. Run smoke on `phase4_reid_on.mp4` (with v3 weights once trained) with each combination of envs:
  - baseline (both OFF)
  - `SS_PERSON_USE_SOFT_NMS=1`
  - `SS_PERSON_TRACK_MIN_LIFETIME=5`
  - both ON
