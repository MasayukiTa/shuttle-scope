"""S-4 step 2/3: ラリー境界検出の時間軸と、start/end を組にした segments。

GPU・DB 不要の合成データ。test_rally_boundary_integration.py と同じ流儀で、
同じ実時間のプレーを 10/15/30 fps でサンプリングした成果物が同じ境界になること、
segments が純関数で組み立てられること（空入力・open_ended・データ不足）を確かめる。
"""
from __future__ import annotations

import pytest

from backend.cv.candidate_builder import detect_rally_boundaries_from_cv
from backend.cv.rally_segments import (
    build_rally_segments,
    estimate_sample_fps,
)


def _play(sample_fps: float):
    """同じ実時間のプレーを sample_fps でサンプリングした合成成果物。

      0.0-0.5s  サーブ準備: player_a がサーブゾーンで静止、シャトル有
      0.5-2.0s  ラリー: シャトル有、選手は毎サンプル動く
      2.0-3.3s  終了: シャトル消失 + 選手静止
    """
    shuttle, players = [], []
    n = int(round(3.3 * sample_fps))
    for i in range(n):
        t = round(i / sample_fps, 3)
        if t < 0.5:
            conf = 0.9
            pl = [
                {"label": "player_a", "centroid": [0.50, 0.85]},
                {"label": "player_b", "centroid": [0.50, 0.15]},
            ]
        elif t < 2.0:
            conf = 0.85
            ax = 0.40 + (i % 3) * 0.05
            pl = [
                {"label": "player_a", "centroid": [ax, 0.55]},
                {"label": "player_b", "centroid": [0.55 - (i % 3) * 0.05, 0.30]},
            ]
        else:
            conf = 0.0
            pl = [
                {"label": "player_a", "centroid": [0.40, 0.55]},
                {"label": "player_b", "centroid": [0.55, 0.30]},
            ]
        shuttle.append({"timestamp_sec": t, "confidence": conf})
        players.append({"timestamp_sec": t, "players": pl})
    return shuttle, players


class TestTimeAxis:
    @pytest.mark.parametrize("sample_fps", [10.0, 15.0, 30.0])
    def test_boundaries_found_at_every_sample_rate(self, sample_fps):
        shuttle, players = _play(sample_fps)
        # 動画 fps は 60 と仮定（サンプルレートとは別物）
        out = detect_rally_boundaries_from_cv(
            match_id=1, shuttle_frames=shuttle, player_frames=players, fps=60.0,
        )
        kinds = [b["kind"] for b in out["boundaries"]]
        assert kinds == ["start", "end"], (sample_fps, out["boundaries"])

    def test_same_real_time_play_gives_same_boundaries_across_rates(self):
        results = {}
        for sample_fps in (10.0, 15.0, 30.0):
            shuttle, players = _play(sample_fps)
            out = detect_rally_boundaries_from_cv(
                match_id=1, shuttle_frames=shuttle, player_frames=players, fps=60.0,
            )
            results[sample_fps] = [(b["kind"], b["timestamp_sec"]) for b in out["boundaries"]]
        ref = results[30.0]
        assert [k for k, _ in ref] == ["start", "end"]
        for sample_fps, got in results.items():
            assert [k for k, _ in got] == [k for k, _ in ref], results
            for (_, t_got), (_, t_ref) in zip(got, ref):
                # 最も粗い刻み (0.1s) の 1.5 倍以内で一致
                assert abs(t_got - t_ref) <= 0.15, (sample_fps, results)

    def test_result_does_not_depend_on_declared_video_fps(self):
        shuttle, players = _play(15.0)
        a = detect_rally_boundaries_from_cv(
            match_id=1, shuttle_frames=shuttle, player_frames=players, fps=60.0)
        b = detect_rally_boundaries_from_cv(
            match_id=1, shuttle_frames=shuttle, player_frames=players, fps=29.97)
        assert a["boundaries"] == b["boundaries"]
        assert a["time_axis"] == b["time_axis"] == "sample_rate"
        assert a["sample_fps"] == 15.0

    def test_time_axis_is_honest_when_rate_cannot_be_estimated(self):
        # サンプル 2 点では間隔の中央値が取れない → 動画 fps にフォールバックし、そう明示する
        shuttle = [{"timestamp_sec": 0.0, "confidence": 0.9},
                   {"timestamp_sec": 0.1, "confidence": 0.9}]
        out = detect_rally_boundaries_from_cv(
            match_id=1, shuttle_frames=shuttle, player_frames=[], fps=60.0)
        assert out["sample_fps"] is None
        assert out["time_axis"] == "video_fps_fallback"
        assert out["fps"] == 60.0

    def test_estimate_sample_fps_uses_median_gap(self):
        # ラリー窓 2 つ（窓内 0.1s 刻み、窓の間に 30 秒の隙間）でも刻み幅が取れる
        ts = [0.0, 0.1, 0.2, 0.3, 30.0, 30.1, 30.2, 30.3]
        assert estimate_sample_fps(ts) == pytest.approx(10.0)
        assert estimate_sample_fps([]) is None
        assert estimate_sample_fps([1.0, 1.0, 1.0]) is None


