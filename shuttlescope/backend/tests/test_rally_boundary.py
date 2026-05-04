"""Track A5: RallyBoundaryDetector テスト。

3 信号 (shuttle / player / serve) の各々と AND ロジックを検証。
"""
from __future__ import annotations

import pytest

from backend.cv.rally_boundary import RallyBoundaryDetector


def _player(label, x, y):
    return {"label": label, "centroid": [x, y]}


def test_shuttle_signal_alone_does_not_fire_when_min_signals_2():
    det = RallyBoundaryDetector(
        fps=10, shuttle_missing_seconds=0.3, min_signals=2,
        player_static_seconds=10, min_rally_seconds=0,
    )
    # ラリーオープン状態にしておく (start を経由)
    det._rally_open = True
    # 動く選手を入れて player 信号を ON にしない
    for i in range(5):
        ev = det.process_frame(
            frame_index=i,
            timestamp_sec=i / 10.0,
            shuttle_confidence=0.0,  # shuttle 信号 ON
            player_positions=[_player("a", 0.5 + i * 0.1, 0.5)],  # 動いてる
        )
    # min_signals=2、shuttle のみで発火しない
    end_events = [b for b in det.boundaries if b.kind == "end"]
    assert end_events == []


def test_serve_signal_starts_rally():
    det = RallyBoundaryDetector(fps=10, min_signals=1, min_rally_seconds=0)
    ev = det.process_frame(
        frame_index=0,
        timestamp_sec=0.0,
        shuttle_confidence=0.9,
        player_positions=[_player("a", 0.5, 0.85)],  # serve zone
    )
    assert ev is not None
    assert ev.kind == "start"
    assert "serve_position" in ev.signals_fired


def test_two_signals_fire_end_when_rally_open():
    det = RallyBoundaryDetector(
        fps=10, shuttle_missing_seconds=0.3, player_static_seconds=0.3,
        min_signals=2, min_rally_seconds=0,
    )
    det._rally_open = True
    det._rally_start_frame = 0
    end_event = None
    for i in range(5):
        ev = det.process_frame(
            frame_index=i,
            timestamp_sec=i / 10.0,
            shuttle_confidence=0.0,                     # shuttle 信号 ON
            player_positions=[_player("a", 0.4, 0.4)],  # 静止 → player 信号 ON (要 streak)
        )
        if ev is not None:
            end_event = ev
            break
    assert end_event is not None
    assert end_event.kind == "end"
    assert "shuttle_missing" in end_event.signals_fired
    assert "player_static" in end_event.signals_fired


def test_min_rally_seconds_blocks_too_short():
    det = RallyBoundaryDetector(
        fps=10, min_signals=1, min_rally_seconds=2.0,
        shuttle_missing_seconds=0.1,
    )
    det._rally_open = True
    det._rally_start_frame = 0
    # 5 frame = 0.5s < 2.0s min_rally
    for i in range(5):
        det.process_frame(i, i / 10.0, shuttle_confidence=0.0,
                          player_positions=[_player("a", 0.4, 0.4)])
    end_events = [b for b in det.boundaries if b.kind == "end"]
    assert end_events == []


def test_cooldown_prevents_immediate_double_fire():
    det = RallyBoundaryDetector(
        fps=10, min_signals=1, min_rally_seconds=0,
        shuttle_missing_seconds=0.1,
    )
    det._rally_open = True
    det._rally_start_frame = 0
    # frame 0 は min_rally_frames=1 なので発火しない、frame 1 で発火
    det.process_frame(0, 0.0, shuttle_confidence=0.0, player_positions=[])
    ev1 = det.process_frame(1, 0.1, shuttle_confidence=0.0, player_positions=[])
    assert ev1 is not None and ev1.kind == "end"
    # 直後の 2 回目は cooldown で発火しない
    ev2 = det.process_frame(2, 0.2, shuttle_confidence=0.0, player_positions=[])
    assert ev2 is None


def test_reset_clears_state():
    det = RallyBoundaryDetector(fps=10)
    det._rally_open = True
    det.boundaries.append("dummy")  # type: ignore
    det.reset()
    assert det._rally_open is False
    assert det.boundaries == []


def test_player_movement_resets_static_streak():
    det = RallyBoundaryDetector(
        fps=10, player_static_seconds=0.3, min_signals=1, min_rally_seconds=0,
        shuttle_missing_seconds=10,
    )
    det._rally_open = True
    # 静止 streak 蓄積
    det.process_frame(0, 0.0, 0.9, [_player("a", 0.4, 0.4)])
    det.process_frame(1, 0.1, 0.9, [_player("a", 0.4, 0.4)])
    # 動いた → リセット
    det.process_frame(2, 0.2, 0.9, [_player("a", 0.5, 0.5)])
    assert det._player_static_streak == 0


def test_serve_zone_outside_no_fire():
    det = RallyBoundaryDetector(fps=10, min_signals=1, min_rally_seconds=0)
    ev = det.process_frame(
        frame_index=0, timestamp_sec=0.0, shuttle_confidence=0.9,
        player_positions=[_player("a", 0.5, 0.4)],  # serve_zone_y_range=(0.78,1.0) 外
    )
    assert ev is None
