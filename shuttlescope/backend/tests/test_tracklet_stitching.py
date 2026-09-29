"""Unit tests for the offline tracklet stitcher (backend/cv/tracklet_stitcher.py)。

合成 tracklet で以下を検証:
  - 1 選手が 3 fragment に分断 (frame gap あり) → 1 identity に統合される
  - 同サイド (同 quadrant でない) 2 選手は 2 identity のまま分離される
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.cv.tracklet_stitcher import (
    _Tracklet, stitch, StitchConfig, SIDE_OF_COURT,
)


def _make_tracklet(track_id, court, f0, f1, cx0, cy0, vx=0.0, vy=0.0, emb=None):
    """frame f0..f1 を 1 frame 刻みで等速移動する合成 tracklet。"""
    frames = np.arange(f0, f1 + 1, dtype=np.int64)
    n = len(frames)
    cxs = cx0 + vx * np.arange(n)
    cys = cy0 + vy * np.arange(n)
    motion = float(np.std(cxs) + np.std(cys)) + 50.0  # 背景除去を確実に通すため十分動かす
    return _Tracklet(
        track_id=track_id, start_frame=int(f0), end_frame=int(f1), n_frames=n,
        dom_court=court, court_frac=0.9, motion=motion,
        frames=frames, cxs=cxs, cys=cys,
        rep_emb=(None if emb is None else np.asarray(emb, np.float32)),
    )


def test_one_player_three_fragments_stitch_to_one():
    """同一 quadrant・連続軌道の 3 fragment が 1 identity に統合される。"""
    cfg = StitchConfig(use_appearance=False)  # appearance なしでも幾何のみで統合できること
    # court 0 (FL) を等速で右へ移動する 1 選手が gap を挟んで 3 分割される
    t1 = _make_tracklet(101, 0, 0, 50, cx0=800, cy0=650, vx=2.0)
    t2 = _make_tracklet(102, 0, 70, 120, cx0=800 + 2.0 * 70, cy0=650, vx=2.0)  # gap 20
    t3 = _make_tracklet(103, 0, 150, 200, cx0=800 + 2.0 * 150, cy0=650, vx=2.0)  # gap 30
    res = stitch([t1, t2, t3], cfg)
    m = res["mapping"]
    assert m[101] == m[102] == m[103], f"3 fragment が同一 identity でない: {m}"
    assert res["diag"]["n_stable_ids"] == 1


def test_two_same_side_players_stay_separate():
    """同じ far side でも別 quadrant (FL=0, FR=1) の 2 選手は 2 identity に残る。"""
    cfg = StitchConfig(use_appearance=False)
    fl = _make_tracklet(201, 0, 0, 100, cx0=850, cy0=650, vx=0.5)   # far-left
    fr = _make_tracklet(202, 1, 0, 100, cx0=1150, cy0=650, vx=-0.5)  # far-right
    res = stitch([fl, fr], cfg)
    m = res["mapping"]
    assert m[201] != m[202], "同サイドの 2 選手が誤統合された"
    assert res["diag"]["n_stable_ids"] == 2
    # 両者とも far side
    assert SIDE_OF_COURT[m[201]] == 0 and SIDE_OF_COURT[m[202]] == 0


def test_hard_cap_four_and_no_cross_net():
    """4 quadrant 全部に fragment があれば identity は 4、side 制約を満たす。"""
    cfg = StitchConfig(use_appearance=False)
    tls = [
        _make_tracklet(1, 0, 0, 80, 850, 650, vx=0.4),
        _make_tracklet(2, 1, 0, 80, 1150, 650, vx=-0.4),
        _make_tracklet(3, 2, 0, 80, 750, 900, vx=0.4),
        _make_tracklet(4, 3, 0, 80, 1100, 900, vx=-0.4),
        # 各 quadrant にもう1 fragment (時間的に後続) → 同 identity に吸収されるべき
        _make_tracklet(5, 0, 100, 180, 850 + 0.4 * 100, 650, vx=0.4),
        _make_tracklet(6, 3, 100, 180, 1100 - 0.4 * 100, 900, vx=-0.4),
    ]
    res = stitch(tls, cfg)
    d = res["diag"]
    assert d["n_stable_ids"] == 4
    assert d["far_side_ids"] == [0, 1]
    assert d["near_side_ids"] == [2, 3]
    m = res["mapping"]
    assert m[5] == m[1], "court0 の後続 fragment が同一 identity に入っていない"
    assert m[6] == m[4], "court3 の後続 fragment が同一 identity に入っていない"


def test_background_static_filtered():
    """court 外・不動の静止誤検出は背景として落とされる (stable_id=-1)。"""
    cfg = StitchConfig()
    player = _make_tracklet(301, 0, 0, 100, 850, 650, vx=1.0)
    # 静止背景: court 外 (dom_court=-1), 不動
    frames = np.arange(0, 100, dtype=np.int64)
    bg = _Tracklet(track_id=302, start_frame=0, end_frame=99, n_frames=100,
                   dom_court=-1, court_frac=0.0, motion=2.0,
                   frames=frames, cxs=np.full(100, 1432.0), cys=np.full(100, 541.0))
    res = stitch([player, bg], cfg)
    m = res["mapping"]
    assert m[302] == -1, "静止背景が選手として残った"
    assert m[301] >= 0, "選手が背景扱いされた"


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
