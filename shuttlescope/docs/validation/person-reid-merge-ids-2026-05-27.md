# PersonTracker: ReID-based track_id merging (Task #40)

Date: 2026-05-27
Branch: `feat/person-tracker-reid`

## Summary

When ByteTracker ages out a track and a new detection enters the scene shortly
after, the same person normally receives a *new* `track_id`. Downstream
analytics (player labelling, condition timeline) treats them as separate
individuals which corrupts stats.

This change adds an **opt-in** post-processing layer in
`backend/cv/person_tracker.py` that uses the OSNet ReID embedding (already
computed by Phase 4) to rewrite the emitted `track_id` to the previous one when
the new track's appearance matches a recently-lost track within a cosine-sim
threshold.

The layer **never touches ByteTracker internal state** — it only maintains an
alias map and rewrites `TrackedPerson.track_id` at the boundary, mirroring how
`_reid_recover` is layered on top of the adjudicator output.

## Behaviour

- Default OFF. Existing callers see zero behavioural change.
- Enable via env `SS_PERSON_REID_MERGE_IDS=1`, or constructor `merge_ids=True`.
- Tunable:
  - `SS_PERSON_REID_MERGE_SIM` (default `0.85`) — cosine sim threshold.
  - `SS_PERSON_REID_MERGE_BUFFER` (default `32`) — LRU cap on lost track_ids.
- State is cleared on `reset_for_new_set()` (player identity continuity does
  not survive a set boundary because side-swap remaps court_id).

## Algorithm

1. Each `update()` call, after Tier 3 ReID recovery, embeds the bboxes of all
   current tracks (skipped if embedder is unavailable — silent no-op).
2. Tracks whose `track_id` disappeared since the previous frame have their
   last embedding pushed into an `OrderedDict` (LRU) keyed by *canonical*
   track_id, bounded by `merge_buffer_size`.
3. Newly-appearing `track_id`s (not seen in the previous frame, no existing
   alias) are matched greedily against the lost buffer by cosine similarity
   matrix; pairs with sim ≥ threshold receive an alias entry.
4. On emit, any track_id present in the alias map is rewritten in the output
   `TrackedPerson`.

## Trade-offs

- Greedy matching is O(M·L) per frame; M and L are tiny (≤4 doubles, buffer
  ≤32) so this is negligible compared to the embedder call.
- A second `embed_batch` is paid per frame when `_reid_recover` already
  embedded. This is acceptable for an opt-in path; future optimization can
  share the feature cache.
- False-merges (two different players above threshold) are bounded by the
  threshold; default `0.85` is conservative. Users in noisy environments can
  raise it.

## Files touched

- `shuttlescope/backend/cv/person_tracker.py`
  - new env constants `REID_MERGE_*`
  - new ctor params `merge_ids`, `merge_sim_threshold`, `merge_buffer_size`
  - new state: `_track_id_alias`, `_prev_raw_track_ids`,
    `_track_id_embedding`, `_lost_track_buffer`
  - new methods `_embed_tracks`, `_apply_track_id_merge`
  - `update()` wired to call merge step (court-on and court-off branches)
  - `reset_for_new_set()` clears merge state
- `shuttlescope/backend/tests/test_person_tracker_merge_ids.py` (new)

## Verification

- New unit suite (6 tests) passes locally with system python:
  - `test_merge_disabled_by_default_when_env_unset`
  - `test_merge_assigns_old_id_to_similar_new_track`
  - `test_merge_skipped_when_similarity_below_threshold`
  - `test_no_merge_for_continuing_track_id`
  - `test_disabled_when_merge_ids_flag_off`
  - `test_lost_buffer_lru_eviction`
- Existing `backend/tests/test_person_tracker.py` regressions: 33 passed,
  2 pre-existing failures unrelated to this change (FastAPI `on_startup`
  signature mismatch in `court_calibration` router import — same failure on
  branch HEAD prior to this commit).
- `update_batch()` was intentionally **not** wired in this pass; offline batch
  callers do not currently consume `track_id` continuity. If needed it can be
  added symmetrically in a follow-up.
