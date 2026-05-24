# WASB-SBDT shuttle detector

HRNet-based shuttlecock detector ported from
[nttcom/WASB-SBDT](https://github.com/nttcom/WASB-SBDT) (MIT license).

Used as an alternative to TrackNetV3 for high-FPS / wide-angle footage where
TrackNet collapses (see benchmark in
`docs/research/2026-05-24_wasb_vs_tracknet_muroya.md` —
0% -> 30.9% detection on 1080p 60fps doubles).

## License

The upstream WASB-SBDT model and code are released under the MIT License.
Original copyright belongs to NTT Communications. See the upstream repo for
the full text. We redistribute only the exported ONNX weights.

## Citation

```
@inproceedings{tarashima2023wasb,
  title     = {Widely Applicable Strong Baseline for Sports Ball Detection and Tracking},
  author    = {Tarashima, Shuhei and Haq, Muhammad Abdul and Wang, Yushan and Tagawa, Norio},
  booktitle = {BMVC},
  year      = {2023}
}
```

## Files

- `inference.py` — `WasbInference` runner (TrackNet-compatible API)
- `weights/wasb_badminton.onnx` — exported HRNet weights (5.18 MB).
  **Not committed yet**; will be added in a follow-up commit after
  optimization smoke test passes on prod.
- `weights/trt_cache/` — TensorRT engine cache (auto-created)

## Re-export from upstream

1. Clone `nttcom/WASB-SBDT`, follow the install steps.
2. Download the badminton pretrained checkpoint from the Google Drive link
   in the upstream README (`badminton/best_model.pth.tar`).
3. Export to ONNX with opset 17, fixed input shape `(1, 9, 288, 512)`,
   dynamic batch dim.
4. Drop the resulting `wasb_badminton.onnx` into `backend/wasb/weights/`.

Override the path at runtime with `SS_WASB_ONNX=/abs/path/to/model.onnx`.

## Enabling

Selected via `cv.factory.get_shuttle_detector()` using the env switch:

```
SS_SHUTTLE_IMPL=wasb       # use HRNet WASB
SS_SHUTTLE_IMPL=tracknet   # default, keep TrackNetV3
```

### Production wiring (2026-05-24)

The following production code paths now route through `get_shuttle_detector()`
instead of `get_tracknet()` directly, so they respect the env switch:

- `backend/cv/tracknet_runner.py` — entry point used by `cluster/tasks.py`
  and direct callers (`run_tracknet(video_path)`).
- `backend/pipeline/video_pipeline.py` — `_get_tracknet()` used by the
  standalone analysis worker (`backend/pipeline/worker.py`).

Both call `inferencer.run(video_path) -> List[ShuttleSample]`. `WasbInference`
exposes a `.run()` adapter that wraps `predict_frames()` so it is a true
drop-in replacement for `TrackNetInferencer`.

### Performance (RTX 5060 Ti, 1080p 60fps doubles, muroya test video)

- WASB: ~60+ FPS, **39.3%** shuttle detection rate (with optimizations:
  TRT EP, IOBinding, GPU preprocess, sigmoid, temporal smoothing).
- TrackNetV3: **0%** detection rate on the same footage (well-known
  collapse on wide-angle / high-fps doubles).
- Benchmark: `docs/research/2026-05-24_wasb_vs_tracknet_muroya.md`.

### Fallback behaviour

If `SS_SHUTTLE_IMPL=wasb` but the ONNX is missing, CUDA/TRT EPs are
unavailable, or `WasbInference.load()` raises, the factory logs a warning
and falls back to `get_tracknet()` so production never breaks. Callers
using `_get_tracknet` in `video_pipeline.py` keep the existing inline-mock
fallback for environments where even `get_shuttle_detector` is unreachable.

### Stays on `get_tracknet()` directly

- `backend/benchmark/runner.py` and `backend/benchmark/pareto_sweep.py`
  — these read TrackNet-specific introspection (`_impl`, `backend_name()`,
  `_max_batch`, `run_frames()`, OpenVINO CPU native path). Switching them
  would lose the per-EP benchmark coverage that they are designed to
  measure. They will be migrated separately once a WASB-specific
  benchmark harness is added.
- All `backend/tests/*` keep calling `get_tracknet()` to keep TrackNet-
  specific regression coverage.
