"""Track C3: SwingDetector — RTMPose 手首速度 + 肘角度から打撃フレームを検出。

3 段階ヒッター推定の Priority 1 を担う:
  - Wrist 速度 (右 or 左) が WRIST_VEL_THRESHOLD 超え
  - 同窓内で 肘角度変化が ELBOW_CHANGE_MIN 度以上
  - 両条件を満たした player を「今打った」とする

Hitter Attribution との連携 (Track C4):
  - Priority 1: SwingDetector → SwingEvent.identity = hitter (HIGH)
  - Priority 2: shuttle 位置最近傍 (MED)
  - Priority 3: review_required (LOW)

設計:
  - 入力: PoseResult のフレーム時系列 (player 単位の 履歴)
  - 出力: SwingEvent (frame_idx, identity, hand, velocity, confidence)
  - 速度・角度は **画像正規化座標基準** (0..1)。FPS で時間正規化する。
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

import numpy as np

from backend.cv.rtmpose import KP, PoseResult

logger = logging.getLogger(__name__)


@dataclass
class SwingEvent:
    """検出されたスイング (打撃) イベント。"""
    frame_idx: int
    timestamp_sec: float
    identity: str             # player_a / player_b / ...
    hand: str                  # 'right' or 'left'
    wrist_velocity: float      # 画像正規化単位/秒
    elbow_angle_change: float  # degrees
    confidence: float          # 0..1


@dataclass
class _PlayerHistory:
    """player 単位の pose 履歴 (deque で固定窓)。"""
    poses: Deque[PoseResult] = field(default_factory=deque)
    timestamps: Deque[float] = field(default_factory=deque)


class SwingDetector:
    """RTMPose の手首速度 + 肘角度変化でスイングを検出する。

    Parameters:
        fps: 動画 FPS (時間正規化に使用)
        window_seconds: 速度・角度変化を測る窓 (秒)
        wrist_vel_threshold: 画像正規化単位/秒。標準 1.5 ≈ 60fps で 0.025 px/frame 相当
        elbow_change_min: 度。肘がこの角度以上動けば swing
        min_kp_confidence: keypoint conf がこれ未満なら無視 (RTMPose unloaded で 0 のため)
        cooldown_frames: 同 player の連続発火を抑える窓
    """

    def __init__(
        self,
        *,
        fps: float = 60.0,
        window_seconds: float = 0.10,
        wrist_vel_threshold: float = 1.5,
        elbow_change_min: float = 25.0,
        min_kp_confidence: float = 0.30,
        cooldown_frames: int = 10,
    ) -> None:
        self.fps = max(fps, 1.0)
        self.window_seconds = window_seconds
        self.window_frames = max(2, int(round(window_seconds * self.fps)))
        self.wrist_vel_threshold = wrist_vel_threshold
        self.elbow_change_min = elbow_change_min
        self.min_kp_confidence = min_kp_confidence
        self.cooldown_frames = cooldown_frames

        self._history: Dict[str, _PlayerHistory] = defaultdict(_PlayerHistory)
        self._last_swing_frame: Dict[str, int] = {}

    # ─── メインエントリ ───────────────────────────────────────────────────

    def process_frame(
        self,
        frame_idx: int,
        timestamp_sec: float,
        poses: List[PoseResult],
    ) -> Optional[SwingEvent]:
        """1 フレーム分のポーズを取り込み、スイングを検出した player があれば返す。

        複数同時にスイングしている場合は confidence 最大を返す。
        """
        # 履歴更新
        for p in poses:
            ident = p.label or (f"track_{p.track_id}" if p.track_id is not None else None)
            if ident is None:
                continue
            h = self._history[ident]
            h.poses.append(p)
            h.timestamps.append(timestamp_sec)
            while len(h.poses) > self.window_frames:
                h.poses.popleft()
                h.timestamps.popleft()

        # 各 player について swing 検出
        candidates: List[SwingEvent] = []
        for ident, h in self._history.items():
            if len(h.poses) < 2:
                continue
            last = self._last_swing_frame.get(ident, -10**9)
            if frame_idx - last < self.cooldown_frames:
                continue
            ev = self._detect_swing(ident, frame_idx, timestamp_sec, h)
            if ev is not None:
                candidates.append(ev)

        if not candidates:
            return None
        winner = max(candidates, key=lambda e: e.confidence)
        self._last_swing_frame[winner.identity] = frame_idx
        return winner

    # ─── 内部 ─────────────────────────────────────────────────────────

    def _detect_swing(
        self,
        ident: str,
        frame_idx: int,
        ts: float,
        h: _PlayerHistory,
    ) -> Optional[SwingEvent]:
        best: Optional[SwingEvent] = None
        for hand_name, w_idx, e_idx, s_idx in (
            ("right", KP.R_WRIST, KP.R_ELBOW, KP.R_SHOULDER),
            ("left", KP.L_WRIST, KP.L_ELBOW, KP.L_SHOULDER),
        ):
            vel = self._wrist_peak_velocity(h, w_idx)
            angle = self._elbow_angle_change(h, s_idx, e_idx, w_idx)
            if vel < self.wrist_vel_threshold:
                continue
            if angle < self.elbow_change_min:
                continue
            conf = min(1.0, vel / (self.wrist_vel_threshold * 2.0)) * \
                   min(1.0, angle / (self.elbow_change_min * 2.0))
            ev = SwingEvent(
                frame_idx=frame_idx, timestamp_sec=ts, identity=ident,
                hand=hand_name, wrist_velocity=vel, elbow_angle_change=angle,
                confidence=conf,
            )
            if best is None or ev.confidence > best.confidence:
                best = ev
        return best

    def _wrist_peak_velocity(self, h: _PlayerHistory, w_idx: int) -> float:
        """窓内の手首速度のピーク (画像正規化単位/秒)。"""
        peak = 0.0
        last_xy = None
        last_ts = None
        for pose, ts in zip(h.poses, h.timestamps):
            kp = pose.keypoints
            if kp[w_idx, 2] < self.min_kp_confidence:
                last_xy = None
                last_ts = None
                continue
            x, y = float(kp[w_idx, 0]), float(kp[w_idx, 1])
            if last_xy is not None and last_ts is not None and ts > last_ts:
                dt = ts - last_ts
                if dt > 0:
                    dx = x - last_xy[0]
                    dy = y - last_xy[1]
                    v = math.sqrt(dx * dx + dy * dy) / dt
                    if v > peak:
                        peak = v
            last_xy = (x, y)
            last_ts = ts
        return peak

    def _elbow_angle_change(
        self,
        h: _PlayerHistory,
        s_idx: int,
        e_idx: int,
        w_idx: int,
    ) -> float:
        """窓最初と最後の肘角度の差 (度、絶対値)。"""
        first = h.poses[0].keypoints
        last = h.poses[-1].keypoints
        for kp in (first, last):
            if (kp[s_idx, 2] < self.min_kp_confidence
                    or kp[e_idx, 2] < self.min_kp_confidence
                    or kp[w_idx, 2] < self.min_kp_confidence):
                return 0.0
        a1 = self._angle_at(first, s_idx, e_idx, w_idx)
        a2 = self._angle_at(last, s_idx, e_idx, w_idx)
        return abs(a2 - a1)

    @staticmethod
    def _angle_at(kp: np.ndarray, s_idx: int, e_idx: int, w_idx: int) -> float:
        """肘 (e) 中心の shoulder-elbow-wrist 角 (度)。"""
        v1 = np.array([kp[s_idx, 0] - kp[e_idx, 0], kp[s_idx, 1] - kp[e_idx, 1]])
        v2 = np.array([kp[w_idx, 0] - kp[e_idx, 0], kp[w_idx, 1] - kp[e_idx, 1]])
        n1 = np.linalg.norm(v1)
        n2 = np.linalg.norm(v2)
        if n1 < 1e-6 or n2 < 1e-6:
            return 0.0
        cos = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
        return math.degrees(math.acos(cos))

    def reset(self) -> None:
        self._history.clear()
        self._last_swing_frame.clear()
