# 2026-05-24 — WASB-SBDT shuttle detection module

## Goal

Register the WASB-SBDT HRNet shuttle detector as an alternative to
TrackNetV3, selectable via the `SS_SHUTTLE_IMPL` env var. Pure
file-write change — the ONNX weight file is added in a follow-up commit.

## Files added / changed

- **added** `shuttlescope/backend/wasb/__init__.py`
- **added** `shuttlescope/backend/wasb/inference.py`
  - `WasbInference` runner with TrackNet-compatible API
    (`predict_frames(frames) -> list[dict]` with `frame_idx, zone,
    confidence, x_norm, y_norm, visible`).
  - EP cascade: TensorRT (fp16 + engine cache) → CUDA → CPU.
  - Reuses `backend.tracknet.inference._register_cuda_dll_dirs` and
    `_vram_based_max_batch` (per_sample_mb=120).
  - Graceful failure: returns `visible=False` placeholders when ONNX
    file is absent; `_gpu_load_error` set on GPU EP failure.
  - Model path resolution priority: `SS_WASB_ONNX` env > ctor arg >
    `backend/wasb/weights/wasb_badminton.onnx`.
- **added** `shuttlescope/backend/wasb/README.md`
  - MIT license note, BMVC2023 citation, re-export instructions,
    pointer to the benchmark doc.
- **added** `shuttlescope/backend/wasb/weights/.gitkeep`
  - Placeholder; actual ONNX (5.18 MB) ships in a separate commit.
- **changed** `shuttlescope/backend/cv/factory.py`
  - New `get_shuttle_detector()` reads `SS_SHUTTLE_IMPL`
    (default `tracknet` for backward compat).
  - WASB load failure falls back to `get_tracknet()` automatically.
  - `clear_cache()` now also resets the shuttle-detector cache.
  - **`get_tracknet()` is unchanged.**
- **added** `shuttlescope/backend/tests/test_wasb_inference.py`

## Test result

```
$ python -m pytest backend/tests/test_wasb_inference.py -q
.........                                                                [100%]
9 passed, 1 warning in 38.75s
```

## Backward compatibility

- `get_tracknet()` signature, return type, and resolution order are
  untouched.
- `SS_SHUTTLE_IMPL` defaults to `tracknet`; callers that haven't
  migrated to `get_shuttle_detector()` keep the existing behavior.
- WASB ONNX missing → factory silently falls back to TrackNet (logged
  at WARN level).

## TODO (follow-up commits)

1. Add the optimized `wasb_badminton.onnx` (5.18 MB) under
   `backend/wasb/weights/` after prod smoke test passes.
2. Switch pipeline / router callers from `get_tracknet()` to
   `get_shuttle_detector()` once parity vs TrackNetV3 is verified.
3. Once benchmarks are stable, consider flipping the default of
   `SS_SHUTTLE_IMPL` to `wasb`.
