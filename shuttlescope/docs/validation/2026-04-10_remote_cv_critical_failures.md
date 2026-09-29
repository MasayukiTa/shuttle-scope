# Remote / CV Critical Failures Validation

## Date

2026-04-10

## Summary

Current remote sharing and CV execution are **not validated end to end**.

Recent real-use observations exposed failures that invalidate any “mostly done” interpretation of the feature set:

- `localfile` stream aborted with `AbortError`
- starting `ngrok` from the annotator and opening share still surfaced a `10.238.*` LAN URL instead of a public tunnel URL
- remote devices therefore could not join as intended
- `TrackNet` switched to `エラー（再試行）` within seconds after starting analysis
- `YOLO` immediately surfaced an analysis error banner

## Validation Result

### 1. Tunnel / share flow

Result: **failed**

The share flow cannot be treated as correct while a tunnel is running if the user is still shown a LAN URL.
This is a false-positive UX and blocks real remote use.

### 2. localfile playback stability

Result: **failed**

An abort surfaced from the local file stream path. Root cause is not yet validated and the flow cannot be treated as stable.

### 3. TrackNet real execution

Result: **failed**

TrackNet runtime is not considered validated until at least one real local badminton video completes from the actual annotator UI flow and produces a usable artifact.

### 4. YOLO real execution

Result: **failed**

YOLO runtime is not considered validated until readiness is truthful before execution and at least one real local video either:

- completes successfully, or
- is blocked with a concrete pre-run reason

## Interpretation

This is not a minor polish issue.
It is a trust issue:

- users are being shown misleading share state
- CV buttons exist but real execution is not yet proven
- validation quality has been below the standard required for these flows

## Required next step

Treat the following as a blocking recovery task:

- tunnel URL precedence correctness
- localfile abort root-cause fix
- TrackNet real-video completion
- YOLO truthful readiness and/or real completion

The detailed execution mandate is captured in:

- `private_docs/ShuttleScope_CRITICAL_REMOTE_AND_CV_FIX_MANDATE_v1.md`

## Status

Open / blocking
