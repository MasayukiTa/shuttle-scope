"""A5: RallyBoundaryDetector のパイプライン統合テスト。

GPU 不要の合成データで以下を検証する:
  - detect_rally_boundaries_from_cv が start/end 境界を期待通り出すこと
  - 各境界に decision_mode / reason_codes が付与されること
  - build_candidates の戻り値に rally_boundaries が入ること（env ON）
  - SS_RALLY_BOUNDARY_DETECT=0 で従来通り（rally_boundaries キー無し）動くこと

既存 test_rally_boundary.py（検出器単体）は壊さない（本ファイルは統合のみ）。
"""
from __future__ import annotations

import os

import pytest

from backend.cv.candidate_builder import (
    build_candidates,
    detect_rally_boundaries_from_cv,
    rally_boundary_detect_enabled,
)


# ─────────────────────────────────────────────────────────────────────────────
# 合成データ生成
# ─────────────────────────────────────────────────────────────────────────────

def _synthetic_frames(fps: float = 10.0):
    """1 ラリー分の合成シャトル/プレイヤーフレームを生成する。

    検出器は min_signals=2（既定）なので start には serve_position に加えてもう 1 信号
    （ここでは player_static）が同時発火する必要がある。サーブ直前は選手が構えて静止する
    ので、サーブゾーンで数フレーム静止 → serve+player_static で start が発火する現実的な
    シナリオを作る。

    シナリオ（fps=10, dt=0.1s, player_static_seconds=0.4 → 4 frame streak）:
      phase 0  (frame 0-5):   サーブ準備。player_a がサーブゾーン(y=0.85)で静止、
                              shuttle 有。frame 4 以降 serve_position + player_static
                              の 2 信号同時発火 → start 境界
      phase 1  (frame 6-20):  ラリー中。shuttle 有(conf 高)、選手は移動
      phase 2  (frame 21-32): ラリー終了。shuttle 消失(conf=0)＋選手静止
                              → end 境界（shuttle_missing + player_static）

    Returns: (shuttle_frames, player_frames)
    """
    shuttle_frames = []
    player_frames = []

    # phase 0: サーブ準備（サーブゾーンで静止）
    for i in range(0, 6):
        ts = i / fps
        shuttle_frames.append({"timestamp_sec": ts, "confidence": 0.9, "x_norm": 0.5, "y_norm": 0.85})
        player_frames.append({
            "timestamp_sec": ts,
            "players": [
                {"label": "player_a", "centroid": [0.50, 0.85]},  # サーブゾーン内・静止
                {"label": "player_b", "centroid": [0.50, 0.15]},  # 静止
            ],
        })

    # phase 1: ラリー中（shuttle 有、選手移動）
    for i in range(6, 21):
        ts = i / fps
        shuttle_frames.append({"timestamp_sec": ts, "confidence": 0.85, "x_norm": 0.5, "y_norm": 0.5})
        # 選手をフレームごとに動かす（静止 streak を作らない）
        ax = 0.40 + (i % 3) * 0.05
        player_frames.append({
            "timestamp_sec": ts,
            "players": [
                {"label": "player_a", "centroid": [ax, 0.55]},
                {"label": "player_b", "centroid": [0.55 - (i % 3) * 0.05, 0.30]},
            ],
        })

    # phase 2: ラリー終了（shuttle 消失 + 選手静止）
    for i in range(21, 33):
        ts = i / fps
        shuttle_frames.append({"timestamp_sec": ts, "confidence": 0.0, "x_norm": None, "y_norm": None})
        player_frames.append({
            "timestamp_sec": ts,
            "players": [
                {"label": "player_a", "centroid": [0.40, 0.55]},  # 固定 = 静止
                {"label": "player_b", "centroid": [0.55, 0.30]},
            ],
        })

    return shuttle_frames, player_frames


# ─────────────────────────────────────────────────────────────────────────────
# detect_rally_boundaries_from_cv 単体
# ─────────────────────────────────────────────────────────────────────────────

