"""Track A4: OcclusionDetector + OcclusionResolver。

選手同士の遮蔽を 3 パターンで検出し、4 信号 (motion / court / reid / trajectory) を
Hungarian で融合して遮蔽後の identity を解決する。

新規価値: P3 pre-occlusion IoU は遮蔽が起きる**前**に検知して、その瞬間に
identity の reid template を凍結することで、遮蔽後のクリーンな照合が可能になる。
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from enum import Enum
from itertools import combinations
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ─── パターン定義 ─────────────────────────────────────────────────────────────

class OcclusionPattern(str, Enum):
    PLAYER_COUNT_DROP = "count_drop"        # P1: 検出人数が減少
    BBOX_EXPANSION = "bbox_expand"          # P2: 単一 bbox が異常に拡大
    PRE_OCCLUSION_IOU = "pre_occlusion"     # P3: 直前で IoU > 閾値 (新規価値)


@dataclass
class OcclusionEvent:
    """検出された遮蔽イベント。"""
    pattern: OcclusionPattern
    frame_index: int
    involved_labels: List[str]
    confidence: float = 0.5
    merged_bbox: Optional[Tuple[float, float, float, float]] = None


# ─── ヘルパー (identity_graph と重複しない範囲で) ─────────────────────────────

def _bbox_iou(b1, b2) -> float:
    if not b1 or not b2 or len(b1) != 4 or len(b2) != 4:
        return 0.0
    ix1, iy1 = max(b1[0], b2[0]), max(b1[1], b2[1])
    ix2, iy2 = min(b1[2], b2[2]), min(b1[3], b2[3])
    if ix2 <= ix1 or iy2 <= iy1:
        return 0.0
    inter = (ix2 - ix1) * (iy2 - iy1)
    a1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
    a2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
    union = a1 + a2 - inter
    return inter / union if union > 0 else 0.0


def _bbox_area(b) -> float:
    if not b or len(b) != 4:
        return 0.0
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


# ─── OcclusionDetector ───────────────────────────────────────────────────────

class OcclusionDetector:
    """3 パターンで遮蔽を検出する。

    P1 (count_drop):
        expected_players (= 4 ダブルス / 2 シングルス) を
        count_drop_patience フレーム連続で下回ったら発火。
    P2 (bbox_expand):
        ある bbox の面積が直前フレームの自分の bbox 面積の bbox_expand_ratio
        倍以上に膨らんだら、合体検出として発火。
    P3 (pre_occlusion_iou):
        2 つの bbox 間 IoU が pre_occlusion_iou_thresh を超えたら
        「これから遮蔽が起きる」シグナルとして発火。
    """

    def __init__(
        self,
        expected_players: int = 4,
        count_drop_patience: int = 3,
        bbox_expand_ratio: float = 1.5,
        pre_occlusion_iou_thresh: float = 0.3,
    ) -> None:
        self.expected_players = expected_players
        self.count_drop_patience = count_drop_patience
        self.bbox_expand_ratio = bbox_expand_ratio
        self.pre_occlusion_iou_thresh = pre_occlusion_iou_thresh
        self._low_count_streak = 0
        # track_id -> 直前フレームの bbox area
        self._prev_areas: Dict[str, float] = {}

    def detect(
        self,
        identities: Dict[str, dict],
        detections: List[dict],
        frame_index: int,
    ) -> List[OcclusionEvent]:
        events: List[OcclusionEvent] = []
        events.extend(self._check_count_drop(detections, frame_index))
        events.extend(self._check_bbox_expansion(detections, frame_index))
        events.extend(self._check_pre_occlusion_iou(identities, detections, frame_index))
        return events

    # ─── P1 ──────────────────────────────────────────────────────────────

    def _check_count_drop(
        self,
        detections: List[dict],
        frame_index: int,
    ) -> List[OcclusionEvent]:
        if len(detections) < self.expected_players:
            self._low_count_streak += 1
        else:
            self._low_count_streak = 0
        if self._low_count_streak == self.count_drop_patience:
            return [OcclusionEvent(
                pattern=OcclusionPattern.PLAYER_COUNT_DROP,
                frame_index=frame_index,
                involved_labels=[d.get("label", "?") for d in detections],
                confidence=min(1.0, (self.expected_players - len(detections)) / self.expected_players),
            )]
        return []

    # ─── P2 ──────────────────────────────────────────────────────────────

    def _check_bbox_expansion(
        self,
        detections: List[dict],
        frame_index: int,
    ) -> List[OcclusionEvent]:
        events: List[OcclusionEvent] = []
        new_areas: Dict[str, float] = {}
        for d in detections:
            label = d.get("label", "?")
            bbox = d.get("bbox", [])
            area = _bbox_area(bbox)
            new_areas[label] = area
            prev = self._prev_areas.get(label)
            if prev is not None and prev > 0 and area / prev >= self.bbox_expand_ratio:
                events.append(OcclusionEvent(
                    pattern=OcclusionPattern.BBOX_EXPANSION,
                    frame_index=frame_index,
                    involved_labels=[label],
                    confidence=min(1.0, (area / prev - 1.0) / 2.0),
                    merged_bbox=tuple(bbox) if len(bbox) == 4 else None,
                ))
        self._prev_areas = new_areas
        return events

    # ─── P3 (新規価値) ───────────────────────────────────────────────────

    def _check_pre_occlusion_iou(
        self,
        identities: Dict[str, dict],
        detections: List[dict],
        frame_index: int,
    ) -> List[OcclusionEvent]:
        events: List[OcclusionEvent] = []
        # 全ペアの IoU をチェック
        det_pairs = list(combinations(detections, 2))
        for a, b in det_pairs:
            iou = _bbox_iou(a.get("bbox", []), b.get("bbox", []))
            if iou >= self.pre_occlusion_iou_thresh:
                events.append(OcclusionEvent(
                    pattern=OcclusionPattern.PRE_OCCLUSION_IOU,
                    frame_index=frame_index,
                    involved_labels=[a.get("label", "?"), b.get("label", "?")],
                    confidence=iou,
                ))
        return events

    def reset(self) -> None:
        self._low_count_streak = 0
        self._prev_areas = {}


# ─── OcclusionResolver: 4 信号 Hungarian ──────────────────────────────────────

@dataclass
class ResolverSignals:
    """4 信号それぞれの重み (合計 1.0)。"""
    motion: float = 0.30
    court: float = 0.20
    reid: float = 0.35
    trajectory: float = 0.15


class OcclusionResolver:
    """遮蔽後の identity 割当を 4 信号融合 + Hungarian で解決する。

    Signals:
      1. motion: 直前速度からの線形外挿位置との距離 (近いほど高得点)
      2. court: コート半面の正当性 (自陣に居るべき選手が相手陣に出ない)
      3. reid: 凍結 ReID テンプレートとの cos 類似度
      4. trajectory: 遮蔽前の移動方向と一貫しているか (内積)

    全信号は [0, 1] に正規化し、weighted sum で identity x detection の
    score 行列を作る。1 - score を cost として scipy Hungarian (linear_sum_assignment)
    で最適割当。scipy が無い環境では貪欲フォールバック。
    """

    def __init__(
        self,
        weights: Optional[ResolverSignals] = None,
        min_score: float = 0.3,
    ) -> None:
        self.weights = weights or ResolverSignals()
        self.min_score = min_score

    def resolve(
        self,
        occluded_identities: List[dict],
        new_detections: List[dict],
        court_adapter=None,
    ) -> Dict[int, str]:
        """detections に identity label を割り当てる。

        Args:
            occluded_identities: [{"label": str, "last_bbox": [x1,y1,x2,y2],
                                   "vel_cx": float, "vel_cy": float,
                                   "frozen_reid": list, "team": "near"|"far"|None}, ...]
            new_detections: [{"bbox": [...], "hist": [...], "track_id": ...}, ...]
            court_adapter: optional CourtAdapter (court 制約信号で使用)

        Returns:
            {detection_index: label}
        """
        if not occluded_identities or not new_detections:
            return {}

        n_id = len(occluded_identities)
        n_det = len(new_detections)
        score = [[0.0] * n_det for _ in range(n_id)]

        for i, ident in enumerate(occluded_identities):
            for j, det in enumerate(new_detections):
                s_motion = self._score_motion(ident, det)
                s_court = self._score_court(ident, det, court_adapter)
                s_reid = self._score_reid(ident, det)
                s_traj = self._score_trajectory(ident, det)
                score[i][j] = (
                    self.weights.motion * s_motion
                    + self.weights.court * s_court
                    + self.weights.reid * s_reid
                    + self.weights.trajectory * s_traj
                )

        return self._assign(score, occluded_identities, new_detections)

    # ─── 信号 ────────────────────────────────────────────────────────────

    @staticmethod
    def _bbox_center(b) -> Tuple[float, float]:
        if not b or len(b) != 4:
            return (0.5, 0.5)
        return ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)

    def _score_motion(self, ident: dict, det: dict) -> float:
        last = ident.get("last_bbox")
        if not last:
            return 0.5
        lcx, lcy = self._bbox_center(last)
        vx = ident.get("vel_cx", 0.0) or 0.0
        vy = ident.get("vel_cy", 0.0) or 0.0
        # 1 フレーム後の予測位置
        px, py = lcx + vx, lcy + vy
        dcx, dcy = self._bbox_center(det.get("bbox", []))
        dist = math.sqrt((px - dcx) ** 2 + (py - dcy) ** 2)
        # 距離 0 → 1.0、距離 0.5 → 0.0 で線形減衰
        return max(0.0, 1.0 - dist / 0.5)

    def _score_court(self, ident: dict, det: dict, court_adapter) -> float:
        team = ident.get("team")
        if team is None:
            return 0.5
        cy = self._bbox_center(det.get("bbox", []))[1]
        # near (自陣 y > 0.5) / far (相手陣 y < 0.5) の判定
        if court_adapter is not None and getattr(court_adapter, "is_calibrated", False):
            try:
                _, ccy = court_adapter.pixel_to_court(0.5, cy)
                cy = ccy
            except Exception:
                pass
        in_correct_half = (
            (team == "near" and cy > 0.5)
            or (team == "far" and cy < 0.5)
        )
        return 1.0 if in_correct_half else 0.1

    def _score_reid(self, ident: dict, det: dict) -> float:
        tmpl = ident.get("frozen_reid") or ident.get("reid_template")
        feat = det.get("hist") or []
        if not tmpl or not feat or len(tmpl) != len(feat):
            return 0.5  # neutral
        dot = sum(x * y for x, y in zip(tmpl, feat))
        na = sum(x * x for x in tmpl) ** 0.5
        nb = sum(y * y for y in feat) ** 0.5
        if na <= 0 or nb <= 0:
            return 0.5
        return max(0.0, min(1.0, dot / (na * nb)))

    def _score_trajectory(self, ident: dict, det: dict) -> float:
        last = ident.get("last_bbox")
        if not last:
            return 0.5
        vx = ident.get("vel_cx", 0.0) or 0.0
        vy = ident.get("vel_cy", 0.0) or 0.0
        v_mag = math.sqrt(vx * vx + vy * vy)
        if v_mag < 1e-6:
            return 0.5
        lcx, lcy = self._bbox_center(last)
        dcx, dcy = self._bbox_center(det.get("bbox", []))
        dx, dy = dcx - lcx, dcy - lcy
        d_mag = math.sqrt(dx * dx + dy * dy)
        if d_mag < 1e-6:
            return 0.5
        cosine = (vx * dx + vy * dy) / (v_mag * d_mag)
        return (cosine + 1.0) / 2.0

    # ─── 割当 ────────────────────────────────────────────────────────────

    def _assign(
        self,
        score: List[List[float]],
        identities: List[dict],
        detections: List[dict],
    ) -> Dict[int, str]:
        n_id = len(identities)
        n_det = len(detections)
        # cost = -score (Hungarian は最小化)
        try:
            from scipy.optimize import linear_sum_assignment
            import numpy as np
            cost = np.array(score, dtype=float) * -1.0
            row_ind, col_ind = linear_sum_assignment(cost)
            result: Dict[int, str] = {}
            for r, c in zip(row_ind, col_ind):
                if r < n_id and c < n_det and score[r][c] >= self.min_score:
                    result[int(c)] = identities[r]["label"]
            return result
        except Exception:
            # 貪欲フォールバック
            pairs = [
                (-score[i][j], i, j)
                for i in range(n_id)
                for j in range(n_det)
                if score[i][j] >= self.min_score
            ]
            pairs.sort(key=lambda x: x[0])
            used_i: set = set()
            used_j: set = set()
            result_g: Dict[int, str] = {}
            for _c, i, j in pairs:
                if i in used_i or j in used_j:
                    continue
                result_g[int(j)] = identities[i]["label"]
                used_i.add(i)
                used_j.add(j)
            return result_g
