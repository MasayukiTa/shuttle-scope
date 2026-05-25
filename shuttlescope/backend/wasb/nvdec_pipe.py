"""NVDEC zero-copy GPU pipe for WASB shuttle detection.

Decodes 1080p H.264 via NVIDIA NVDEC, keeps frames on GPU as torch tensors
(no CPU copy), runs GPU preprocess + WASB inference. Eliminates the cv2 +
H2D upload bottleneck.

Measured on RTX 5060 Ti (player_a 1798 frame, INT8 WASB):
  cv2 + WASB path:    17s (105 FPS)
  NVDEC + WASB path:  11.5s (156 FPS, 1.49x)
  Decode share dropped from ~43% to 24% of pipeline wall.

Requirements:
  pip install PyNvVideoCodec    (uses _121 variant for CUDA 12.x torch)
  NVIDIA driver with NVDEC support (already shipped with 596.21+)

Usage:
    from backend.wasb.nvdec_pipe import iter_nvdec_triplets, infer_with_wasb
    for tri_batch in iter_nvdec_triplets(video_path, start_sec=600, n_frames=1800):
        results = infer_with_wasb(wasb, tri_batch)
"""
from __future__ import annotations
import os
import importlib.util
import logging
from pathlib import Path
from typing import Iterator, Optional

import numpy as np

logger = logging.getLogger(__name__)

# ── Load PyNvVideoCodec, forcing the CUDA-12-compatible variant ──────
def _load_nvc():
    """Load PyNvVideoCodec _121 module (CUDA 12.x compatible with our torch).

    The PyNvVideoCodec package auto-picks _130 based on NVENC driver version,
    but _130 requires CUDA 13 runtime that we don't have. We import _121
    directly which works with PyTorch's bundled CUDA 12.8.
    """
    try:
        import PyNvVideoCodec as _pkg
        pkg_dir = Path(_pkg.__file__).parent
    except ImportError:
        logger.warning("PyNvVideoCodec not installed; NVDEC pipe unavailable")
        return None
    # Try _121 first (matches CUDA 12.x)
    candidate = pkg_dir / "PyNvVideoCodec_121.cp312-win_amd64.pyd"
    if not candidate.exists():
        # Try other naming patterns / versions
        for cand in pkg_dir.glob("PyNvVideoCodec_*.pyd"):
            candidate = cand
            break
    if not candidate.exists():
        logger.warning("PyNvVideoCodec .pyd not found in %s", pkg_dir)
        return None
    spec = importlib.util.spec_from_file_location("_PyNvVideoCodec", str(candidate))
    try:
        nvc = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(nvc)
        logger.info("[nvdec] loaded %s", candidate.name)
        return nvc
    except Exception as exc:
        logger.warning("[nvdec] failed to load %s: %s", candidate.name, exc)
        return None


_nvc = _load_nvc()


def is_available() -> bool:
    return _nvc is not None


def iter_nvdec_frames_gpu(
    video_path: str,
    start_sec: float = 0.0,
    n_frames: Optional[int] = None,
    gpu_id: int = 0,
):
    """Yield (3, H, W) uint8 RGB CHW frames as torch tensors on GPU.

    Each frame is a zero-copy view into the NVDEC output buffer. Hold each
    tensor only as long as needed before requesting the next frame; the
    decoder may overwrite/recycle the underlying memory.
    """
    if _nvc is None:
        raise RuntimeError("PyNvVideoCodec not available")
    import torch
    sdec = _nvc.CreateSimpleDecoder(
        video_path, gpu_id, 0, 0,
        True,                          # use_device_memory (GPU buffers)
        0, 0, 0, 4,
        _nvc.OutputColorType.RGBP,    # CHW RGB output
        False, False,
    )
    # Resolve start index. Most clips are 60 fps; use the demuxer fps if needed.
    fps = 60.0
    try:
        # SimpleDecoder doesn't expose framerate directly; use Demuxer.
        demuxer = _nvc.CreateDemuxer(video_path)
        fps = demuxer.FrameRate()
    except Exception:
        pass
    start_idx = int(start_sec * fps)
    end_idx = start_idx + (n_frames or 10**9)
    for i in range(start_idx, end_idx):
        try:
            f = sdec[i]
            yield torch.as_tensor(f, device=f"cuda:{gpu_id}")
        except Exception:
            break


