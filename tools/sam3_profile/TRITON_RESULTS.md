# Triton-on-Windows + torch.compile for SAM3 (RTX 5060 Ti, sm_120)

Env: RTX 5060 Ti (Blackwell sm_120), torch 2.11.0+cu128, py3.12.0, Windows.
Date: 2026-05-30. Backend venv (production):
`C:/Users/kiyus/Desktop/github/shuttle-scope/shuttlescope/backend/.venv`.

## Triton install (the prior blocker)
- Installed `triton-windows==3.5.1.post24` (provides `triton 3.5.1`, matching torch 2.11's
  Triton 3.5 line) into the **production backend venv**. Purely additive: only `triton-windows`
  was added; torch/other packages untouched (`pip freeze` snapshot in
  `sam3_bench/triton/freeze_before.txt`). torch still imports & CUDA available after install.
- `import triton` -> `3.5.1`. A trivial `@triton.jit` add kernel **compiled to PTX and ran
  correctly on the sm_120 GPU** (max err 0.0). See `triton_results/kernel_test.log`.
- Inductor smoke test (tiny MLP, `mode="max-autotune"`): **compiled and ran correctly**
  (max err 4.8e-7). MSVC C++ wrapper compilation works. Warning "Not enough SMs to use
  max_autotune_gemm" is non-fatal (falls back to default Triton mm). See `inductor_smoke.log`.

=> **Triton IS functional on this Windows box.** The prior `TritonMissing` failure is resolved.

## torch.compile on SAM3
| Config | mode | result |
|--------|------|--------|
| backbone+decoder | reduce-overhead | FAILS: CUDA-graphs tensor-overwrite in backbone neck conv2d (cudagraph hazard, same as prior cudagraphs finding) |
| backbone+decoder | max-autotune-no-cudagraphs | RUNS but **recompile-thrashes**: inductor re-autotunes on nearly every call (SAM3 dynamic shapes) -> no usable steady state, killed |
| **decoder only** | **inductor default, dynamic=True, no cudagraphs** | **WIN: works cleanly, 0 recompiles** |

### Decoder-only torch.compile (the viable path), N=20 median, CUDA-synced
- eager:    181.39 ms (5.51 fps)
- compiled: 168.10 ms (5.95 fps)
- **end-to-end speedup 1.079x**, recompiles=0
- **mask IoU vs eager: mean 0.9999, min 0.9996** (correct)

Decoder is ~18% of runtime; a 13 ms end-to-end saving implies the decoder stage itself dropped
~51->~38 ms (~1.3x on the stage). `dynamic=True` is essential — it marks shapes dynamic up front
and eliminates the per-call recompilation that makes naive `torch.compile` unusable here.

## Conclusion
- triton-windows unlocks inductor/Triton codegen on Windows + sm_120 + torch 2.11. Real, but modest.
- **Viable win: compile transformer.decoder only with `dynamic=True` (no cudagraphs)** ->
  ~1.08x e2e, correctness preserved. Do NOT compile the backbone (cudagraph hazard) and do NOT
  use reduce-overhead/cudagraphs or naive max-autotune (recompile thrash).
- The image_encoder (68% of runtime) remains the dominant target; it is matmul-bound and TRT-
  accelerated already, so torch.compile is unlikely to beat TRT there.
