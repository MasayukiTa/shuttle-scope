"""Track A2: CourtAdapter — court_calibration を CV パイプラインに連携する thin adapter.

背景:
    `backend/routers/court_calibration.py` に homography ベースの座標変換が
    完成しているが、`candidate_builder.py` / `court_mapper.py` は依然として
    hard-coded な FRONT_THRESHOLD_Y=0.42 や FORMATION_MIN_Y_DIFF=0.18 を
    使っている。カメラアングルやコート位置が違うと誤分類が起きる。

CourtAdapter:
    - match_id 単位で homography を DB から読み込み
    - pixel_to_court / court_to_pixel の双方向変換
    - 動的な depth_band / formation 閾値を提供
    - 未キャリブレーション時は **hard-coded フォールバック** で退化なし

座標系 (court_calibration と一致):
    画像正規化 (x_norm, y_norm) ∈ [0, 1] × [0, 1]
    コート正規化 (cx, cy) ∈ [0, 1] × [0, 1]
        TL=(0,0), TR=(1,0), BR=(1,1), BL=(0,1)
        ネット ≈ y=0.5
        サイド A: y < 0.5、サイド B: y > 0.5
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Literal, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ── フォールバック定数 (キャリブレーション無し時) ─────────────────────────────
# candidate_builder.py / court_mapper.py で使われていた値と互換。
FALLBACK_FRONT_THRESHOLD_Y = float(os.environ.get("CV_FRONT_Y", "0.42"))
FALLBACK_BACK_THRESHOLD_Y = float(os.environ.get("CV_BACK_Y", "0.60"))
FALLBACK_FORMATION_MIN_Y_DIFF = float(os.environ.get("CV_FORMATION_MIN_Y_DIFF", "0.18"))
FALLBACK_FORMATION_MIN_X_DIFF = float(os.environ.get("CV_FORMATION_MIN_X_DIFF", "0.25"))


DepthBand = Literal["front_a", "back_a", "front_b", "back_b", "mid"]
FormationType = Literal["front_back", "parallel", "mixed"]


@dataclass
class CourtAdapter:
    """Match 単位のコート座標 ↔ 画像座標変換 + 閾値プロバイダ。"""

    homography: Optional[list[list[float]]] = None
    homography_inv: Optional[list[list[float]]] = None
    roi_polygon: Optional[list[list[float]]] = None
    _H_np: Optional[np.ndarray] = field(default=None, init=False, repr=False)
    _H_inv_np: Optional[np.ndarray] = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if self.homography is not None:
            self._H_np = np.array(self.homography, dtype=np.float64)
        if self.homography_inv is not None:
            self._H_inv_np = np.array(self.homography_inv, dtype=np.float64)

    # ─── ファクトリ ──────────────────────────────────────────────────────

    @classmethod
    def for_match(cls, match_id: int) -> "CourtAdapter":
        """match_id から DB の court_calibration artifact を読み込む。

        読み込み失敗 / 未設定時は **空の adapter** (フォールバック動作) を返す。
        """
        try:
            # 循環 import 回避
            from backend.routers.court_calibration import load_calibration_standalone
            data = load_calibration_standalone(match_id)
            if data is None:
                return cls()
            return cls(
                homography=data.get("homography"),
                homography_inv=data.get("homography_inv"),
                roi_polygon=data.get("roi_polygon"),
            )
        except Exception as exc:
            logger.warning("CourtAdapter.for_match(%s) failed: %s — fallback", match_id, exc)
            return cls()

    # ─── 状態 ─────────────────────────────────────────────────────────────

    @property
    def is_calibrated(self) -> bool:
        return self._H_np is not None

    # ─── 座標変換 ────────────────────────────────────────────────────────

    def pixel_to_court(self, x: float, y: float) -> Tuple[float, float]:
        """画像正規化 → コート正規化 (キャリブ無しなら passthrough)。"""
        if self._H_np is None:
            return (x, y)
        pt = np.array([x, y, 1.0], dtype=np.float64)
        res = self._H_np @ pt
        return (float(res[0] / res[2]), float(res[1] / res[2]))

    def court_to_pixel(self, cx: float, cy: float) -> Tuple[float, float]:
        """コート正規化 → 画像正規化 (キャリブ無しなら passthrough)。"""
        if self._H_inv_np is None:
            return (cx, cy)
        pt = np.array([cx, cy, 1.0], dtype=np.float64)
        res = self._H_inv_np @ pt
        return (float(res[0] / res[2]), float(res[1] / res[2]))

    # ─── 動的閾値 ────────────────────────────────────────────────────────

    @property
    def front_threshold_y(self) -> float:
        """front (ネット側) 判定の画像 y 閾値。

        キャリブ済みならコート y=0.42 (= ネット y=0.5 から 0.08 ほど離れた前衛位置) を
        画像 y に逆変換した値。フォールバック時は env 由来の hard-coded 値。
        """
        if self._H_inv_np is None:
            return FALLBACK_FRONT_THRESHOLD_Y
        # コート (0.5, 0.42) を画像 y に逆射影
        _, py = self.court_to_pixel(0.5, 0.42)
        return float(np.clip(py, 0.0, 1.0))

    @property
    def back_threshold_y(self) -> float:
        """back (ベースライン側) 判定の画像 y 閾値。"""
        if self._H_inv_np is None:
            return FALLBACK_BACK_THRESHOLD_Y
        _, py = self.court_to_pixel(0.5, 0.60)
        return float(np.clip(py, 0.0, 1.0))

    @property
    def formation_min_y_diff(self) -> float:
        """前後陣判定の y 差閾値 (画像座標)。

        キャリブ済みならコート y=0.18 相当の画像 y 差を返す。
        """
        if self._H_inv_np is None:
            return FALLBACK_FORMATION_MIN_Y_DIFF
        _, top = self.court_to_pixel(0.5, 0.0)
        _, bot = self.court_to_pixel(0.5, 0.18)
        return float(abs(bot - top))

    @property
    def formation_min_x_diff(self) -> float:
        """平行陣判定の x 差閾値 (画像座標)。"""
        if self._H_inv_np is None:
            return FALLBACK_FORMATION_MIN_X_DIFF
        left, _ = self.court_to_pixel(0.0, 0.5)
        right, _ = self.court_to_pixel(0.25, 0.5)
        return float(abs(right - left))

    # ─── 高レベル分類 ────────────────────────────────────────────────────

    def depth_band(self, x_norm: float, y_norm: float) -> DepthBand:
        """画像座標から depth_band を分類する (キャリブ済みならコート座標経由)。"""
        if self._H_np is None:
            # フォールバック: 旧 court_mapper のロジック
            if y_norm < FALLBACK_FRONT_THRESHOLD_Y:
                return "front_a"
            if y_norm > FALLBACK_BACK_THRESHOLD_Y:
                return "back_b"
            return "mid"
        cx, cy = self.pixel_to_court(x_norm, y_norm)
        side = "a" if cy < 0.5 else "b"
        if cy < 1.0 / 3.0:
            return "back_a" if side == "a" else "front_a"  # 物理的に side a の back
        elif cy < 0.5:
            return "front_a"
        elif cy < 2.0 / 3.0:
            return "front_b"
        else:
            return "back_b"

    def in_court(self, x_norm: float, y_norm: float, margin: float = 0.05) -> bool:
        """点が ROI 多角形 (コート + マージン) 内か判定。"""
        if self.roi_polygon is None:
            # フォールバック: 全画面許容
            return True
        # Ray casting
        polygon = self.roi_polygon
        n = len(polygon)
        inside = False
        j = n - 1
        for i in range(n):
            xi, yi = polygon[i]
            xj, yj = polygon[j]
            if ((yi > y_norm) != (yj > y_norm)) and (
                x_norm < (xj - xi) * (y_norm - yi) / ((yj - yi) or 1e-9) + xi
            ):
                inside = not inside
            j = i
        return inside

    def formation_type(
        self,
        p1: Tuple[float, float],
        p2: Tuple[float, float],
    ) -> FormationType:
        """ダブルスペアの陣形分類 (front_back / parallel / mixed)。

        画像座標で受け取り、キャリブ済みならコート座標で計算する。
        """
        if self._H_np is None:
            dx = abs(p1[0] - p2[0])
            dy = abs(p1[1] - p2[1])
        else:
            c1 = self.pixel_to_court(*p1)
            c2 = self.pixel_to_court(*p2)
            dx = abs(c1[0] - c2[0])
            dy = abs(c1[1] - c2[1])
        # キャリブ時は court 座標、未キャリブ時は画像座標で同じ閾値ロジック
        if dy >= self.formation_min_y_diff and dy > dx:
            return "front_back"
        if dx >= self.formation_min_x_diff and dx >= dy:
            return "parallel"
        return "mixed"