def _b(kind, t, signals=("serve_position", "player_static"), conf=None):
    return {
        "kind": kind, "timestamp_sec": t, "signals_fired": list(signals),
        "confidence": conf if conf is not None else round(len(signals) / 3.0, 3),
    }


class TestSegments:
    def test_empty_input_gives_empty_list(self):
        assert build_rally_segments([]) == []
        assert build_rally_segments([], shuttle_timestamps=[], sample_fps=10.0) == []

    def test_pairs_start_end_in_time_order_even_if_input_unsorted(self):
        segs = build_rally_segments([_b("end", 10.0), _b("start", 2.0), _b("end", 30.0), _b("start", 20.0)])
        assert [(s["start_sec"], s["end_sec"]) for s in segs] == [(2.0, 10.0), (20.0, 30.0)]
        s = segs[0]
        assert s["duration"] == 8.0
        assert s["confidence_basis"] == "signals_fired/3"
        assert s["signals"] == {"start": ["serve_position", "player_static"],
                                "end": ["serve_position", "player_static"]}
        assert s["open_ended"] is False
        assert "coverage_ratio" in s

    def test_unmatched_start_and_end_are_open_ended_not_dropped(self):
        segs = build_rally_segments([_b("end", 1.0), _b("start", 5.0), _b("start", 9.0), _b("end", 12.0), _b("start", 40.0)])
        got = [(s["start_sec"], s["end_sec"], s["open_side"]) for s in segs]
        assert got == [
            (None, 1.0, "start_missing"),
            (5.0, None, "end_missing"),
            (9.0, 12.0, None),
            (40.0, None, "end_missing"),
        ]
        assert [s["open_ended"] for s in segs] == [True, True, False, True]
        assert all(s["duration"] is None for s in segs if s["open_ended"])

    def test_coverage_ratio_full_when_densely_sampled(self):
        ts = [i / 10.0 for i in range(0, 200)]
        segs = build_rally_segments([_b("start", 2.0), _b("end", 10.0)],
                                    shuttle_timestamps=ts, sample_fps=10.0)
        assert segs[0]["coverage_ratio"] == 1.0
        assert segs[0]["data_status"] == "ok"
        assert segs[0]["signal_score"] == pytest.approx(0.667, abs=1e-3)

    def test_low_sample_segment_says_data_insufficient_not_zero_confidence(self):
        # 8 秒の区間に 3 サンプルしか無い
        segs = build_rally_segments([_b("start", 2.0), _b("end", 10.0)],
                                    shuttle_timestamps=[2.0, 5.0, 9.9], sample_fps=10.0)
        s = segs[0]
        assert s["data_status"] == "data_insufficient"
        assert s["signal_score"] is None  # 0 という数字にしない
        assert s["coverage_ratio"] < 0.5

    def test_detector_output_carries_segments(self):
        shuttle, players = _play(15.0)
        out = detect_rally_boundaries_from_cv(
            match_id=1, shuttle_frames=shuttle, player_frames=players, fps=60.0)
        assert out["segments_status"] == "ok"
        assert len(out["segments"]) == 1
        seg = out["segments"][0]
        assert seg["start_sec"] < seg["end_sec"]
        assert seg["data_status"] == "ok"

    def test_detector_with_too_few_samples_says_data_insufficient(self):
        shuttle = [{"timestamp_sec": i / 10.0, "confidence": 0.9} for i in range(6)]
        out = detect_rally_boundaries_from_cv(
            match_id=1, shuttle_frames=shuttle, player_frames=[], fps=60.0)
        assert out["segments"] == []
        assert out["segments_status"] == "data_insufficient"

    def test_detector_empty_input_no_error(self):
        out = detect_rally_boundaries_from_cv(
            match_id=1, shuttle_frames=[], player_frames=[], fps=60.0)
        assert out["segments"] == []
        assert out["segments_status"] == "data_insufficient"
