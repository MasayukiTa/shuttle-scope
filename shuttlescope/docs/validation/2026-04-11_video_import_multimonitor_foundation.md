# 2026-04-11 Video Import / Multi-Monitor / Court Grid Foundation

## Summary

This phase added a practical foundation for post-match local video processing,
second-monitor playback continuity, and court-grid calibration scaffolding.

The implementation is valid as a foundation layer and passes the current test
suite, but it is not the final operational state yet.

In particular:

- second-monitor playback now preserves time and paused state
- local match exit can enqueue background video processing
- TrackNet / YOLO status reporting is more truthful and more GPU-oriented
- court-grid overlay and calibration backend routes now exist
- however, the frontend court-grid flow still stores calibration locally and
  does not yet push calibration to the backend API

## Implemented

### 1. Background video import pipeline

Added:

- `backend/routers/video_import.py`
- router registration in `backend/main.py`

Capabilities:

- `POST /api/video_import/path`
- `GET /api/video_import/{job_id}`
- `GET /api/video_import/list`
- sequential TrackNet -> YOLO processing
- per-phase progress and backend reporting
- YOLO artifact persistence into `MatchCVArtifact`

Current trigger:

- `AnnotatorPage.tsx` now posts the local video path on leave / exception flow
  so post-match processing can begin automatically for local files.

### 2. Multi-monitor playback continuity

Updated:

- `electron/main.ts`
- `electron/preload.ts`
- `src/electron.d.ts`
- `src/pages/VideoOnlyPage.tsx`

Behavior change:

- opening the separate video window now passes current playback time
- paused state is preserved
- local files in the separate window use a plain `<video>` player with controls
- streaming URLs still use `WebViewPlayer`

This makes the external-monitor workflow materially closer to a real match-day
operator setup.

### 3. Annotator video pane and in-match UX

Updated:

- `src/components/annotator/AnnotatorVideoPane.tsx`
- `src/pages/AnnotatorPage.tsx`
- `src/store/annotationStore.ts`

Behavior change:

- court-grid overlay can be toggled from the annotator
- when video source mode is `none`, the page explicitly indicates playback is on
  another monitor
- doubles hitter selection is now explicit for all four players
- `setHitter()` now synchronizes `currentPlayer`, fixing team-side drift bugs

### 4. Court calibration foundation

Added:

- `backend/routers/court_calibration.py`
- `src/components/video/CourtGridOverlay.tsx`
- router registration in `backend/main.py`

Backend side:

- stores homography / inverse / ROI polygon / net alignment summary in
  `MatchCVArtifact`
- exposes save/load endpoints

Frontend side:

- supports 6-point calibration UI
- supports re-calibration and point dragging
- overlays a perspective-aware court grid

Important current limitation:

- frontend currently persists calibration only in localStorage
- backend calibration API is not yet invoked by the UI

### 5. TrackNet / YOLO runtime loading improvements

Updated:

- `backend/tracknet/inference.py`
- `backend/routers/tracknet.py`
- `backend/yolo/inference.py`

TrackNet improvements:

- truthful missing-weight error message
- better backend fallback diagnostics
- OpenVINO GPU-first preference with CPU fallback
- `status` endpoint now attempts load and returns `load_error`

YOLO improvements:

- OpenVINO direct API path added
- GPU-first backend preference when available
- better staged fallback:
  - OpenVINO
  - ultralytics
  - ONNX Runtime

### 6. Match creation UX cleanup

Updated:

- `src/pages/MatchListPage.tsx`

Behavior change:

- richer player search / provisional creation flow
- better doubles entry layout
- stronger opponent-team identification flow

## Validation Run

Executed:

- `npm run build`
- `npx vitest run --config vitest.config.ts`
- `.\backend\.venv\Scripts\python -m pytest backend/tests/ -q`

Observed:

- build: success
- vitest: `84 passed`
- pytest: `469 passed, 1 warning`

Known warning:

- existing Pydantic deprecation warning in `backend/config.py`

## Honest Status

This phase should be treated as:

- foundation complete for video-import and multi-monitor continuity
- runtime backend loading improved
- court-grid UX scaffolded

This phase should **not** yet be treated as:

- fully validated real-video CV workflow
- fully integrated backend-persisted court calibration workflow
- final production-grade post-match automation

## Immediate Remaining Gaps

- wire `CourtGridOverlay` to save/load calibration through
  `/api/matches/{match_id}/court_calibration`
- validate `video_import` on a real local badminton file end-to-end
- verify TrackNet / YOLO artifact quality from the imported pipeline
- confirm external-monitor workflow in real annotation usage
