"""TrackNet のピーク位置を ShuttleScope の Zone9 に対応づける。

A-1b (2026-09-22) で作り直した。

## 以前なにをしていたか

`coords_to_zone(x_norm, y_norm)` は **画像の生の正規化座標**を

    y_norm > 0.50            → B (Back)
    y_norm <= 0.25           → N (Net)
    それ以外                 → M (Mid)
    x_norm <= 0.33 / > 0.67  → L / R

で切って Zone9 を返していた。この区切りが成り立つのは
「画面の上半分にちょうど半面だけが写っていて、ネットが y=0.25 のあたりにあり、
遠近の歪みが無い」ときだけで、**実際の全景カメラではどれも成り立たない**。

全景では画面の下半分は手前の半面なので、旧実装はそこを丸ごと `B` と呼び、
上半分（奥の半面）ではベースライン側を `N`、ネット側を `M` と呼んでいた。
つまり**奥側半面では行が逆**で、しかも半面の区別が一切無かった。

その `zone` は `cv/candidate_builder.py` を通って `land_zone` 候補として
人のレビューに出ていた。

## いま何を返すか

画像座標だけからは Zone9 は決まらない。ネットがどこかも、どちらの半面かも、
遠近でどれだけ潰れているかも分からないからである。**分からないときは
分からないと言う**（キャリブレーション未設定の試合で移動量統計を出さない
のと同じ方針）。

- `coords_to_zone` は常に `None` を返す。**直さないこと。**
  「画像座標から Zone9 を出す」は直せる種類の誤りではなく、
  必要なのはホモグラフィである。
- キャリブレーション済みなら `court_to_zone9(court_x, court_y)` を使う。
  コート正規化座標は `routers/court_calibration.pixel_to_court_zone` が出す。
  実際の充填は `routers/video_import.py` のキャリブレーション後処理で行う。

## Zone9 の基準（正本は `src/components/court/CourtDiagram.tsx`）

- 行 B/M/N は **ネット基準**。どちらの半面でも N がネット際、B がベースライン側
- 列 L/C/R は **画面基準**。どちらの半面でも画面左が L。鏡映しない
"""

from __future__ import annotations

from typing import Optional

#: コート正規化座標のネット位置 (TL=(0,0), BL=(0,1) の系で y≈0.5)
NET_Y = 0.5

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


def court_to_zone9(court_x: float, court_y: float) -> Optional[tuple[str, str]]:
    """コート正規化座標 → `(side, Zone9)`。コート外なら None。

    court_x: 0=画面左のサイドライン, 1=画面右のサイドライン
    court_y: 0=A 側ベースライン, 0.5=ネット, 1=B 側ベースライン

    行は**ネットからの距離**で三等分する（半面の長さの 1/3 ずつ）。
    列は court_x をそのまま三等分する（鏡映しない＝画面基準）。
    """
    if not (0.0 <= court_x <= 1.0 and 0.0 <= court_y <= 1.0):
        return None

    side = "A" if court_y < NET_Y else "B"
    # ネットからの距離を半面の長さで正規化 (0=ネット際, 1=ベースライン)
    depth = (NET_Y - court_y) / NET_Y if side == "A" else (court_y - NET_Y) / NET_Y
    depth = max(0.0, min(1.0, depth))

    if depth <= 1.0 / 3.0:
        row = "N"
    elif depth <= 2.0 / 3.0:
        row = "M"
    else:
        row = "B"

    if court_x <= 1.0 / 3.0:
        col = "L"
    elif court_x > 2.0 / 3.0:
        col = "R"
    else:
        col = "C"

    zone = ZONE_MAP.get((row, col))
    return (side, zone) if zone else None


def coords_to_zone(x_norm: float, y_norm: float) -> Optional[str]:
    """**常に None。** 画像の生座標から Zone9 は決まらない。

    ネット位置も半面の別も遠近の歪みも画像座標には入っていない。
    旧実装はこれを固定の閾値で切って Zone9 を名乗り、その値が
    `land_zone` 候補として人のレビューに出ていた。
    キャリブレーション済みの経路では `court_to_zone9` を使うこと。
    """
    return None


def heatmap_to_zone(
    heatmap,
    threshold: float = 0.5,
) -> tuple[Optional[str], float, Optional[tuple[float, float]]]:
    """ピーク位置と強度を返す。zone は常に None（`coords_to_zone` と同じ理由）。"""
    import numpy as np

    h, w = heatmap.shape
    peak_val = float(heatmap.max())
    if peak_val < threshold:
        return None, peak_val, None

    y_px, x_px = np.unravel_index(np.argmax(heatmap), heatmap.shape)
    x_norm = x_px / w
    y_norm = y_px / h

    return None, peak_val, (x_norm, y_norm)


def batch_heatmap_argmax(
    heatmaps,
    threshold: float = 0.5,
) -> list[tuple[Optional[str], float, Optional[tuple[float, float]]]]:
    """N 枚のヒートマップを GPU tensor のまま一括 argmax する。

    heatmaps: (N, H, W) torch.Tensor (CUDA float32) または numpy ndarray
    戻り値: heatmap_to_zone() と同じ (zone, confidence, coords) のリスト。
    zone は常に None。

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
            results.append((None, peak_val, (x_norm, y_norm)))
        return results

    except Exception:
        # torch 未インストール or numpy 入力 → 既存実装にフォールバック
        import numpy as np
        arr = heatmaps if isinstance(heatmaps, np.ndarray) else heatmaps
        return [heatmap_to_zone(arr[i], threshold) for i in range(len(arr))]
