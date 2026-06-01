"""Standalone ByteTracker 実装。

ultralytics の AGPL コードに依存せず、ByteTrack 論文
(Zhang et al., ECCV 2022) の核となる以下の手順を独立に実装する:

  1. 検出を high-conf / low-conf の 2 グループに分離
  2. 既存 track の Kalman 予測 → high-conf detections と IoU マッチ
     (Hungarian, scipy.optimize.linear_sum_assignment)
  3. 残った既存 track と low-conf detections で 2 回目マッチ
  4. 未マッチ既存 track は lost、buffer 期間内は復活可能
  5. 未マッチ high-conf detections は新規 track として起こす

依存: numpy, scipy のみ。torch / lap / cython_bbox は不要。
ライセンス: 本ファイルは MIT (shuttlescope 本体と同じ)。

公開クラス:
  - ByteTracker  : tracker 本体
  - STrack       : track state (Kalman filter 付き)
  - Detection    : 入力フォーマット (x1,y1,x2,y2,score)

注: 設計書 2026-05-27_person_tracking_design.md および backend/yolo/bytetrack.yaml
の閾値 (track_high_thresh=0.25, track_low_thresh=0.10, new_track_thresh=0.25,
track_buffer=120, match_thresh=0.8) をデフォルトとして採用する。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np


# ── 入力 dataclass ──────────────────────────────────────────────────────
@dataclass
class Detection:
    """1 検出。x1,y1,x2,y2 は pixel、score は 0-1。"""
    bbox: tuple[float, float, float, float]
    score: float


# ── Kalman filter (constant-velocity, 8 state) ───────────────────────────
class _KalmanFilter:
    """SORT/ByteTrack 流の 8 次元 constant-velocity Kalman。

    state = [cx, cy, a, h, vcx, vcy, va, vh]
      a = aspect ratio (w / h)、h = height
    観測 = [cx, cy, a, h]

    実装は SORT (https://github.com/abewley/sort) を参考に独立実装。
    """

    def __init__(self) -> None:
        ndim = 4
        dt = 1.0
        # 遷移行列 F
        self._motion_mat = np.eye(2 * ndim, dtype=np.float64)
        for i in range(ndim):
            self._motion_mat[i, ndim + i] = dt
        # 観測行列 H
        self._update_mat = np.eye(ndim, 2 * ndim, dtype=np.float64)
        # ノイズ重み (SORT と同じ経験値)
        self._std_weight_position = 1.0 / 20.0
        self._std_weight_velocity = 1.0 / 160.0

    def initiate(self, measurement: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        mean_pos = measurement
        mean_vel = np.zeros_like(mean_pos)
        mean = np.r_[mean_pos, mean_vel]
        std = [
            2 * self._std_weight_position * measurement[3],
            2 * self._std_weight_position * measurement[3],
            1e-2,
            2 * self._std_weight_position * measurement[3],
            10 * self._std_weight_velocity * measurement[3],
            10 * self._std_weight_velocity * measurement[3],
            1e-5,
            10 * self._std_weight_velocity * measurement[3],
        ]
        covariance = np.diag(np.square(std))
        return mean, covariance

    def predict(self, mean: np.ndarray, covariance: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        std_pos = [
            self._std_weight_position * mean[3],
            self._std_weight_position * mean[3],
            1e-2,
            self._std_weight_position * mean[3],
        ]
        std_vel = [
            self._std_weight_velocity * mean[3],
            self._std_weight_velocity * mean[3],
            1e-5,
            self._std_weight_velocity * mean[3],
        ]
        motion_cov = np.diag(np.square(np.r_[std_pos, std_vel]))
        mean = self._motion_mat @ mean
        covariance = self._motion_mat @ covariance @ self._motion_mat.T + motion_cov
        return mean, covariance

    def update(
        self, mean: np.ndarray, covariance: np.ndarray, measurement: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        std = [
            self._std_weight_position * mean[3],
            self._std_weight_position * mean[3],
            1e-1,
            self._std_weight_position * mean[3],
        ]
        innovation_cov = np.diag(np.square(std))
        projected_mean = self._update_mat @ mean
        projected_cov = self._update_mat @ covariance @ self._update_mat.T + innovation_cov
        # Kalman gain (cholesky 安定化版は scipy 必要なので素直に inv)
        kalman_gain = covariance @ self._update_mat.T @ np.linalg.inv(projected_cov)
        innovation = measurement - projected_mean
        new_mean = mean + kalman_gain @ innovation
        new_cov = covariance - kalman_gain @ self._update_mat @ covariance
        return new_mean, new_cov


# ── STrack ──────────────────────────────────────────────────────────────
_shared_kf = _KalmanFilter()


class STrack:
    """Single object track。Kalman で predict、update、bbox xyxy 出力。

    state 'tracked'  : 直近フレームで matched
    state 'lost'     : 一時的に matched しなかった (buffer 内なら復活可)
    state 'removed'  : buffer 切れ
    """

    _next_id = 1

    @classmethod
    def reset_id(cls) -> None:
        cls._next_id = 1

    def __init__(self, bbox_xyxy: tuple[float, float, float, float], score: float):
        self.score = float(score)
        self._mean: Optional[np.ndarray] = None
        self._covariance: Optional[np.ndarray] = None
        self.track_id: int = -1
        self.state: str = "new"
        self.start_frame: int = 0
        self.frame_id: int = 0
        self.tracklet_len: int = 0
        self.is_activated: bool = False
        self._set_bbox(bbox_xyxy)

    def _set_bbox(self, xyxy: tuple[float, float, float, float]) -> None:
        x1, y1, x2, y2 = xyxy
        w = max(x2 - x1, 1e-6)
        h = max(y2 - y1, 1e-6)
        self._cxcyah = np.array([x1 + w / 2, y1 + h / 2, w / h, h], dtype=np.float64)

    @property
    def xyxy(self) -> tuple[float, float, float, float]:
        if self._mean is None:
            cx, cy, a, h = self._cxcyah
        else:
            cx, cy, a, h = self._mean[:4]
        w = a * h
        return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)

    def activate(self, frame_id: int) -> None:
        self.track_id = STrack._next_id
        STrack._next_id += 1
        self._mean, self._covariance = _shared_kf.initiate(self._cxcyah)
        self.tracklet_len = 0
        self.state = "tracked"
        self.frame_id = frame_id
        self.start_frame = frame_id
        # 最初のフレームでは is_activated=False、2 frame 目以降の matched で True
        self.is_activated = frame_id == 0

    def re_activate(self, new_track: "STrack", frame_id: int, new_id: bool = False) -> None:
        assert self._mean is not None and self._covariance is not None
        self._mean, self._covariance = _shared_kf.update(
            self._mean, self._covariance, new_track._cxcyah
        )
        self.tracklet_len = 0
        self.state = "tracked"
        self.is_activated = True
        self.frame_id = frame_id
        if new_id:
            self.track_id = STrack._next_id
            STrack._next_id += 1
        self.score = new_track.score

    def predict(self) -> None:
        if self._mean is None or self._covariance is None:
            return
        mean = self._mean.copy()
        # lost 中は速度成分を 0 に倒すと暴走しない
        if self.state != "tracked":
            mean[6] = 0.0
            mean[7] = 0.0
        self._mean, self._covariance = _shared_kf.predict(mean, self._covariance)

    def update(self, new_track: "STrack", frame_id: int) -> None:
        assert self._mean is not None and self._covariance is not None
        self.frame_id = frame_id
        self.tracklet_len += 1
        self._mean, self._covariance = _shared_kf.update(
            self._mean, self._covariance, new_track._cxcyah
        )
        self.state = "tracked"
        self.is_activated = True
        self.score = new_track.score

    def mark_lost(self) -> None:
        self.state = "lost"

    def mark_removed(self) -> None:
        self.state = "removed"


# ── IoU マトリクス ──────────────────────────────────────────────────────
def _ious(atracks: list[STrack], btracks: list[STrack]) -> np.ndarray:
    """各 STrack の現 xyxy 同士の IoU 行列を返す (a x b)。"""
    if not atracks or not btracks:
        return np.zeros((len(atracks), len(btracks)), dtype=np.float64)
    a = np.array([t.xyxy for t in atracks], dtype=np.float64)
    b = np.array([t.xyxy for t in btracks], dtype=np.float64)
    # 交差面積
    tl = np.maximum(a[:, None, :2], b[None, :, :2])
    br = np.minimum(a[:, None, 2:], b[None, :, 2:])
    wh = np.clip(br - tl, 0, None)
    inter = wh[..., 0] * wh[..., 1]
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return inter / np.maximum(union, 1e-9)


def _linear_assignment(
    cost_matrix: np.ndarray, thresh: float
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """cost (= 1 - iou) を Hungarian で最小化。thresh 超え (= iou < 1-thresh) は捨てる。

    返り値: (matches, unmatched_a, unmatched_b)
    """
    if cost_matrix.size == 0:
        return [], list(range(cost_matrix.shape[0])), list(range(cost_matrix.shape[1]))
    from scipy.optimize import linear_sum_assignment
    row_ind, col_ind = linear_sum_assignment(cost_matrix)
    matches: list[tuple[int, int]] = []
    used_a: set[int] = set()
    used_b: set[int] = set()
    for r, c in zip(row_ind, col_ind):
        if cost_matrix[r, c] <= thresh:
            matches.append((int(r), int(c)))
            used_a.add(int(r))
            used_b.add(int(c))
    unmatched_a = [i for i in range(cost_matrix.shape[0]) if i not in used_a]
    unmatched_b = [j for j in range(cost_matrix.shape[1]) if j not in used_b]
    return matches, unmatched_a, unmatched_b


# ── ByteTracker 本体 ────────────────────────────────────────────────────
class ByteTracker:
    """ByteTrack algorithm の standalone 実装。

    Args:
        track_high_thresh: high-conf detection の下限。
        track_low_thresh : low-conf detection の下限 (1st pass 漏れの救済に使う)。
        new_track_thresh : 新規 track を起こす最小 score。
        track_buffer     : lost 状態を保持するフレーム数。
        match_thresh_high: 1st pass の IoU 一致しきい値 (cost = 1 - iou)。
        match_thresh_low : 2nd pass 用 (low-conf det との).
        match_thresh_unconfirmed: 起動中 track と new det の一致しきい値。
    """

    def __init__(
        self,
        track_high_thresh: float = 0.25,
        track_low_thresh: float = 0.10,
        new_track_thresh: float = 0.25,
        track_buffer: int = 120,
        match_thresh_high: float = 0.8,
        match_thresh_low: float = 0.5,
        match_thresh_unconfirmed: float = 0.7,
    ):
        self.track_high_thresh = track_high_thresh
        self.track_low_thresh = track_low_thresh
        self.new_track_thresh = new_track_thresh
        self.track_buffer = track_buffer
        self.match_thresh_high = match_thresh_high
        self.match_thresh_low = match_thresh_low
        self.match_thresh_unconfirmed = match_thresh_unconfirmed

        self._tracked: list[STrack] = []   # state=tracked
        self._lost: list[STrack] = []      # state=lost
        self._removed: list[STrack] = []   # state=removed (GC 待ち)
        self._frame_id = 0
        STrack.reset_id()

    def reset(self) -> None:
        """セット間などで内部 state を完全リセット。"""
        self._tracked.clear()
        self._lost.clear()
        self._removed.clear()
        self._frame_id = 0
        STrack.reset_id()

    def update(self, detections: list[Detection], frame_id: Optional[int] = None) -> list[STrack]:
        """1 フレーム処理。tracked 状態かつ is_activated=True の STrack list を返す。"""
        if frame_id is None:
            self._frame_id += 1
        else:
            self._frame_id = int(frame_id)

        # detection を high / low に分離
        dets_high: list[STrack] = []
        dets_low: list[STrack] = []
        for d in detections:
            if d.score >= self.track_high_thresh:
                dets_high.append(STrack(d.bbox, d.score))
            elif d.score >= self.track_low_thresh:
                dets_low.append(STrack(d.bbox, d.score))

        # 既存 track を tracked / unconfirmed (未起動) に分けて predict
        unconfirmed: list[STrack] = []
        tracked: list[STrack] = []
        for t in self._tracked:
            if t.is_activated:
                tracked.append(t)
            else:
                unconfirmed.append(t)

        pool = tracked + self._lost
        for t in pool:
            t.predict()

        # ── Step 1: high-conf det と pool の Hungarian ──
        iou_mat = _ious(pool, dets_high)
        cost = 1.0 - iou_mat
        matches, u_pool, u_det_high = _linear_assignment(cost, 1.0 - self.match_thresh_high)
        for ip, idh in matches:
            track = pool[ip]
            det = dets_high[idh]
            if track.state == "tracked":
                track.update(det, self._frame_id)
            else:  # lost → revive
                track.re_activate(det, self._frame_id, new_id=False)

        # ── Step 2: 残った tracked と low-conf det を 2nd pass ──
        # (Step 1 未マッチの pool のうち、state=tracked のもののみ対象)
        remaining_tracked_idx = [i for i in u_pool if pool[i].state == "tracked"]
        remaining_tracked = [pool[i] for i in remaining_tracked_idx]
        iou_mat2 = _ious(remaining_tracked, dets_low)
        cost2 = 1.0 - iou_mat2
        matches2, u_rt2, u_det_low = _linear_assignment(cost2, 1.0 - self.match_thresh_low)
        for ir, idl in matches2:
            track = remaining_tracked[ir]
            det = dets_low[idl]
            track.update(det, self._frame_id)
        # 2nd pass でも未マッチの tracked → lost
        for ir in u_rt2:
            t = remaining_tracked[ir]
            if t.state == "tracked":
                t.mark_lost()

        # 元々 lost のままで Step 1 にも引っかからなかった track はそのまま lost 継続
        # (state は既に lost なので追加処理不要)

        # ── Step 3: unconfirmed と Step 1 未マッチ high-conf det ──
        u_det_high_pool = [dets_high[i] for i in u_det_high]
        iou_mat3 = _ious(unconfirmed, u_det_high_pool)
        cost3 = 1.0 - iou_mat3
        matches3, u_unconf, u_det_high2 = _linear_assignment(
            cost3, 1.0 - self.match_thresh_unconfirmed
        )
        for iu, idh in matches3:
            track = unconfirmed[iu]
            det = u_det_high_pool[idh]
            track.update(det, self._frame_id)
        for iu in u_unconf:
            track = unconfirmed[iu]
            track.mark_removed()

        # ── Step 4: 残った high-conf det を新規 track として起こす ──
        for i in u_det_high2:
            det = u_det_high_pool[i]
            if det.score < self.new_track_thresh:
                continue
            det.activate(self._frame_id)
            # 1 フレーム目に限り即 activated。それ以外は次フレームで matched して初活性化
            if self._frame_id == 1 or self._frame_id == 0:
                det.is_activated = True
            self._tracked.append(det)

        # ── Step 5: 状態リスト再構築 ──
        new_tracked: list[STrack] = []
        new_lost: list[STrack] = []
        for t in self._tracked:
            if t.state == "tracked":
                new_tracked.append(t)
            elif t.state == "lost":
                new_lost.append(t)
            # removed は drop
        for t in self._lost:
            if t.state == "tracked":
                new_tracked.append(t)  # re_activate された
            elif t.state == "lost":
                # buffer 期限切れチェック
                if self._frame_id - t.frame_id > self.track_buffer:
                    t.mark_removed()
                else:
                    new_lost.append(t)
        # 一意化 (re_activate された track が両方に居る可能性)
        seen_ids: set[int] = set()
        dedup_tracked: list[STrack] = []
        for t in new_tracked:
            if t.track_id in seen_ids:
                continue
            seen_ids.add(t.track_id)
            dedup_tracked.append(t)
        new_lost = [t for t in new_lost if t.track_id not in seen_ids]

        self._tracked = dedup_tracked
        self._lost = new_lost

        return [t for t in self._tracked if t.is_activated]