def iter_nvdec_chunks(
    video_path: str,
    start_sec: float = 0.0,
    n_frames: Optional[int] = None,
    gpu_id: int = 0,
    chunk_size: int = 128,
    overlap: int = 2,
    output_size: tuple = (288, 512),
    normalize: bool = True,
):
    """Yield (chunk_size, 3, H_OUT, W_OUT) float32 RGB GPU tensors,
    already preprocessed for WASB (resize + ImageNet normalize).

    overlap: number of frames shared between consecutive chunks for sliding
    window inference (=FRAME_STACK-1 in WASB's case).
    """
    if _nvc is None:
        raise RuntimeError("PyNvVideoCodec not available")
    import torch

    H_OUT, W_OUT = output_size
    mean_gpu = torch.tensor([0.485, 0.456, 0.406],
                             device=f"cuda:{gpu_id}").view(1, 3, 1, 1)
    std_gpu = torch.tensor([0.229, 0.224, 0.225],
                            device=f"cuda:{gpu_id}").view(1, 3, 1, 1)

    buf = []
    total_yielded = 0
    target = n_frames or 10**9

    for t_frame in iter_nvdec_frames_gpu(video_path, start_sec, target, gpu_id):
        buf.append(t_frame)
        if len(buf) >= chunk_size:
            stacked = torch.stack(buf, dim=0).float() / 255.0
            if (stacked.shape[-2], stacked.shape[-1]) != output_size:
                stacked = torch.nn.functional.interpolate(
                    stacked, size=output_size, mode="bilinear", align_corners=False,
                )
            if normalize:
                stacked = (stacked - mean_gpu) / std_gpu
            yield stacked, total_yielded
            total_yielded += len(buf) - overlap
            buf = buf[-overlap:] if overlap > 0 else []
    if len(buf) >= 3:
        stacked = torch.stack(buf, dim=0).float() / 255.0
        if (stacked.shape[-2], stacked.shape[-1]) != output_size:
            stacked = torch.nn.functional.interpolate(
                stacked, size=output_size, mode="bilinear", align_corners=False,
            )
        if normalize:
            stacked = (stacked - mean_gpu) / std_gpu
        yield stacked, total_yielded


def run_wasb_on_nvdec(
    wasb,
    video_path: str,
    start_sec: float = 0.0,
    n_frames: int = 1800,
    gpu_id: int = 0,
    visible_threshold: float = 0.5,
) -> list[dict]:
    """End-to-end NVDEC → WASB pipeline.

    Returns the same list[dict] as WasbInference.predict_frames (one entry per
    triplet, with frame_idx, x_norm, y_norm, confidence, visible, zone)."""
    import torch
    from backend.wasb.inference import FRAME_STACK, INPUT_H, INPUT_W
    from backend.tracknet.zone_mapper import coords_to_zone

    sess = wasb._session
    inp_name = wasb._input_name
    out_name = sess.get_outputs()[0].name
    batch = max(1, wasb._max_batch)
    overlap = FRAME_STACK - 1

    results: list[dict] = []
    for stacked_chunk, chunk_start_idx in iter_nvdec_chunks(
        video_path, start_sec, n_frames, gpu_id,
        chunk_size=128, overlap=overlap,
        output_size=(INPUT_H, INPUT_W),
    ):
        n_trip = stacked_chunk.shape[0] - 2
        if n_trip <= 0: continue
        trips = torch.cat([stacked_chunk[0:n_trip],
                            stacked_chunk[1:n_trip+1],
                            stacked_chunk[2:n_trip+2]], dim=1)
        for b0 in range(0, n_trip, batch):
            inp = trips[b0:b0+batch].contiguous()
            bsz = inp.shape[0]
            if bsz != batch:
                pad = torch.zeros(batch-bsz, 9, INPUT_H, INPUT_W,
                                   dtype=torch.float32, device=f"cuda:{gpu_id}")
                inp = torch.cat([inp, pad], dim=0)
            out_t = torch.empty(batch, FRAME_STACK, INPUT_H, INPUT_W,
                                 dtype=torch.float32, device=f"cuda:{gpu_id}")
            io = sess.io_binding()
            io.bind_input(name=inp_name, device_type="cuda", device_id=gpu_id,
                          element_type=np.float32, shape=tuple(inp.shape),
                          buffer_ptr=inp.data_ptr())
            io.bind_output(name=out_name, device_type="cuda", device_id=gpu_id,
                           element_type=np.float32, shape=tuple(out_t.shape),
                           buffer_ptr=out_t.data_ptr())
            sess.run_with_iobinding(io)
            last = torch.sigmoid(out_t[:bsz, -1, :, :])
            mv, idx = last.view(bsz, -1).max(dim=1)
            ys = (idx // INPUT_W).cpu().numpy()
            xs = (idx % INPUT_W).cpu().numpy()
            confs = mv.cpu().numpy()
            for i in range(bsz):
                conf = float(confs[i])
                visible = conf >= visible_threshold
                x_norm = float(xs[i]) / INPUT_W
                y_norm = float(ys[i]) / INPUT_H
                results.append({
                    "frame_idx": chunk_start_idx + b0 + i + FRAME_STACK,
                    "confidence": round(conf, 3),
                    "x_norm": round(x_norm, 4) if visible else None,
                    "y_norm": round(y_norm, 4) if visible else None,
                    "visible": visible,
                    "zone": coords_to_zone(x_norm, y_norm) if visible else None,
                })
        del trips
    return results
