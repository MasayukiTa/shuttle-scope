"""track_evaluator (ground-truth 不要 proxy 指標) の合成データ unit test。

GPU / CV / model 依存なし。純ロジックを per-frame 合成系列で検証する。
"""
from __future__ import annotations

from backend.cv import track_evaluator as te


def _rec(frame, track_id, court_id):
    return {"frame": frame, "track_id": track_id, "court_id": court_id}


class TestPerCourtUniqueIds:
    def test_counts_distinct_track_ids_per_court(self):
        records = [
            _rec(0, 1, 0), _rec(0, 2, 1),
            _rec(1, 1, 0), _rec(1, 2, 1),
            _rec(2, 5, 0),  # court0 に新 ID
        ]
        out = te.per_court_unique_ids(records)
        assert out[0] == 2  # track 1, 5
        assert out[1] == 1  # track 2
        assert out[2] == 0
        assert out[3] == 0

    def test_ignores_none_court_and_negative_ids(self):
        records = [
            _rec(0, 1, None),   # コート外 → 無視
            _rec(0, -1, 0),     # 未付与 ID → 無視
            _rec(0, 7, 0),
        ]
        out = te.per_court_unique_ids(records)
        assert out[0] == 1


class TestProxyIdsw:
    def test_three_switches_in_one_court(self):
        """court0 で track_id が 1→5→9→13 と 3 回切り替わる → proxy_idsw=3。"""
        records = [
            _rec(0, 1, 0), _rec(1, 1, 0),
            _rec(2, 5, 0), _rec(3, 5, 0),
            _rec(4, 9, 0),
            _rec(5, 13, 0),
        ]
        per_court = te.proxy_idsw_per_court(records)
        assert per_court[0] == 3
        assert te.proxy_idsw_total(records) == 3

    def test_stable_single_id_is_zero(self):
        records = [_rec(f, 1, 0) for f in range(10)]
        assert te.proxy_idsw_per_court(records)[0] == 0
        assert te.proxy_idsw_total(records) == 0

    def test_initial_occupancy_not_counted(self):
        """初回占有フレームの ID は switch として数えない。"""
        records = [_rec(0, 42, 2)]
        assert te.proxy_idsw_per_court(records)[2] == 0

    def test_independent_per_court(self):
        records = [
            _rec(0, 1, 0), _rec(0, 10, 1),
            _rec(1, 2, 0),   # court0 switch (+1)
            _rec(1, 10, 1),  # court1 stable
        ]
        per_court = te.proxy_idsw_per_court(records)
        assert per_court[0] == 1
        assert per_court[1] == 0
        assert te.proxy_idsw_total(records) == 1

    def test_doubles_two_occupants_partial_swap(self):
        """doubles: 1 court に 2 人。片方だけ入れ替われば +1。"""
        records = [
            _rec(0, 1, 0), _rec(0, 2, 0),   # 初期: {1,2}
            _rec(1, 1, 0), _rec(1, 2, 0),   # 不変
            _rec(2, 1, 0), _rec(2, 9, 0),   # 2→9 (新規 9 流入 +1)
        ]
        assert te.proxy_idsw_per_court(records)[0] == 1

    def test_non_consecutive_frames_use_prev_occupied(self):
        """占有フレームが連続しなくても、直前の占有フレームと比較する。"""
        records = [
            _rec(0, 1, 0),
            # frame 1,2 は court0 占有なし
            _rec(3, 1, 0),  # 同 ID → switch なし
            _rec(7, 8, 0),  # 別 ID → +1
        ]
        assert te.proxy_idsw_per_court(records)[0] == 1


class TestAggregateSwapEvents:
    def test_none_is_zero(self):
        out = te.aggregate_swap_events(None)
        assert out == {"swap_detected": 0, "swap_applied": 0}

    def test_passthrough(self):
        out = te.aggregate_swap_events({"swap_detected": 3, "swap_applied": 2})
        assert out == {"swap_detected": 3, "swap_applied": 2}


class TestEvaluateRun:
    def test_schema_keys_present(self):
        records = [_rec(0, 1, 0), _rec(1, 5, 0)]
        ev = te.evaluate_run(
            records,
            swap_stats={"swap_detected": 1, "swap_applied": 1},
            frames=2,
            seconds=0.5,
        )
        for key in (
            "per_court_unique_ids", "unique_ids_total",
            "swap_detected", "swap_applied",
            "proxy_idsw_per_court", "proxy_idsw_total",
            "frames", "seconds",
        ):
            assert key in ev, f"missing key {key}"
        assert ev["proxy_idsw_total"] == 1
        assert ev["unique_ids_total"] == 2
        assert ev["swap_applied"] == 1
        assert ev["frames"] == 2
        assert ev["seconds"] == 0.5

    def test_off_run_has_zero_swaps(self):
        records = [_rec(0, 1, 0)]
        ev = te.evaluate_run(records, swap_stats={"swap_detected": 0, "swap_applied": 0})
        assert ev["swap_detected"] == 0
        assert ev["swap_applied"] == 0


class TestCompareRuns:
    def test_delta_is_on_minus_off(self):
        off_records = [_rec(0, 1, 0), _rec(1, 5, 0), _rec(2, 9, 0)]  # idsw=2, unique=3
        on_records = [_rec(0, 1, 0), _rec(1, 1, 0), _rec(2, 1, 0)]   # idsw=0, unique=1
        off = te.evaluate_run(off_records)
        on = te.evaluate_run(on_records, swap_stats={"swap_detected": 2, "swap_applied": 2})
        cmp = te.compare_runs(off, on)
        assert cmp["delta"]["unique_ids_total"] == 1 - 3
        assert cmp["delta"]["proxy_idsw_total"] == 0 - 2
        # ON で安定向上 (負の delta) を確認
        assert cmp["delta"]["proxy_idsw_total"] < 0
        assert cmp["on"]["swap_applied"] == 2
        assert cmp["off"]["swap_applied"] == 0
        # per-court delta も court0 に入る
        assert cmp["delta"]["per_court"][0]["proxy_idsw"] == -2
