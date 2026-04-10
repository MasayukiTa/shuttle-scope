# Critical Remote / CV Fix Execution Record

## Date
2026-04-10

## Status
Code fixes applied. Build ✓. Tests (34) ✓. Execution validation pending real video run.

---

## Root Causes Found

### A. Tunnel share shows LAN URL instead of public URL

**Root cause confirmed**: `rebaseUrl` in `useSessionSharing.ts` used `tunnelBase + u.hash` where `u.hash` is only the URL fragment (`#...`). The entire path was dropped.

Example of the bug:
- Input URL: `http://192.168.1.50:8765/coach/ABC123`
- tunnelBase: `https://xxx.ngrok.io`
- Bug output: `https://xxx.ngrok.io` (path `/coach/ABC123` lost entirely)
- Fixed output: `https://xxx.ngrok.io/coach/ABC123`

The `SessionShareModal` renders whatever URLs it receives as props — it has no rebasing logic of its own. All three URL types (coach, camera_sender, viewer) are passed through `rebaseUrl` in AnnotatorPage JSX. With the bug, they all resolved to just the tunnel root.

### B. localfile AbortError spam

**Root cause confirmed**: `electron/main.ts` `registerLocalFileProtocol()` — when a video range request is cancelled by the browser (normal during seek, source swap, or unmount), the underlying Node.js `ReadableStream` fires an `error` event. The handler called `console.error('[localfile] Stream error:', err)` unconditionally. An `AbortError` from browser request cancellation is a normal part of video playback; it does not indicate a real failure.

### C. TrackNet エラー（再試行）

**Root cause**: Two failure modes:
1. If weights are present but runtime dependencies (tensorflow, onnxruntime, openvino) are not installed, `inf.load()` returns False in the background job. The error stored was the generic string `"モデルロードに失敗しました"` without specifying which backend failed and why.
2. The frontend error button showed the error message only as a `title` (tooltip requiring hover), not as visible text.
3. When the HTTP POST for batch start itself returns 503 (weights missing), the `catch` block previously called `alert(t('tracknet.batch_error'))` discarding the actual server reason.

### D. YOLO immediate error

**Root cause**: Same pattern as TrackNet. `is_available()` may pass (e.g., when ultralytics is importable), but actual `load()` in the background thread fails. Or the POST returns 503 when neither ultralytics nor ONNX weights are present. In both cases the user saw only a generic error with no actionable detail.

---

## Files Changed

| File | Change |
|------|--------|
| `src/hooks/annotator/useSessionSharing.ts` | Fixed `rebaseUrl` to use `pathname + search + hash`; added `tunnelPending` state (tunnel running but URL not yet fetched) |
| `src/pages/AnnotatorPage.tsx` | Added `tunnelPending` destructuring; tunnel button shows "取得中..." when pending; share button shows amber color + blocks modal open when pending; TrackNet + YOLO error buttons now show visible truncated error text below button |
| `electron/main.ts` | `registerLocalFileProtocol()` — suppress benign abort errors (`ERR_STREAM_DESTROYED`, `AbortError`, message contains "abort") in stream error handlers; real errors still logged |
| `backend/tracknet/inference.py` | Added `_load_error: Optional[str]` field; `get_load_error()` method; each backend attempt now records a specific failure reason; `load()` sets `_load_error` with tried-backend list on failure |
| `backend/routers/tracknet.py` | `_run_batch` uses `inf.get_load_error()` instead of generic string |
| `src/hooks/annotator/useCVJobs.ts` | Added `extractApiError()` helper; `handleTracknetBatch` and `handleYoloBatch` catch blocks now set error job state with the actual server detail, not generic alert |

---

## Validation Steps Required (not yet executed — requires real environment)

### A. Tunnel URL correctness
```
1. Start ngrok from annotator tunnel button
2. Wait for tunnelBase to resolve (button shows "ON" not "取得中...")
3. Open share modal
4. Verify all displayed URLs start with https://xxx.ngrok.io/ (not 10.* or 192.168.*)
5. Verify QR codes encode the public URLs
6. Verify viewer URL is /viewer/... path (not /camera/...)
```

### B. localfile abort suppression
```
1. Open a match with a local video
2. Play and seek rapidly multiple times
3. Switch to another match and back
4. Confirm no "[localfile] Stream error: AbortError" in Electron console
5. Confirm video still plays normally after seek
```

### C. TrackNet error classification
```
1. If weights missing: confirm POST /tracknet/batch returns 503 with detail text
   → error button shows specific reason (not generic)
2. If weights present but runtime missing: confirm job transitions to error
   → error button shows which backend was tried and why it failed
3. If everything installed: run on real local video
   → confirm progress advances, completes, artifact is written
```

### D. YOLO error + readiness
```
1. Without ultralytics and without ONNX: POST /yolo/batch returns 503
   → error state shows the server reason text visibly below button
2. With ultralytics installed but bad weights: load() fails
   → error stored in job, shown visibly
3. With ultralytics working: run on real local video
   → confirm progress, completion, overlay visible
```

---

## What Remains Blocked

- **TrackNet real completion**: Cannot validate without weights installed and a real local badminton video to test against. The code path is correct but the runtime environment requires: tensorflow OR onnxruntime OR openvino installed, AND weights present.

- **YOLO real completion**: Cannot validate without ultralytics installed. With `pip install ultralytics`, `yolov8n.pt` downloads automatically on first run. The inference code is correct.

- **End-to-end tunnel test**: Requires ngrok running and a remote device on a different network to verify the public URL is truly reachable.

---

## Remaining Caveat

The error display improvements (visible error text below buttons) only appear in the compact header toolbar. For a full failure investigation, the user must check the Electron dev console for Python backend logs. A dedicated CV status page or expanded error panel would provide better diagnostics — this is out of scope for this fix but noted for future work.
