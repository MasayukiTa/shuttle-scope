# Mid-rally save: replace_strokes + cross-device owner guard

Date: 2026-11-09
Branch: fix/midrally-save-v3
PR: #270 (supersedes closed PR #267)
Commits: 3d9044d (replace_strokes/final), 822ab06 (source_device_id guard)

## Problem

`/strokes/batch` (backend/routers/strokes.py) returns `already_saved` without
adding strokes when a rally with the same `(set_id, rally_num)` already exists
(`_batch_existing_response`). With mid-rally autosave, an autosaved partial rally
could therefore block the final confirm from persisting the full stroke set.

## Design

### 1. replace_strokes (confirm keeps all strokes)

The confirm save sends `replace_strokes=true`. `_batch_replace_existing` soft-
deletes the existing non-deleted strokes (`Stroke.deleted_at = now`) and re-
inserts the full set. `uq_strokes_rally_id_stroke_num_active` only covers
non-deleted rows, so a `db.flush()` between the soft delete and the re-insert
keeps the active-partial unique index from firing. `final=false` mid-saves do
not shrink an already-finalized rally.

### 2. Cross-device owner guard

Rally has no creator (`user_id`) column, so `source_device_id` (from
`settings.sync_device_id`, carried on `body.rally.source_device_id`,
max_length=100) is used as a proxy owner key:

- When the existing rally has a device id AND the incoming device id differs,
  the replace is rejected: the existing rally is returned as `already_saved`
  (no overwrite).
- When either side is unset, the replace is allowed on the basis of
  `require_match_scope` (same match / same user) passing in the caller
  (`_batch_save_rally_body`) -- the fixed-condition fallback (limit to the same
  match / same user when a reliable creator cannot be determined).
- On a permitted replace the incoming device id is stamped onto the rally
  (`existing.source_device_id = incoming_device`), so the first writer takes
  ownership.

### 3. syncStatus (PR #260)

The frontend stamps `settings.sync_device_id` onto the batch payload from both
confirm-save paths (AnnotatorPage.tsx, LiveInputPage.tsx via
`buildBatchPayload`). A successful response -- including `already_saved` for a
rejected cross-device replace -- clears the unsent count, so only truly-unsent
rallies remain counted; a rejected replace does not keep re-queuing.

## Files

- backend/routers/strokes.py: source_device_id field, `_batch_replace_existing`
  soft-delete+reinsert and device guard.
- src/utils/annotationPayload.ts: `source_device_id` on BatchRallyPayload,
  `sourceDeviceId` arg on buildBatchPayload.
- src/pages/AnnotatorPage.tsx, src/pages/LiveInputPage.tsx: pass
  `sourceDeviceId: appSettings.sync_device_id || undefined` on confirm save.

## Tests

- backend/tests/test_strokes_batch_midrally_replace.py (pytest): replace keeps
  all strokes; same-device replace allowed; different-device replace rejected
  as already_saved; unset device falls back to match scope.
- src/utils/__tests__/annotationPayload.midRally.test.ts (vitest): payload
  carries source_device_id when set and omits it when unset.
- scripts/ci_test_manifest.txt updated.

## CI

Security / lint / i18n / icon / scan-pr gates: pass. Build and Test
(ubuntu-latest, windows-latest): run on PR #270.