class TestDetectRallyBoundariesFromCv:
    def test_detects_start_and_end(self):
        shuttle, players = _synthetic_frames(fps=10.0)
        out = detect_rally_boundaries_from_cv(
            match_id=1, shuttle_frames=shuttle, player_frames=players, fps=10.0,
        )
        kinds = [b["kind"] for b in out["boundaries"]]
        assert "start" in kinds, f"start 境界が出ていない: {out['boundaries']}"
        assert "end" in kinds, f"end 境界が出ていない: {out['boundaries']}"
        assert out["boundary_count"] == len(out["boundaries"])

    def test_start_before_end_in_time(self):
        shuttle, players = _synthetic_frames(fps=10.0)
        out = detect_rally_boundaries_from_cv(
            match_id=1, shuttle_frames=shuttle, player_frames=players, fps=10.0,
        )
        starts = [b for b in out["boundaries"] if b["kind"] == "start"]
        ends = [b for b in out["boundaries"] if b["kind"] == "end"]
        assert starts and ends
        assert starts[0]["timestamp_sec"] < ends[0]["timestamp_sec"]

    def test_decision_mode_and_reason_codes_present(self):
        shuttle, players = _synthetic_frames(fps=10.0)
        out = detect_rally_boundaries_from_cv(
            match_id=1, shuttle_frames=shuttle, player_frames=players, fps=10.0,
        )
        assert out["boundaries"]
        for b in out["boundaries"]:
            assert b["decision_mode"] in ("auto_filled", "suggested", "review_required")
            assert isinstance(b["reason_codes"], list)
            assert isinstance(b["signals_fired"], list)
            assert 0.0 <= b["confidence"] <= 1.0

    def test_start_has_serve_signal(self):
        shuttle, players = _synthetic_frames(fps=10.0)
        out = detect_rally_boundaries_from_cv(
            match_id=1, shuttle_frames=shuttle, player_frames=players, fps=10.0,
        )
        starts = [b for b in out["boundaries"] if b["kind"] == "start"]
        assert starts
        assert "serve_position" in starts[0]["signals_fired"]

    def test_end_has_shuttle_and_player_signals(self):
        shuttle, players = _synthetic_frames(fps=10.0)
        out = detect_rally_boundaries_from_cv(
            match_id=1, shuttle_frames=shuttle, player_frames=players, fps=10.0,
        )
        ends = [b for b in out["boundaries"] if b["kind"] == "end"]
        assert ends
        assert "shuttle_missing" in ends[0]["signals_fired"]
        assert "player_static" in ends[0]["signals_fired"]

    def test_empty_shuttle_frames_returns_zero_boundaries(self):
        out = detect_rally_boundaries_from_cv(
            match_id=1, shuttle_frames=[], player_frames=[], fps=10.0,
        )
        assert out["boundary_count"] == 0
        assert out["boundaries"] == []

    def test_thresholds_reflect_env_override(self, monkeypatch):
        monkeypatch.setenv("SS_RALLY_MIN_SIGNALS", "3")
        shuttle, players = _synthetic_frames(fps=10.0)
        out = detect_rally_boundaries_from_cv(
            match_id=1, shuttle_frames=shuttle, player_frames=players, fps=10.0,
        )
        assert out["thresholds"]["min_signals"] == 3


# ─────────────────────────────────────────────────────────────────────────────
# build_candidates との統合
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildCandidatesRallyBoundaries:
    def _rallies_strokes(self):
        rallies_db = [{
            "id": 1,
            "video_timestamp_start": 0.0,
            "video_timestamp_end": 2.5,
        }]
        strokes_db = [
            {"id": 10, "rally_id": 1, "stroke_num": 1, "timestamp_sec": 0.2},
            {"id": 11, "rally_id": 1, "stroke_num": 2, "timestamp_sec": 1.0},
        ]
        return rallies_db, strokes_db

    def test_rally_boundaries_present_when_enabled(self, monkeypatch):
        monkeypatch.setenv("SS_RALLY_BOUNDARY_DETECT", "1")
        assert rally_boundary_detect_enabled() is True
        shuttle, players = _synthetic_frames(fps=10.0)
        rallies_db, strokes_db = self._rallies_strokes()
        result = build_candidates(
            match_id=1,
            rallies_db=rallies_db,
            strokes_db=strokes_db,
            tracknet_frames=shuttle,
            yolo_frames=players,
            alignment_data=[],
            fps=10.0,
        )
        # 既存 rallies フィールドは不変で存在
        assert "rallies" in result
        # A5: rally_boundaries が追加されている
        assert "rally_boundaries" in result
        rb = result["rally_boundaries"]
        assert rb["match_id"] == 1
        assert isinstance(rb["boundaries"], list)
        kinds = [b["kind"] for b in rb["boundaries"]]
        assert "start" in kinds and "end" in kinds

    def test_rally_boundaries_absent_when_disabled(self, monkeypatch):
        monkeypatch.setenv("SS_RALLY_BOUNDARY_DETECT", "0")
        assert rally_boundary_detect_enabled() is False
        shuttle, players = _synthetic_frames(fps=10.0)
        rallies_db, strokes_db = self._rallies_strokes()
        result = build_candidates(
            match_id=1,
            rallies_db=rallies_db,
            strokes_db=strokes_db,
            tracknet_frames=shuttle,
            yolo_frames=players,
            alignment_data=[],
            fps=10.0,
        )
        # OFF: 従来通り rallies は出るが rally_boundaries キーは付かない
        assert "rallies" in result
        assert "rally_boundaries" not in result

    def test_existing_rallies_field_unchanged_by_flag(self, monkeypatch):
        # ON/OFF どちらでも rallies の中身は同一であること（境界検出は非破壊）
        shuttle, players = _synthetic_frames(fps=10.0)
        rallies_db, strokes_db = self._rallies_strokes()

        monkeypatch.setenv("SS_RALLY_BOUNDARY_DETECT", "0")
        off = build_candidates(
            match_id=1, rallies_db=rallies_db, strokes_db=strokes_db,
            tracknet_frames=shuttle, yolo_frames=players, alignment_data=[], fps=10.0,
        )
        monkeypatch.setenv("SS_RALLY_BOUNDARY_DETECT", "1")
        on = build_candidates(
            match_id=1, rallies_db=rallies_db, strokes_db=strokes_db,
            tracknet_frames=shuttle, yolo_frames=players, alignment_data=[], fps=10.0,
        )
        assert off["rallies"] == on["rallies"]
