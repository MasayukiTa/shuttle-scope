"""TrackNet の CPU フォールバック実装 (classical CV)。

Phase A 本実装:
    - 本物の TrackNet 学習済み重みは同梱しないが、代替として OpenCV の
      古典的な画像処理でシャトル (羽根) を検出する。
    - HSV フィルタ (白〜黄) + 背景差分 (MOG2) + HoughCircles の合成で、
      フレームごとに最も確からしい 1 点を選ぶ。
    - 検出失敗フレームは前後の検出結果で線形補間する。補間できない場合は
      confidence=0.0 で (x, y) = (0, 0) を出力して呼び出し側が扱えるようにする。
    - 5060 Ti 到着後に `tracknet_cuda.py` の本物 TrackNet に差し替えるための
      インタフェース (run(video_path) -> List[ShuttleSample]) のみを固定する。

import 方針:
    - cv2 は既存モジュール (yolov8n.py など) でも使われているため、トップレベル
      import で問題ない想定。numpy も同様。
"""
from __future__ import annotations

import logging
import math
from typing import List, Optional, Tuple

import cv2
import numpy as np

from backend.cv.base import ShuttleSample, TrackNetInferencer

logger = logging.getLogger(__name__)


# シャトルコック想定サイズ (画素単位)。Full HD ベースの粗い目安。
_EXPECTED_RADIUS_PX = 8.0
_EXPECTED_AREA_PX = math.pi * (_EXPECTED_RADIUS_PX ** 2)

# HSV 閾値: 白〜黄のシャトル色域を広めに取る。
# H: 0-40 (黄側), S: 低め (白寄り), V: 高め (明るい)
_HSV_LOWER = np.array([0, 0, 180], dtype=np.uint8)
_HSV_UPPER = np.array([40, 120, 255], dtype=np.uint8)


