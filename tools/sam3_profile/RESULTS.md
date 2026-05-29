# SAM3 Inference Profiling + torch.compile Evaluation

Env: RTX 5060 Ti (Blackwell sm_120), torch 2.11.0+cu128, ultralytics 8.4.38, Windows.
Model: sam3.pt via SAM3SemanticPredictor, prompt text=["person"], imgsz=518.
Test frame: ultralytics assets/bus.jpg (4 people + bus; 5 person masks). Median of N=20, CUDA-synced. EAGER PyTorch (no TRT engine loaded).

## Per-stage latency (warm, synced, median)

| Stage                | ms     | % total |
|----------------------|--------|---------|
| preprocess           | 2.90   | 1.0     |
| image_encoder (backbone) | 191.02 | 68.6 |
| text_encoder         | 0.00   | 0.0  (cached after 1st call) |
| geometry_encoder     | 0.00   | 0.0  (cached) |
| transformer.encoder  | 11.75  | 4.2     |
| transformer.decoder  | 50.61  | 18.2    |
| dot_prod_scoring     | 0.99   | 0.4     |
| segmentation_head    | 5.06   | 1.8     |
| postprocess          | 2.67   | 1.0     |
| **total**            | **278.56** | (3.59 fps) |

stage_sum 265 ms, unaccounted 13.6 ms (Python glue / dataloader).

DOMINANT: image_encoder 68.6% (191 ms eager PyTorch), then transformer.decoder 18.2% (51 ms).
Note: 191 ms is the *eager PyTorch* encoder. The TRT FP32+noTactic engine (STATUS.txt) cuts the encoder but only ~1.15x end-to-end (FP16 numerically broken on this card).

## torch.compile

| Config | backend | speedup | IoU vs eager | result |
|--------|---------|---------|--------------|--------|
| backbone+decoder | inductor (reduce-overhead / max-autotune) | -- | -- | FAILS: TritonMissing |
| backbone+decoder | cudagraphs | -- | -- | FAILS: decoder dynamic-coords tensor overwrite |
| backbone only    | cudagraphs | 0.945x | 1.000 | correct but SLOWER |
| backbone only    | aot_eager  | 0.97x  | 1.000 | correct, no speedup |

Root cause: Triton is NOT installed in the prod venv and has no viable Windows build. torch.compile's only kernel-generating backend (inductor) is therefore non-functional. Also "Not enough SMs to use max_autotune_gemm" on the 5060 Ti. Non-Triton backends are numerically correct (IoU 1.0) but give <=1.0x because they cannot fuse/codegen kernels; cudagraphs adds capture overhead.

## Conclusions
- torch.compile is NOT a viable low-fragility win on this Windows + 5060 Ti + torch2.11 setup (no Triton). Output IoU stays 1.0 where it runs, but there is zero speedup; one backend even regresses 5%.
- Optimization effort should focus on the IMAGE ENCODER (68.6%): the existing TRT FP32+noTactic engine is the realistic lever (~1.15x e2e). Bigger encoder wins are blocked until a TRT/driver update fixes the sm_120 cuBLAS tactic bug so FP16 becomes usable.
- Secondary target: transformer.decoder (18.2%, 51 ms) - pure PyTorch, untouched by TRT. If Triton ever lands on Windows (or move to Linux), the decoder is the best torch.compile candidate.
