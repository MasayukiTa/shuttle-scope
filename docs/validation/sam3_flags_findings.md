# SAM3 Encoder TRT Toolchain Speedup Investigation

Date: 2026-05-30
Branch: feat/sam3-flags
GPU: RTX 5060 Ti (Blackwell sm_120), driver 596.21
TensorRT: 10.16.1.11 (v101601 b11)
ONNX: sam3_enc_518_fix.onnx (518x518 encoder)
Ground truth: enc_ref.npz

## Baseline (working config)
Build: `--noTF32 --tacticSources=-CUBLAS,-CUBLAS_LT,-CUDNN --memPoolSize=workspace:4096`
- Accuracy: worst rel_mean 0.00035, corr 1.0 (PASS)
- trtexec standalone GPU compute: **142.3 ms median** (6.96 qps), enqueue 2.55 ms
- NB: the "~25ms / 4fps hybrid" figure from the brief is the hybrid-pipeline amortized
  number, not standalone encoder inference. All flag deltas below use the consistent
  trtexec harness (--iterations=100 --avgRuns=50).

## 1. TensorRT version
- Only 10.16.1.11 is installed on prod. No newer zip staged anywhere under kiyus/.
- Box HAS internet egress (developer.nvidia.com reachable).
- Latest is **TensorRT 11.0.0** (Windows + CUDA 12.8.1, expanded sm_120 enablement) per
  NVIDIA release notes. Could plausibly fix the sm_120 cuBLAS MatMul mis-execution that
  forces the tactic exclusion.
- BLOCKER: TRT downloads are behind NVIDIA Developer Program login (auth-gated zip), so it
  cannot be wget'd unattended. NOT installed. REQUIRES: a human to download the
  TensorRT 11.0.0 Windows zip (CUDA 12.8) from developer.nvidia.com and extract to
  C:\TensorRT\. Then rebuild WITHOUT the tactic exclusion and verify corr vs enc_ref to
  confirm the cuBLAS bug is fixed. No admin needed (zip extract only).

## 2. FP8 (e4m3)
Build: `--fp8 --noTF32 --tacticSources=-CUBLAS,-CUBLAS_LT,-CUDNN`
- Accuracy: corr 1.0, worst rel_mean 0.00035 (PASS) — IDENTICAL to FP32 baseline.
- GPU compute: **154 ms median — ~8% SLOWER than FP32 baseline.**
- Reason: the ONNX has no Q/DQ nodes, so `--fp8` cannot select real FP8 MatMul kernels;
  it kept compute in high precision (hence identical accuracy) while adding cast overhead.
- Conclusion: FP8 is a dead end here without an explicitly quantized (Q/DQ, calibrated)
  ONNX. That requires a calibration/PTQ export step — out of scope for builder flags.

## 3. Builder flags (on working FP32+notactic config)
| Config                     | GPU compute median | vs baseline | enqueue |
|----------------------------|--------------------|-------------|---------|
| baseline (opt3, ws4096)    | 142.3 ms           | --          | 2.55 ms |
| --builderOptimizationLevel=5 | 141.8 ms         | ~0 (noise)  | 2.7 ms  |
| --memPoolSize=workspace:8192 | 146.2 ms         | ~0 (noise)  | 2.5 ms  |
| --useCudaGraph (runtime)   | 144.6 ms           | ~0 compute  | **0.16 ms** (16x less) |
| --best                     | **37.8 ms (26 qps)** | **3.8x FASTER** but **ACCURACY BROKEN** (corr 0.44, rel_mean 1.03, PASS=false) | 2.8 ms |

- builderOptimizationLevel=5: no measurable speedup (compute-bound model, opt3 already
  finds good tactics given the tactic exclusion).
- Large mempool (8GB): no improvement (4GB workspace already sufficient).
- useCudaGraph: no GPU-compute change (model is GPU-bound at 142ms), BUT cuts CPU enqueue
  overhead 2.55ms -> 0.16ms. Worth enabling in the hybrid pipeline since the CPU is busy
  with detection/tracking concurrently — frees CPU launch budget at zero accuracy cost.
- --best: 3.8x faster (37.8ms, plan shrinks 1740MB->488MB) by selecting FP16/INT8/FP8
  tactics, but accuracy is DESTROYED (corr 0.44) — same failure mode as plain-FP32+tactics
  and FP16 on this sm_120 build. Confirms that on TRT 10.16 the 142ms FP32 cost and
  correctness are inseparable from the tactic exclusion; any lower-precision path breaks.

## Best config found
The existing baseline (`--noTF32 --tacticSources=-CUBLAS,-CUBLAS_LT,-CUDNN`) remains
optimal for accuracy+speed on TRT 10.16. Add `--useCudaGraph` at inference time for CPU
overhead reduction. No builder flag improves GPU compute. Real speedup requires either
(a) TensorRT 11.0 (may lift the tactic exclusion -> faster cuBLAS MatMul) or
(b) a Q/DQ-calibrated ONNX for genuine FP8 — both need a human-gated step.
