"""Map TrackNet heatmap peaks into ShuttleScope's Zone9 grid."""

from __future__ import annotations

from typing import Optional

Y_BACK = 0.50
Y_NET = 0.25
X_LEFT = 0.33
X_RIGHT = 0.67

# ---------------------------------------------------------------------------
# Phase-2: バッチ GPU argmax
# ---------------------------------------------------------------------------

ZONE_MAP: dict[tuple[str, str], str] = {
    ("B", "L"): "BL",
    ("B", "C"): "BC",
    ("B", "R"): "BR",
    ("M", "L"): "ML",
    ("M", "C"): "MC",
    ("M", "R"): "MR",
    ("N", "L"): "NL",
    ("N", "C"): "NC",
    ("N", "R"): "NR",
}


def coords_to_zone(x_norm: float, y_norm: float) -> Optional[str]:
    if not (0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0):
        return None

    if y_norm > Y_BACK:
        row = "B"
    elif y_norm <= Y_NET:
        row = "N"
    else:
        row = "M"

    if x_norm <= X_LEFT:
        col = "L"
    elif x_norm > X_RIGHT:
        col = "R"
    else:
        col = "C"

    return ZONE_MAP.get((row, col))


def heatmap_to_zone(
    heatmap,
    threshold: float = 0.5,
) -> tuple[Optional[str], float, Optional[tuple[float, float]]]:
    import numpy as np

    h, w = heatmap.shape
    peak_val = float(heatmap.max())
    if peak_val < threshold:
        return None, peak_val, None

    y_px, x_px = np.unravel_index(np.argmax(heatmap), heatmap.shape)
    x_norm = x_px / w
    y_norm = y_px / h

    return coords_to_zone(x_norm, y_norm), peak_val, (x_norm, y_norm)


def batch_heatmap_argmax(
    heatmaps,
    threshold: float = 0.5,
) -> list[tuple[Optional[str], float, Optional[tuple[float, float]]]]:
    """N 枚のヒートマップを GPU tensor のまま一括 argmax する。

    heatmaps: (N, H, W) torch.Tensor (CUDA float32) または numpy ndarray
    戻り値: heatmap_to_zone() と同じ (zone, confidence, coords) のリスト

    GPU tensor の場合は GPU 上で argmax/max を計算し、
    D2H 転送は各バッチ末尾の 1 回にまとめる。
    numpy の場合は heatmap_to_zone() をループで呼ぶ（フォールバック）。
    """
    try:
        import torch  # type: ignore
        if not isinstance(heatmaps, torch.Tensor):
            raise TypeError("not a tensor")

        N, H, W = heatmaps.shape
        flat = heatmaps.view(N, -1)                 # (N, H*W)
        peaks, flat_idx = flat.max(dim=1)           # (N,) GPU
        peaks_cpu = peaks.cpu()                     # D2H まとめて 1 回
        flat_idx_cpu = flat_idx.cpu()               # D2H まとめて 1 回

        results = []
        for i in range(N):
            peak_val = float(peaks_cpu[i])
            if peak_val < threshold:
                results.append((None, peak_val, None))
                continue
            idx = int(flat_idx_cpu[i])
            y_px = idx // W
            x_px = idx % W
            x_norm = x_px / W
            y_norm = y_px / H
            results.append((coords_to_zone(x_norm, y_norm), peak_val, (x_norm, y_norm)))
        return results

    except Exception:
        # torch 未インストール or numpy 入力 → 既存実装にフォールバック
        import numpy as np
        arr = heatmaps if isinstance(heatmaps, np.ndarray) else heatmaps
        return [heatmap_to_zone(arr[i], threshold) for i in range(len(arr))]