class CpuTrackNet(TrackNetInferencer):
    """CPU (OpenCV classical CV) 経由のシャトル検出器。"""

    def __init__(
        self,
        expected_radius_px: float = _EXPECTED_RADIUS_PX,
        hough_dp: float = 1.2,
        hough_min_dist: float = 20.0,
    ) -> None:
        # コンストラクタでは重い依存を触らない (テストでの import 負荷を抑える)。
        self._expected_radius_px = float(expected_radius_px)
        self._expected_area_px = math.pi * (self._expected_radius_px ** 2)
        self._hough_dp = float(hough_dp)
        self._hough_min_dist = float(hough_min_dist)

    # ------------------------------------------------------------------
    # 公開 API
    # ------------------------------------------------------------------
    def run(self, video_path: str) -> List[ShuttleSample]:
        """動画を読み込み、各フレームのシャトル座標を推定して返す。"""
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise RuntimeError(f"動画を開けません: {video_path}")

        try:
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
            if fps <= 0.0 or not math.isfinite(fps):
                fps = 30.0

            # 背景差分器はフレーム間を通して状態を保持する。
            bg_sub = cv2.createBackgroundSubtractorMOG2(
                history=200, varThreshold=16, detectShadows=False
            )

            raw: List[Optional[Tuple[float, float, float]]] = []
            frame_idx = 0
            while True:
                ok, frame = cap.read()
                if not ok:
                    break
                raw.append(self._detect_one_frame(frame, bg_sub))
                frame_idx += 1
        finally:
            cap.release()

        # 検出失敗フレームは前後の確定結果で線形補間する。
        filled = self._interpolate_missing(raw)

        samples: List[ShuttleSample] = []
        for i, item in enumerate(filled):
            ts = i / fps
            if item is None:
                # 補間もできなかったフレームは confidence=0 で出力。
                samples.append(
                    ShuttleSample(frame=i, ts_sec=ts, x=0.0, y=0.0, confidence=0.0)
                )
            else:
                x, y, conf = item
                samples.append(
                    ShuttleSample(frame=i, ts_sec=ts, x=x, y=y, confidence=conf)
                )
        return samples

    # ------------------------------------------------------------------
    # 内部
    # ------------------------------------------------------------------
    def _detect_one_frame(
        self,
        frame: np.ndarray,
        bg_sub: "cv2.BackgroundSubtractor",
    ) -> Optional[Tuple[float, float, float]]:
        """1 フレーム分の検出。成功時 (x, y, confidence) を返す。"""
        if frame is None or frame.size == 0:
            return None

        # 1) 色マスク (白〜黄)
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        color_mask = cv2.inRange(hsv, _HSV_LOWER, _HSV_UPPER)

        # 2) 背景差分による動体マスク
        motion_mask = bg_sub.apply(frame)
        # 影抑制のため 200 以上 (= 前景のみ) を採用
        _, motion_mask = cv2.threshold(motion_mask, 200, 255, cv2.THRESH_BINARY)

        # 3) 色 AND 動体 で候補領域を絞る
        combined = cv2.bitwise_and(color_mask, motion_mask)
        combined = cv2.morphologyEx(
            combined, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)
        )

        # 4) 輪郭抽出で候補中心を得る
        contours, _ = cv2.findContours(
            combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        best: Optional[Tuple[float, float, float]] = None
        best_score = -1.0
        for cnt in contours:
            area = float(cv2.contourArea(cnt))
            if area < 2.0 or area > self._expected_area_px * 20.0:
                continue
            m = cv2.moments(cnt)
            if m["m00"] <= 0.0:
                continue
            cx = m["m10"] / m["m00"]
            cy = m["m01"] / m["m00"]
            # 面積スコア: 想定面積に近いほど高く、0..1 にクリップ。
            score = float(
                min(area, self._expected_area_px) / max(self._expected_area_px, 1.0)
            )
            if score > best_score:
                best_score = score
                best = (float(cx), float(cy), float(min(max(score, 0.0), 1.0)))

        if best is not None:
            return best

        # 5) 輪郭で取れない場合は HoughCircles で補助的に探す
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 1.2)
        circles = cv2.HoughCircles(
            gray,
            cv2.HOUGH_GRADIENT,
            dp=self._hough_dp,
            minDist=self._hough_min_dist,
            param1=80.0,
            param2=20.0,
            minRadius=max(2, int(self._expected_radius_px * 0.5)),
            maxRadius=max(4, int(self._expected_radius_px * 2.5)),
        )
        if circles is not None and len(circles) > 0:
            # 最初の 1 つを採用 (信頼度は中程度)。
            c = circles[0][0]
            return float(c[0]), float(c[1]), 0.3

        return None

    @staticmethod
    def _interpolate_missing(
        raw: List[Optional[Tuple[float, float, float]]],
    ) -> List[Optional[Tuple[float, float, float]]]:
        """None 要素を前後の確定値で線形補間する。"""
        n = len(raw)
        if n == 0:
            return raw
        # 確定インデックスを拾う
        known_idx = [i for i, v in enumerate(raw) if v is not None]
        if not known_idx:
            return raw  # 全滅: そのまま返す (呼び出し側で confidence=0 にする)

        out: List[Optional[Tuple[float, float, float]]] = list(raw)
        # 先頭の欠損は最初の確定値で埋める (confidence は低めにする)。
        first = known_idx[0]
        for i in range(0, first):
            x, y, _ = raw[first]  # type: ignore[misc]
            out[i] = (x, y, 0.1)
        # 末尾の欠損は最後の確定値で埋める。
        last = known_idx[-1]
        for i in range(last + 1, n):
            x, y, _ = raw[last]  # type: ignore[misc]
            out[i] = (x, y, 0.1)
        # 中間の欠損は両端を線形補間。
        for a, b in zip(known_idx, known_idx[1:]):
            if b - a <= 1:
                continue
            xa, ya, _ = raw[a]  # type: ignore[misc]
            xb, yb, _ = raw[b]  # type: ignore[misc]
            span = b - a
            for k in range(1, span):
                t = k / span
                out[a + k] = (
                    xa + (xb - xa) * t,
                    ya + (yb - ya) * t,
                    0.2,  # 補間は生検出より低めの信頼度
                )
        return out
