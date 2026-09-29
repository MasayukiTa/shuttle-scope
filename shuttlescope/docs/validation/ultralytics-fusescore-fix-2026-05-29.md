# ultralytics fuse_score crash fix (2026-05-29)

## Symptom
Person tracking pipeline crashed in ultralytics `.track()` when
`SS_YOLO_BYTETRACK` was unset/1. Worked around earlier by `SS_YOLO_BYTETRACK=0`
(standalone ByteTracker). ultralytics installed: 8.4.38.

## Traceback (reproduced, crashes on frame 0)
```
File ".../ultralytics/trackers/byte_tracker.py", line 412, in get_dists
    if self.args.fuse_score:
File ".../ultralytics/utils/__init__.py", line 328, in __getattr__
    raise AttributeError(...)
AttributeError: 'IterableSimpleNamespace' object has no attribute 'fuse_score'.
```

## Root cause
ultralytics 8.4.x loads the tracker yaml WITHOUT merging defaults:
`ultralytics/trackers/track.py` -> `cfg = IterableSimpleNamespace(**YAML.load(tracker))`.
Only keys present in our `backend/yolo/bytetrack.yaml` become attributes.
Our yaml was missing `fuse_score`, which `BYTETracker.get_dists()` reads
(byte_tracker.py:342 and :412). So `.track()` raises AttributeError as soon
as `get_dists` runs (frame 0). Not an ultralytics bug and not our call pattern
-- our tracker config was incomplete for this ultralytics version.

## Fix (minimal, config-level)
Added `fuse_score: true` (+ explanatory comment) to
`backend/yolo/bytetrack.yaml`. No ultralytics monkeypatch, no code change in
`inference.py`, no version change. `fuse_score: true` matches ultralytics'
shipped default and stabilizes weak detections.

## Repro / verification
- Repro: `model.track(frame, classes=[0], persist=True, tracker=bytetrack.yaml)`
  over 40 frames of test video `fd425688-...mp4` with 1-class model
  `yolov8n_v2_finetuned_dyn.onnx`. Before: crash frame 0. After: 40 frames
  tracked, no crash, track_id assigned (boxes 7-8/frame).
- Regression test: `backend/tests/test_bytetrack_tracker_config.py` (3 tests,
  GPU-free via `importorskip`): yaml has fuse_score; BYTETracker.update over
  two 1-det frames (exercises fuse_score path); empty-detection frame no-crash.
  Result: 3 passed.

## Recommendation
None blocking. Optional: keep tracker yaml fields in sync with ultralytics
defaults on future ultralytics upgrades (the no-merge load means any newly
required field must be added here).
