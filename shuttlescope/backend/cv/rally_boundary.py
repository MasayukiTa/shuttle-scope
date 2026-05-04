"""Track A5: RallyBoundaryDetector — ラリー境界の自動推定。

3 つの CV 信号を AND で集約してラリー終了を判定する:
  - shuttle 信号: TrackNet confidence が連続 N フレーム閾値以下
  - player 信号: 全選手の移動速度が閾値以下 (静止)
  - serve 信号: 1 選手がサーブゾーン内に入った (≒ 次ラリー準備)

オフライン (バッチ処理後) で使い、検出されたラリー境界は
**suggested として CVAssistPanel で人間が確認** する想定。
**自動でラリーを切らない** (退化リスクゼロ)。
"""
from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Literal, Optional, Tuple

logger = logging.getLogger(__name__)


BoundaryKind = Literal["start", "end"]


@dataclass
class RallyBoundary:
    """検出されたラリー境界。"""
    kind: BoundaryKind
    frame_index: int
    timestamp_sec: float
    confidence: float
    signals_fired: List[str] = field(default_factory=list)


class RallyBoundaryDetector:
    """3 信号 AND でラリー境界を自動検出する。

    使い方:
        det = RallyBoundaryDetector(fps=60.0)
        for frame in batch_frames:
            ev = det.process_frame(...)
            if ev:
                yield ev
        boundaries = det.boundaries

    パラメータ:
        fps: 動画 FPS。秒ベースの閾値を frame ベースに換算する。
        shuttle_missing_seconds: shuttle 信号がこの秒数連続で発火 → ラリー終了候補。
        shuttle_conf_thresh: TrackNet confidence < この値で「shuttle 不在」とみなす。
        player_static_seconds: 全選手がこの秒数連続で静止 → player 信号 ON。
        player_static_speed: フレーム間の移動量がこの値以下なら静止扱い (画像正規化)。
        serve_zone_y_range: サーブ位置の y 範囲 (画像正規化、ベースライン側)。
        serve_zone_x_range: サーブ位置の x 範囲。
        min_signals: AND 条件で発火に必要な信号数 (デフォルト 2 = 緩め)。
        min_rally_seconds: 短すぎるラリーを ignore するための最低継続秒。
    """

    def __init__(
        self,
        *,
        fps: float = 60.0,
        shuttle_missing_seconds: float = 0.5,
        shuttle_conf_thresh: float = 0.30,
        player_static_seconds: float = 0.4,
        player_static_speed: float = 0.005,
        serve_zone_y_range: Tuple[float, float] = (0.78, 1.0),
        serve_zone_x_range: Tuple[float, float] = (0.20, 0.80),
        min_signals: int = 2,
        min_rally_seconds: float = 0.5,
    ) -> None:
        self.fps = max(fps, 1.0)
        self.shuttle_missing_frames = max(1, int(shuttle_missing_seconds * self.fps))
        self.shuttle_conf_thresh = shuttle_conf_thresh
        self.player_static_frames = max(1, int(player_static_seconds * self.fps))
        self.player_static_speed = player_static_speed
        self.serve_zone_y_range = serve_zone_y_range
        self.serve_zone_x_range = serve_zone_x_range
        self.min_signals = max(1, min_signals)
        self.min_rally_frames = max(1, int(min_rally_seconds * self.fps))

        # 状態
        self._shuttle_low_streak: int = 0
        self._player_static_streak: int = 0
        self._prev_player_pos: Dict[str, Tuple[float, float]] = {}
        self._rally_open: bool = False
        self._rally_start_frame: int = 0
        self._cooldown: int = 0  # 連続発火防止

        self.boundaries: List[RallyBoundary] = []

    # ─── メインエントリ ───────────────────────────────────────────────────

    def process_frame(
        self,
        frame_index: int,
        timestamp_sec: float,
        shuttle_confidence: Optional[float],
        player_positions: List[dict],
    ) -> Optional[RallyBoundary]:
        """1 フレーム分の信号を取って境界を判定する。

        Args:
            frame_index: フレーム番号
            timestamp_sec: 動画タイムスタンプ
            shuttle_confidence: TrackNet 信頼度 (None なら不明)
            player_positions: [{"label": "player_a", "centroid": [x, y]}, ...]
                             centroid は画像正規化座標。

        Returns:
            検出された RallyBoundary。なければ None。
        """
        self._update_shuttle(shuttle_confidence)
        self._update_player(player_positions)
        in_serve = self._check_serve_position(player_positions)

        if self._cooldown > 0:
            self._cooldown -= 1
            return None

        signals_fired: List[str] = []
        if self._shuttle_low_streak >= self.shuttle_missing_frames:
            signals_fired.append("shuttle_missing")
        if self._player_static_streak >= self.player_static_frames:
            signals_fired.append("player_static")
        if in_serve:
            signals_fired.append("serve_position")

        if len(signals_fired) < self.min_signals:
            return None

        # ラリー継続中 → end
        if self._rally_open:
            elapsed = frame_index - self._rally_start_frame
            if elapsed < self.min_rally_frames:
                return None
            ev = RallyBoundary(
                kind="end",
                frame_index=frame_index,
                timestamp_sec=timestamp_sec,
                confidence=min(1.0, len(signals_fired) / 3.0),
                signals_fired=signals_fired,
            )
            self.boundaries.append(ev)
            self._rally_open = False
            self._cooldown = self.shuttle_missing_frames  # 連続発火防止
            return ev
        else:
            # ラリー未開始 → start (serve 信号必須)
            if "serve_position" in signals_fired:
                ev = RallyBoundary(
                    kind="start",
                    frame_index=frame_index,
                    timestamp_sec=timestamp_sec,
                    confidence=min(1.0, len(signals_fired) / 3.0),
                    signals_fired=signals_fired,
                )
                self.boundaries.append(ev)
                self._rally_open = True
                self._rally_start_frame = frame_index
                self._cooldown = self.player_static_frames
                return ev
        return None

    # ─── 信号更新 ────────────────────────────────────────────────────────

    def _update_shuttle(self, confidence: Optional[float]) -> None:
        if confidence is None or confidence < self.shuttle_conf_thresh:
            self._shuttle_low_streak += 1
        else:
            self._shuttle_low_streak = 0

    def _update_player(self, players: List[dict]) -> None:
        if not players:
            self._player_static_streak += 1
            return
        all_static = True
        for p in players:
            label = p.get("label")
            c = p.get("centroid")
            if not label or not c or len(c) < 2:
                continue
            prev = self._prev_player_pos.get(label)
            if prev is not None:
                dx = c[0] - prev[0]
                dy = c[1] - prev[1]
                speed = math.sqrt(dx * dx + dy * dy)
                if speed > self.player_static_speed:
                    all_static = False
            self._prev_player_pos[label] = (c[0], c[1])
        if all_static:
            self._player_static_streak += 1
        else:
            self._player_static_streak = 0

    def _check_serve_position(self, players: List[dict]) -> bool:
        """1 選手以上がサーブゾーンに入っているか。"""
        for p in players:
            c = p.get("centroid")
            if not c or len(c) < 2:
                continue
            x, y = c[0], c[1]
            if (
                self.serve_zone_x_range[0] <= x <= self.serve_zone_x_range[1]
                and self.serve_zone_y_range[0] <= y <= self.serve_zone_y_range[1]
            ):
                return True
        return False

    def reset(self) -> None:
        self._shuttle_low_streak = 0
        self._player_static_streak = 0
        self._prev_player_pos = {}
        self._rally_open = False
        self._rally_start_frame = 0
        self._cooldown = 0
        self.boundaries = []
