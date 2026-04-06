"""TrackNet座標 → Zone9 マッピング

コート（カメラ正面想定）を 3×3 に分割:
  NL | NC | NR   ← ネット前（奥）
  ML | MC | MR   ← ミドル
  BL | BC | BR   ← バック（手前）

入力: 正規化座標 (x_norm, y_norm) — 各 0.0～1.0
  x: 左端=0, 右端=1
  y: 画面上端=0（相手側ベースライン）, 画面下端=1（自コートベースライン）

自コート側（手前 = y > 0.5）→ B系ゾーン
ミドル（0.25 < y ≤ 0.5）  → M系ゾーン
ネット前（y ≤ 0.25）       → N系ゾーン
"""

from typing import Optional

# Zone境界（正規化座標）
Y_BACK = 0.50   # y > Y_BACK → Back row (BL/BC/BR)
Y_NET  = 0.25   # y ≤ Y_NET  → Net row  (NL/NC/NR)
X_LEFT = 0.33   # x ≤ X_LEFT → Left column
X_RIGHT= 0.67   # x > X_RIGHT → Right column

ZONE_GRID = [
    # row, col → zone
    ("B", "L"): "BL", ("B", "C"): "BC", ("B", "R"): "BR",
    ("M", "L"): "ML", ("M", "C"): "MC", ("M", "R"): "MR",
    ("N", "L"): "NL", ("N", "C"): "NC", ("N", "R"): "NR",
]

# dict形式に変換
_ZONE_MAP: dict[tuple[str, str], str] = {k: v for k, v in ZONE_GRID}


def coords_to_zone(x_norm: float, y_norm: float) -> Optional[str]:
    """正規化座標からZone9文字列を返す。コート外(0-1範囲外)はNoneを返す。"""
    if not (0.0 <= x_norm <= 1.0 and 0.0 <= y_norm <= 1.0):
        return None

    # 行（奥→手前: N→M→B）
    if y_norm > Y_BACK:
        row = "B"
    elif y_norm <= Y_NET:
        row = "N"
    else:
        row = "M"

    # 列
    if x_norm <= X_LEFT:
        col = "L"
    elif x_norm > X_RIGHT:
        col = "R"
    else:
        col = "C"

    return _ZONE_MAP.get((row, col))


def heatmap_to_zone(
    heatmap,   # numpy array (H, W), values 0~1
    threshold: float = 0.5,
) -> tuple[Optional[str], float, Optional[tuple[float, float]]]:
    """TrackNet出力ヒートマップからZone9とconfidenceを返す。
    Returns: (zone, confidence, (x_norm, y_norm))
    シャトルが検出されない場合は (None, 0.0, None)。
    """
    import numpy as np

    h, w = heatmap.shape
    peak_val = float(heatmap.max())

    if peak_val < threshold:
        return None, peak_val, None

    # ピーク座標を取得
    peak_idx = np.unravel_index(np.argmax(heatmap), heatmap.shape)
    y_px, x_px = peak_idx
    x_norm = x_px / w
    y_norm = y_px / h

    zone = coords_to_zone(x_norm, y_norm)
    return zone, peak_val, (x_norm, y_norm)
