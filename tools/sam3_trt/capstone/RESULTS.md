# SAM3 Capstone Hybrid Pipeline -- Integrated Benchmark (RTX 5060 Ti, sm_120)

Date: 2026-05-30. 30 prod test frames (sam3_bench/frames, 518x518), text="person".
venv python 3.12 / torch 2.11+cu128 / TensorRT 10.16.1.11.

## Integrated config tested
Hybrid = TRT encoder + TRT decoder (sam3_dec_notactic.plan, FP32+noTactic) +
PyTorch for grounding/neck/mask head. Encoder run via persistent IO buffers with
optional CUDA-graph capture (torch.cuda.CUDAGraph around execute_async_v3).

## IMPORTANT correction to the brief's premise
The brief assumed a VERIFIED BF16 encoder plan (sam3_enc_518_bf16.plan, corr 0.9998,
~74ms, 1.92-2.0x). That plan does NOT exist and never passed. The bf16 agent's own
STATUS_bf16.txt + git commit 194b3ba document:
  - plain BF16 build FAILED (ConvTranspose unsupported in bf16; 0-byte plan)
  - BF16 + ConvTranspose:fp32 BUILT but FAILED verification (corr 0.113 = noise)
  - the only fast+correct engine is sam3_enc_linfp16.plan = FP16 dense layers, FP32
    attention-core/RoPE/LN. corr 0.99993, but only 1.20-1.21x (NOT 1.92x).
So the integrated "fast" config uses linfp16 (best available), and FP32-enc is the
gold-quality reference. No BF16 win exists on this Blackwell card.

## Encoder microbench (isolated TRT, 50 iters incl H2D copy)
  FP32  no-graph : 141.95 ms
  FP32  cudagraph: 141.38 ms   (~0% gain)
  linfp16 cudagraph: 116.89 ms (1.21x vs FP32)
CUDA graph gives ~0 benefit: the encoder is ONE large execute_async_v3, so host
enqueue overhead is negligible vs 117-142ms GPU compute. (The "16x enqueue" win
applies to many tiny kernels, not a single monolithic TRT engine.)

## End-to-end (median over 29 timed frames)
  config                              fps    ms     frame0 masks   mean IoU   min IoU
  PyTorch (baseline)                  3.22   310.2  71             1.000      1.000  (ref)
  FP32-enc-TRT + dec-TRT + graph      4.44   225.0  71             0.999      0.976
  linfp16-enc-TRT + dec-TRT + graph   4.96   201.6  67 (4 DROPPED) 0.929      0.172
VRAM peak (torch alloc): PyTorch 4647 / FP32-hybrid 4658 / linfp16-hybrid 4697 MB.

## Speedups
  FP32-hybrid : 1.38x vs PyTorch (3.22->4.44). Quality PRESERVED (IoU 0.999, no drops).
  linfp16-hybrid: 1.54x vs PyTorch, 1.12x vs FP32-hybrid -- but IoU FAILS target.

## Final verdict on the >0.97 mask-IoU target
  - FP32-enc + dec-TRT + cudagraph: PASSES. min IoU 0.976, 71/71 masks, mean 0.999.
  - linfp16-enc + dec-TRT: FAILS. mean 0.929, min 0.172, drops 4 of 71 masks on
    frame0. The 0.65% encoder perturbation compounds through the SAM3 mask decoder
    and destroys small/distant person masks. NOT production-safe.

## RECOMMENDED production offline config
  FP32-encoder-TRT + decoder-TRT + CUDA-graph encoder = 4.44 fps at IoU 0.999/min
  0.976 (full mask fidelity). This is the integration of every win that does NOT
  cost accuracy. linfp16 is faster (4.96 fps) but only acceptable if degraded
  small-object recall is tolerable -- it is not, for person tracking.

## Reusable artifacts
  encoder (gold):  C:/Users/kiyus/Desktop/sam3_bench/sam3_enc_518_fix_notactic.plan
  encoder (fast):  C:/Users/kiyus/Desktop/sam3_bench/bf16/sam3_enc_linfp16.plan
  decoder:         C:/Users/kiyus/Desktop/sam3_bench/e2e/sam3_dec_notactic.plan
  harness:         tools/sam3_trt/capstone/capstone_bench.py
  results json:    tools/sam3_trt/capstone/capstone_result.json
  (NO working BF16 plan exists; sam3_enc_bf16_nt.plan is 0 bytes / failed.)
