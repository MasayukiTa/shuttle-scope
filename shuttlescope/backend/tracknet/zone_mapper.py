"""Map TrackNet heatmap peaks into ShuttleScope's Zone9 grid."""

from __future__ import annotations

from typing import Optional

Y_BACK = 0.50
Y_NET = 0.25
X_LEFT = 0.33
X_RIGHT = 0.67

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
