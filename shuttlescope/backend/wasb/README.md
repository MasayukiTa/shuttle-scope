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
