# person_tracker_native_ext .pyd load/run fix (2026-05-29)

Task #37. Goal: make `person_tracker_native_ext.pyd` importable inside a Python
process (that imports torch) and run a batch detection, printing an fps number.

## Confirmed root cause (not the hypothesised cuDNN ABI conflict)

The brief suspected a cuDNN 9.x ABI conflict between torch's bundled cuDNN and
the cuDNN ORT 1.24.4 expects. That was **not** the actual failure.

Empirical reproduction showed two chained failures, both caused by **ORT GPU
provider DLLs not being on the DLL search path next to the binary**:

1. At session create:
   `Error loading "...\build\Release\onnxruntime_providers_shared.dll" which is
   missing. (Error 126)` — both the TensorRT EP and the CUDA EP failed to load,
   because ORT dynamically loads `onnxruntime_providers_shared.dll`,
   `onnxruntime_providers_tensorrt.dll` and `onnxruntime_providers_cuda.dll` at
   runtime and they were absent from the output dir.
2. ORT then silently fell back to the **CPU EP** (`trt=0`). The detector binds a
   CUDA device input tensor to that CPU session, so inference died with:
   `RuntimeError: There's no data transfer registered for copying tensors from
   Device:[DeviceType:1 ...] to Device:[DeviceType:0 ...]`.

The standalone `detector_test.exe` exhibited the **identical** error when run
from its build dir (exit 9) — confirming the cause is the missing provider DLLs,
not a Python/torch DLL-order interaction. The previously reported "628 fps .exe"
had simply been run from an environment where ORT's lib dir was on PATH.

cuDNN is irrelevant here: this machine has no standalone cuDNN install, the model
runs via the **TensorRT EP** (TensorRT 10.16.1.11), and once the provider DLLs
resolve, TRT EP loads cleanly even with torch imported first.

## The fix

`shuttlescope/backend/cv/person_tracker_native/CMakeLists.txt`:
- The `detector_test` POST_BUILD copy now copies **all** `${ORT_ROOT}/lib/*.dll`
  (via `file(GLOB ...)`), not just `onnxruntime.dll`.
- Added an equivalent POST_BUILD step for the `person_tracker_native_ext` target
  so the four ORT DLLs land next to the `.pyd`. The Python test harness already
  calls `os.add_dll_directory` on the `.pyd` dir, so the providers resolve.

Test harness `C:/Users/kiyus/AppData/Local/Temp/test_native_import.py`:
- Points sys.path / DLL dirs at the worktree build output
  (`.../build/Release`).
- Adds `os.add_dll_directory` for ORT lib, CUDA v12.8 bin and TensorRT
  `C:/TensorRT/TensorRT-10.16.1.11/bin` (TRT EP runtime deps).
- Imports torch **before** the .pyd to reproduce the prod load order.

No C++ source (detector.cpp / bindings.cpp) changes were needed. The existing
`SS_PT_NATIVE_NO_CUDA_FALLBACK` escape hatch was not required — TRT EP works.

## Build setup used

- Generator: `Visual Studio 17 2022` + `-A x64` (matches the known-good setup;
  Ninja produced an LNK2005 duplicate-symbol on `detector_test` because the
  static lib and the exe both compile `preprocess.cu`).
- cmake from VS BuildTools, run inside `vcvars64.bat`.
- `-Dpybind11_DIR=<venv>/Lib/site-packages/pybind11/share/cmake/pybind11`.
- `CUDA_SEPARABLE_COMPILATION OFF` on exe + .pyd targets preserved.

## Result

Harness output (torch imported first):

```
[detector] TensorRT EP appended (...trt_cache_person_native)
[detector] loaded: input=images (dtype=1), output=output0 (dtype=1), trt=1
[harness] torch 2.11.0+cu128 cuda 12.8
[harness] import OK: ...person_tracker_native_ext.cp312-win_amd64.pyd
[harness] BatchDetector constructed OK
[harness] warm detect_and_track OK, frames=4
[harness] RESULT fps=632.0 (N=50 B=4 total=0.32s)
OK fps=632.0
```

**632.0 fps** (B=4, N=50) via TRT FP16 EP — matches the ~628 fps standalone exe.

Model used: `yolov8n_v2_finetuned_dyn.onnx` (1-class / n_ch=5), which
`bindings.cpp` requires. The worktree's own `models/` only contains the 84-ch
COCO `yolov8n.onnx`; the 1-class model was read (read-only) from the live
checkout's `models/` dir via `SS_PT_MODEL`.

## Remaining issues / follow-ups

- The worktree lacks `yolov8n_v2_finetuned_dyn.onnx`; tests must point at the
  finetuned 1-class model (set `SS_PT_MODEL`). Consider committing/symlinking it.
- TensorRT runtime DLLs are resolved via `os.add_dll_directory` in the harness,
  not copied next to the .pyd (they are large). Production loader code must add
  `C:/TensorRT/TensorRT-10.16.1.11/bin` to the DLL search path the same way.
- `bindings.cpp` only supports n_ch=5 (1-class); 84-ch COCO models are rejected.
