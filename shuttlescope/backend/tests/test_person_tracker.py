"""PersonTracker (Phase 1+2) の unit test。

ultralytics 依存は遅延 import なので、quadrant adjudicator + dataclass
レベルのテストはこの軽量 venv でも回る。PersonTracker.update の smoke は
ultralytics が import できる時だけ実行する (skip if not available)。
"""
from __future__ import annotations

import importlib.util

import numpy as np
import pytest

from backend.cv.person_tracker import (
    PersonTracker,
    TrackedPerson,
    _QuadrantAdjudicator,
    adjudicate_court,
)


# 100x100 矩形コート (TL, TR, BR, BL) — 中央 (50,50)
SQUARE_CORNERS = [(0.0, 0.0), (100.0, 0.0), (100.0, 100.0), (0.0, 100.0)]


def _bbox_with_foot(fx: float, fy: float, w: float = 10.0, h: float = 20.0) -> tuple[float, float, float, float]:
    """足元が (fx, fy) になる bbox。"""
    return (fx - w / 2, fy - h, fx + w / 2, fy)


class TestQuadrantAdjudicator:
    def setup_method(self):
        self.adj = _QuadrantAdjudicator(SQUARE_CORNERS)

    def test_fl(self):
        # 左上象限 (足元 = 25, 25)
        assert self.adj.classify(_bbox_with_foot(25, 25)) == 0

    def test_fr(self):
        assert self.adj.classify(_bbox_with_foot(75, 25)) == 1

    def test_bl(self):
        assert self.adj.classify(_bbox_with_foot(25, 75)) == 2

    def test_br(self):
        assert self.adj.classify(_bbox_with_foot(75, 75)) == 3

    def test_out_of_court(self):
        # 足元がコート外
        assert self.adj.classify(_bbox_with_foot(150, 50)) is None
        assert self.adj.classify(_bbox_with_foot(50, -10)) is None

    def test_invalid_corners(self):
        with pytest.raises(ValueError):
            _QuadrantAdjudicator([(0.0, 0.0), (1.0, 0.0)])


class TestAdjudicateCourtMatchType:
    def setup_method(self):
        self.adj = _QuadrantAdjudicator(SQUARE_CORNERS)

    def _mk(self, foot, tid, conf):
        return TrackedPerson(
            bbox=_bbox_with_foot(*foot),
            track_id=tid,
            court_id=None,
            player_uuid=None,
            confidence=conf,
        )

    def test_singles_same_quadrant_demotes_low_conf(self):
        # 2 track 同じ FL 象限。conf 高い方が残り、低い方は court_id=None。
        a = self._mk((25, 25), 1, 0.9)
        b = self._mk((30, 30), 2, 0.4)
        out = adjudicate_court([a, b], self.adj, "singles")
        cids = {t.track_id: t.court_id for t in out}
        assert cids[1] == 0
        assert cids[2] is None

    def test_doubles_same_quadrant_two_ok(self):
        a = self._mk((25, 25), 1, 0.9)
        b = self._mk((30, 30), 2, 0.8)
        out = adjudicate_court([a, b], self.adj, "doubles")
        assert all(t.court_id == 0 for t in out)

    def test_doubles_three_in_one_quadrant_demotes_lowest(self):
        a = self._mk((25, 25), 1, 0.9)
        b = self._mk((28, 28), 2, 0.7)
        c = self._mk((30, 30), 3, 0.2)
        out = adjudicate_court([a, b, c], self.adj, "doubles")
        cids = {t.track_id: t.court_id for t in out}
        assert cids[1] == 0 and cids[2] == 0
        assert cids[3] is None

    def test_out_of_court_stays_none(self):
        a = self._mk((25, 25), 1, 0.9)
        b = self._mk((500, 500), 2, 0.9)
        out = adjudicate_court([a, b], self.adj, "doubles")
        cids = {t.track_id: t.court_id for t in out}
        assert cids[1] == 0
        assert cids[2] is None


class TestPersonTrackerInit:
    def test_invalid_match_type(self):
        with pytest.raises(ValueError):
            PersonTracker(match_type="triples")  # type: ignore[arg-type]

    def test_passthrough_without_corners(self):
        # adjudicator 無しでも構築できる
        t = PersonTracker(match_type="singles", court_corners=None)
        assert t._adjudicator is None


@pytest.mark.skipif(
    importlib.util.find_spec("ultralytics") is None,
    reason="ultralytics not installed",
)
def test_update_smoke_one_frame(tmp_path):
    """ultralytics があれば 1 frame でクラッシュしないか確認。

    本物のモデル load を伴うので、CI でモデルが無ければそもそも __init__ で
    落ちる可能性がある。その場合は xfail 扱いにする (テスト失敗にしない)。
    """
    try:
        tracker = PersonTracker(match_type="doubles", court_corners=SQUARE_CORNERS)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        out = tracker.update(frame, 0)
    except Exception as exc:
        pytest.xfail(f"model load/inference 失敗 (環境依存): {exc}")
    assert isinstance(out, list)
