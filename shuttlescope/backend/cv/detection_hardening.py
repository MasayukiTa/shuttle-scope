"""Track C5: NetAwareDetector + CourtBoundedFilter

YOLO 検出結果のクリーニング層:

  - **NetAwareDetector**: ネット帯域 (コート y ≈ 0.5 付近の薄い帯) で
    confidence threshold を緩和し、加えて y 方向に分断された bbox を
    1 体として統合する。far side の選手検出が消える/分断される問題を解消。

  - **CourtBoundedFilter**: コート ROI 外 + 審判席ゾーンの検出を排除。
    bbox 面積の常識的範囲外 (極小ノイズ / 異常巨大) も排除。track_id 単位の
    持続性 (N フレーム連続検出) も任意で要求できる。

両モジュールとも `CourtAdapter` (Track A2) があれば動的に動作し、なければ
画像正規化座標の hard-coded フォールバックで動作する (退化なし)。
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─── ヘルパー ────────────────────────────────────────────────────────────────

def _bbox_area_norm(bbox: List[float]) -> float:
    if not bbox or len(bbox) != 4:
        return 0.0
    return max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])


def _bbox_y_overlap_ratio(a: List[float], b: List[float]) -> float:
    """2 bbox の x 方向重なり比率 (IoU の x 軸版)。"""
    if not a or not b or len(a) != 4 or len(b) != 4:
        return 0.0
    overlap = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    union = max(a[2], b[2]) - min(a[0], b[0])
    if union <= 0:
        return 0.0
    return overlap / union


def _bbox_y_gap(a: List[float], b: List[float]) -> float:
    """2 bbox の y 方向 gap (画像正規化, 重なっていれば 0)。"""
    if not a or not b or len(a) != 4 or len(b) != 4:
        return 1.0
    return max(0.0, max(a[1], b[1]) - min(a[3], b[3]))


# ─── NetAwareDetector ────────────────────────────────────────────────────────

class NetAwareDetector:
    """ネット帯域での YOLO 検出を補正する。

    動作:
      1. コート y ≈ 0.5 ± net_band_half_court の帯域を「ネット帯域」と定義
      2. 帯域内検出は confidence_threshold = net_conf_threshold (緩い)、
         帯域外は normal_conf_threshold で篩い分け
      3. ネット帯域内で x 方向に重なり、y 方向に小 gap で分断されている
         bbox ペアを 1 体として統合 (外接矩形 + max conf)

    入力 detection は dict: {"bbox": [x1,y1,x2,y2], "confidence": float, ...}
    """

    def __init__(
        self,
        court_adapter=None,
        *,
        net_band_court_y: Tuple[float, float] = (-0.08, 0.08),  # m 相当 (court [0,1] 系では ±0.08)
        net_conf_threshold: float = 0.30,
        normal_conf_threshold: float = 0.50,
        merge_x_overlap: float = 0.6,
        merge_y_gap_max: float = 0.04,
    ) -> None:
        self.court_adapter = court_adapter
        self.net_band_court_y = net_band_court_y
        self.net_conf_threshold = net_conf_threshold
        self.normal_conf_threshold = normal_conf_threshold
        self.merge_x_overlap = merge_x_overlap
        self.merge_y_gap_max = merge_y_gap_max

    # ─── 帯域判定 ────────────────────────────────────────────────────────

    def _net_band_image_y(self) -> Tuple[float, float]:
        """ネット帯域のピクセル y 範囲 (キャリブ無しは 0.45-0.55 デフォルト)。"""
        if self.court_adapter is not None and getattr(self.court_adapter, "is_calibrated", False):
            try:
                _, py_top = self.court_adapter.court_to_pixel(0.5, 0.5 + self.net_band_court_y[0])
                _, py_bot = self.court_adapter.court_to_pixel(0.5, 0.5 + self.net_band_court_y[1])
                return (min(py_top, py_bot), max(py_top, py_bot))
            except Exception:
                pass
        # フォールバック: 画像中央 ±5%
        return (0.45, 0.55)

    def is_in_net_band(self, bbox: List[float]) -> bool:
        if not bbox or len(bbox) != 4:
            return False
        cy = (bbox[1] + bbox[3]) / 2
        py_min, py_max = self._net_band_image_y()
        return py_min <= cy <= py_max

    # ─── フィルタ + マージ ───────────────────────────────────────────────

    def filter(self, detections: List[dict]) -> List[dict]:
        """confidence 篩い分け + ネット帯域内 bbox 統合。"""
        survivors: List[dict] = []
        for d in detections:
            bbox = d.get("bbox", [])
            conf = d.get("confidence", 0.0)
            in_net = self.is_in_net_band(bbox)
            thresh = self.net_conf_threshold if in_net else self.normal_conf_threshold
            if conf >= thresh:
                survivors.append(d)
        return self._merge_split_in_net_band(survivors)

    def _merge_split_in_net_band(self, dets: List[dict]) -> List[dict]:
        net_dets = [d for d in dets if self.is_in_net_band(d.get("bbox", []))]
        non_net = [d for d in dets if not self.is_in_net_band(d.get("bbox", []))]

        merged: List[dict] = []
        used: set = set()
        for i, a in enumerate(net_dets):
            if i in used:
                continue
            ba = a.get("bbox", [])
            grouped = [a]
            for j in range(i + 1, len(net_dets)):
                if j in used:
                    continue
                b = net_dets[j]
                bb = b.get("bbox", [])
                x_iou = _bbox_y_overlap_ratio(ba, bb)
                y_gap = _bbox_y_gap(ba, bb)
                if x_iou >= self.merge_x_overlap and y_gap <= self.merge_y_gap_max:
                    grouped.append(b)
                    used.add(j)
            if len(grouped) == 1:
                merged.append(a)
            else:
                # 外接矩形 + max confidence
                xs = [g["bbox"][0] for g in grouped] + [g["bbox"][2] for g in grouped]
                ys = [g["bbox"][1] for g in grouped] + [g["bbox"][3] for g in grouped]
                merged.append({
                    **a,
                    "bbox": [min(xs), min(ys), max(xs), max(ys)],
                    "confidence": max(g.get("confidence", 0.0) for g in grouped),
                    "merged_from": len(grouped),
                })
            used.add(i)
        return non_net + merged


# ─── CourtBoundedFilter ──────────────────────────────────────────────────────

class CourtBoundedFilter:
    """コート ROI + 審判席 + サイズ + 持続性でノイズ検出を排除する。

    パラメータ:
      court_margin: コート外側マージン (画像正規化、外側にこの分まで許容)
      umpire_zone_y: 審判席 y 範囲 (画像正規化)。範囲内 + 中央付近の検出を排除
      umpire_zone_x: 審判席 x 範囲
      min_area / max_area: bbox 面積の許容範囲 (画像正規化、area = w*h)
      persistence_frames: track_id 単位で連続検出フレーム数がこれ未満なら排除
                          (0 = 持続性チェックなし)
    """

    def __init__(
        self,
        court_adapter=None,
        *,
        court_margin: float = 0.05,
        umpire_zone_y: Tuple[float, float] = (0.92, 1.0),
        umpire_zone_x: Tuple[float, float] = (0.40, 0.60),
        min_area: float = 0.0008,   # 0.028 x 0.028 程度 = 遠景の小さな点
        max_area: float = 0.50,
        persistence_frames: int = 0,
    ) -> None:
        self.court_adapter = court_adapter
        self.court_margin = court_margin
        self.umpire_zone_y = umpire_zone_y
        self.umpire_zone_x = umpire_zone_x
        self.min_area = min_area
        self.max_area = max_area
        self.persistence_frames = max(0, persistence_frames)
        self._track_seen: Dict[int, int] = defaultdict(int)

    # ─── 個別判定 ────────────────────────────────────────────────────────

    def _bbox_center(self, bbox: List[float]) -> Tuple[float, float]:
        return ((bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2)

    def is_in_court(self, bbox: List[float]) -> bool:
        if not bbox or len(bbox) != 4:
            return False
        cx, cy = self._bbox_center(bbox)
        if self.court_adapter is not None:
            return self.court_adapter.in_court(cx, cy, margin=self.court_margin)
        # フォールバック: 画像端マージン
        return (
            self.court_margin <= cx <= 1.0 - self.court_margin
            and self.court_margin <= cy <= 1.0 - self.court_margin
        )

    def is_in_umpire_zone(self, bbox: List[float]) -> bool:
        if not bbox or len(bbox) != 4:
            return False
        cx, cy = self._bbox_center(bbox)
        return (
            self.umpire_zone_x[0] <= cx <= self.umpire_zone_x[1]
            and self.umpire_zone_y[0] <= cy <= self.umpire_zone_y[1]
        )

    def is_valid_size(self, bbox: List[float]) -> bool:
        area = _bbox_area_norm(bbox)
        return self.min_area <= area <= self.max_area

    # ─── メインフィルタ ──────────────────────────────────────────────────

    def filter(self, detections: List[dict]) -> List[dict]:
        valid: List[dict] = []
        seen_ids: set = set()
        for d in detections:
            bbox = d.get("bbox", [])
            if not self.is_in_court(bbox):
                continue
            if self.is_in_umpire_zone(bbox):
                continue
            if not self.is_valid_size(bbox):
                continue
            tid = d.get("track_id")
            if tid is not None:
                self._track_seen[tid] += 1
                seen_ids.add(tid)
                if self.persistence_frames > 0 and self._track_seen[tid] < self.persistence_frames:
                    continue
            valid.append(d)
        # 出現しなくなった track_id のカウンタをクリア (持続性 reset)
        if self.persistence_frames > 0:
            stale = [t for t in self._track_seen if t not in seen_ids]
            for t in stale:
                del self._track_seen[t]
        return valid

    def reset(self) -> None:
        self._track_seen = defaultdict(int)
