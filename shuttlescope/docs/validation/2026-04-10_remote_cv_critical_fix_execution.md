# Critical Remote / CV Fix Execution Record

## Date
2026-04-10

## Status
Code fixes applied. Build ✓. Tests (34) ✓. Execution validation pending real environment run.

---

## Root Causes Found

### A. Tunnel share shows LAN URL instead of public URL

**Root cause confirmed**: `rebaseUrl` in `useSessionSharing.ts` used `tunnelBase + u.hash` where `u.hash` is only the URL fragment (`#...`). The entire pathname was dropped.

- Input: `http://192.168.1.50:8765/coach/ABC123`
- tunnelBase: `https://xxx.ngrok-free.app`
- Bug output: `https://xxx.ngrok-free.app` (pathname lost)
- Fixed output: `https://xxx.ngrok-free.app/coach/ABC123`

All three URL types (coach, camera_sender, viewer) were affected. `SessionShareModal` renders whatever it receives — no independent rebasing.

### A2. ngrok URL never acquired (stdout was discarded)

**Root cause confirmed**: `_start_ngrok` used `stdout=subprocess.DEVNULL` and `shell=True`. ngrok v3 outputs the public URL (`Forwarding https://...`) to **stdout**. By discarding stdout, the code was entirely dependent on `localhost:4040/api/tunnels`. If that API was unavailable (port conflict, timing, ngrok config), the URL could never be acquired. The 30-second poll would time out and leave `running=true, url=null` indefinitely — UI stuck at "取得中..." forever.

### B. localfile AbortError spam

**Root cause confirmed**: `electron/main.ts` stream error handler fired unconditionally on any error including `AbortError`. An `AbortError` from the renderer cancelling a video range request (during seek, source swap, or unmount) is normal — not a real failure.

### C. TrackNet エラー（再試行）

**Root causes**:
1. `inf.load()` records no specific reason for failure — only generic `"モデルロードに失敗しました"` was stored
2. HTTP 503 from `POST /tracknet/batch` — catch block called `alert(t('tracknet.batch_error'))` discarding the server detail
3. Error shown only as `title` tooltip (hover required), not as visible text

### D. YOLO immediate error

Same pattern as C. `is_available()` can pass while `load()` fails in background. 503 error detail discarded in catch block. No visible error text.

---

## Files Changed

| File | Change |
|------|--------|
| `src/hooks/annotator/useSessionSharing.ts` | Fixed `rebaseUrl` to `pathname + search + hash`; added `tunnelPending` (running but no URL yet); added `tunnelLastError` (extracts failure line from `recent_log`); added `recent_log` to `TunnelData` type |
| `src/pages/AnnotatorPage.tsx` | `tunnelPending` → share button amber + blocks modal; tunnel button shows "取得中..."; `tunnelLastError` shown as red text near tunnel button; TrackNet/YOLO error buttons show visible truncated error text below |
| `electron/main.ts` | Suppress benign abort errors in `registerLocalFileProtocol` stream handlers (`ERR_STREAM_DESTROYED`, `AbortError`, message contains "abort") |
| `backend/tracknet/inference.py` | Added `_load_error: Optional[str]`; `get_load_error()` method; each backend attempt records specific failure reason |
| `backend/routers/tracknet.py` | `_run_batch` uses `inf.get_load_error()` for specific error message |
| `src/hooks/annotator/useCVJobs.ts` | Added `extractApiError()` helper; catch blocks now set error job state with actual server detail instead of generic alert |
| `backend/routers/tunnel.py` | **ngrok URL取得を全面的に再設計**: `stdout=subprocess.PIPE` + `--log=stdout --log-format=json` + `shell=False`; `_read_stdout_ngrok` スレッドで JSON 構造化ログから URL を抽出（主経路）; `_read_stderr_ngrok` でエラーログ記録; `_poll_ngrok_url` は補助経路として残しポート 4040〜4043 を試す; タイムアウト時に `_proc=None` にリセットしてUIを "取得中..." から解放; 全ログを `recent_log` に記録し UI から確認可能 |

---

## Architecture: ngrok URL acquisition (after fix)

```
tunnel_start()
  → _start_ngrok(): Popen([ngrok, http, --log=stdout, --log-format=json, --authtoken, TOKEN, PORT],
                           stdout=PIPE, stderr=PIPE, shell=False)
  → Thread: _read_stdout_ngrok()   ← 主経路: JSON から "url":"https://..." を抽出
  → Thread: _read_stderr_ngrok()   ← エラーログ記録
  → Thread: _poll_ngrok_url()      ← 補助経路: localhost:4040〜4043 API を試す

_read_stdout_ngrok():
  - 行ごとに読んで _stderr_lines に記録
  - _NGROK_JSON_URL_RE で "url":"https://..." を抽出 → _tunnel_url にセット
  - プロセス終了時に _proc=None にリセット

_poll_ngrok_url():
  - _tunnel_url が既にセットされていれば即終了
  - 40秒タイムアウト、ポート 4040〜4043 を順に試す
  - タイムアウト時: _proc=None にリセット + エラーログ記録
```

---

## Validation Steps Required (not yet executed)

### A. Tunnel URL correctness
```
1. Start ngrok from annotator tunnel button
2. Wait for button to show "ON" (not "取得中...")
3. Open share modal
4. Verify all URLs are https://xxx.ngrok-free.app/... (not 10.* / 192.168.*)
5. Verify QR codes encode the public URLs
6. Verify viewer URL path is /viewer/..., camera is /camera/...
7. Open from a different network device → confirm join works
```

### A2. ngrok URL acquisition
```
1. Press tunnel button
2. Confirm "取得中..." appears briefly (pending state)
3. Confirm URL appears within ~5 seconds (from stdout parsing)
4. Check recent_log in /api/tunnel/status for "[ngrok] 公開URL取得: https://..."
5. If failure: confirm error message appears in UI near tunnel button (not stuck forever)
```

### B. localfile abort suppression
```
1. Open match with local video
2. Play and seek rapidly
3. Switch matches and back
4. Confirm no "[localfile] Stream error: AbortError" in Electron console
5. Confirm video plays normally
```

### C. TrackNet error classification
```
1. Weights missing → POST 503 → error button shows server detail text visibly
2. Weights present, runtime missing → job error → button shows which backend failed
3. Full environment → run on real local video → artifact written, overlay renders
```

### D. YOLO error + readiness
```
1. No ultralytics + no ONNX → 503 → error text shown visibly below button
2. With ultralytics → run on real local video → completion, overlay visible
```

---

## What Remains Blocked (requires real environment)

- **TrackNet real completion**: needs tensorflow/onnxruntime/openvino AND weights installed AND real local badminton video
- **YOLO real completion**: needs `pip install ultralytics` (auto-downloads yolov8n.pt on first run)
- **End-to-end tunnel test**: needs ngrok running and remote device on different network
- **localfile playback human pass**: suppress fix applied but manual seek/swap/reenter validation needed
