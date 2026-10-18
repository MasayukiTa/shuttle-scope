"""S-4 step 1/8: tracknet_shuttle_track の書き手衝突と、ラリー駆動バッチの安全策。

- 動画全体の走査結果 (coverage=full) を、ラリー窓だけのバッチが上書きしない
- video_import は何が既にあっても置き換え、summary に coverage/sample_fps/範囲を残す
- 全ラリーの video_timestamp_start が同一値なら _run_batch は何も書かない

GPU・実動画は使わない（推論器・フレーム抽出・軌跡構築は差し替える）。
"""
from __future__ import annotations

import json
from datetime import date

import pytest

from backend.db.models import GameSet, Match, MatchCVArtifact, Player, Rally, Stroke
from backend.routers import tracknet as tn
from backend.routers import video_import as vi


class _FakeInf:
    def load(self):
        return True

    def get_load_error(self):
        return None

    def backend_name(self):
        return "fake"

    def predict_frames(self, frames):
        return [{"zone": "BL", "confidence": 0.9, "x_norm": 0.5, "y_norm": 0.5} for _ in frames]


def _full_track(n=1000):
    return [
        {"frame_idx": i * 2, "timestamp_sec": round(i / 15.0, 3), "zone": None,
         "confidence": 0.5, "x_norm": 0.5, "y_norm": 0.5}
        for i in range(n)
    ]


def _window_track(n=30):
    return [
        {"timestamp_sec": round(10.0 + i * 0.1, 3), "zone": None,
         "confidence": 0.5, "x_norm": 0.5, "y_norm": 0.5}
        for i in range(n)
    ]


@pytest.fixture()
def match_ctx(db_session):
    db = db_session
    pa = Player(name="TA PA", name_normalized="ta pa")
    pb = Player(name="TA PB", name_normalized="ta pb")
    db.add_all([pa, pb])
    db.flush()
    m = Match(tournament="TA", tournament_level="domestic", round="QF",
              date=date(2026, 10, 18), format="singles", result="unknown",
              is_public_pool=False, player_a_id=pa.id, player_b_id=pb.id)
    db.add(m)
    db.flush()
    gs = GameSet(match_id=m.id, set_num=1, winner="player_a", score_a=21, score_b=10)
    db.add(gs)
    db.flush()
    db.commit()
    return {"db": db, "match": m, "set": gs}


def _add_rally(ctx, num, start, end=None, land_zone=None):
    db = ctx["db"]
    r = Rally(set_id=ctx["set"].id, rally_num=num, server="player_a", winner="player_a",
              end_type="forced_error", rally_length=1,
              video_timestamp_start=start, video_timestamp_end=end)
    db.add(r)
    db.flush()
    db.add(Stroke(rally_id=r.id, stroke_num=1, player="player_a", shot_type="clear",
                  land_zone=land_zone))
    db.commit()
    return r


def _add_artifact(ctx, track, summary):
    db = ctx["db"]
    a = MatchCVArtifact(
        match_id=ctx["match"].id, artifact_type="tracknet_shuttle_track",
        frame_count=len(track), backend_used="fake",
        summary=json.dumps(summary) if summary is not None else None,
        data=json.dumps(track))
    db.add(a)
    db.commit()
    return a.id


def _run(monkeypatch, ctx, *, window_track=None):
    monkeypatch.setattr(tn, "get_inference", lambda *a, **k: _FakeInf())
    monkeypatch.setattr(tn, "_extract_frames", lambda *a, **k: [object()] * 5)
    built = {"called": 0}

    def _fake_build(*a, **k):
        built["called"] += 1
        return window_track if window_track is not None else _window_track()

    monkeypatch.setattr(tn, "_build_shuttle_track", _fake_build)
    job_id = "jobtest1"
    tn._jobs[job_id] = {"status": "pending", "match_id": ctx["match"].id, "progress": 0.0,
                        "processed_rallies": 0, "total_rallies": 0, "updated_strokes": 0,
                        "error": None, "message": None, "shuttle_track_write": None}
    try:
        tn._run_batch(job_id, ctx["match"].id, "video.mp4", 0.5)
        return dict(tn._jobs[job_id]), built
    finally:
        tn._jobs.pop(job_id, None)


def _artifact(ctx, art_id):
    ctx["db"].expire_all()
    return ctx["db"].get(MatchCVArtifact, art_id)


class TestRallyBatchDoesNotOverwriteFullArtifact:
    def test_full_artifact_keeps_frame_count(self, monkeypatch, match_ctx):
        _add_rally(match_ctx, 1, 10.0, 13.0)
        art_id = _add_artifact(match_ctx, _full_track(1000), {"coverage": "full", "sample_fps": 15.0})
        job, built = _run(monkeypatch, match_ctx)
        art = _artifact(match_ctx, art_id)
        assert art.frame_count == 1000
        assert len(json.loads(art.data)) == 1000
        assert json.loads(art.summary)["coverage"] == "full"
        assert job["status"] == "complete"
        assert job["shuttle_track_write"] == "skipped_existing_full"
        assert "coverage=full" in job["message"]
        assert built["called"] == 0  # 窓の軌跡を作る推論自体を省く

    def test_legacy_full_artifact_without_summary_is_recognised_by_frame_idx(self, monkeypatch, match_ctx):
        _add_rally(match_ctx, 1, 10.0, 13.0)
        art_id = _add_artifact(match_ctx, _full_track(500), None)
        job, _ = _run(monkeypatch, match_ctx)
        assert _artifact(match_ctx, art_id).frame_count == 500
        assert job["shuttle_track_write"] == "skipped_existing_full"

    def test_rally_windows_artifact_is_replaced_with_coverage_meta(self, monkeypatch, match_ctx):
        _add_rally(match_ctx, 1, 10.0, 13.0)
        art_id = _add_artifact(match_ctx, _window_track(5), {"coverage": "rally_windows"})
        job, _ = _run(monkeypatch, match_ctx, window_track=_window_track(30))
        art = _artifact(match_ctx, art_id)
        assert art.frame_count == 30
        s = json.loads(art.summary)
        assert s["coverage"] == "rally_windows"
        assert s["sample_fps"] == 10.0
        assert s["covered_start_sec"] == 10.0
        assert s["covered_end_sec"] == pytest.approx(12.9)
        assert job["shuttle_track_write"] == "written_rally_windows"

    def test_no_artifact_creates_one_with_rally_windows_meta(self, monkeypatch, match_ctx):
        _add_rally(match_ctx, 1, 10.0, 13.0)
        _run(monkeypatch, match_ctx)
        art = (match_ctx["db"].query(MatchCVArtifact)
               .filter(MatchCVArtifact.match_id == match_ctx["match"].id).one())
        assert json.loads(art.summary)["coverage"] == "rally_windows"


class TestVideoImportWritesCoverageAndReplaces:
    def test_replaces_rally_windows_and_records_full_meta(self, match_ctx):
        art_id = _add_artifact(match_ctx, _window_track(30), {"coverage": "rally_windows"})
        track = _full_track(600)
        vi._save_tracknet_artifact(match_ctx["match"].id, track, "fake", sample_fps=15.0)
        art = _artifact(match_ctx, art_id)
        assert art.frame_count == 600
        s = json.loads(art.summary)
        assert s["coverage"] == "full"
        assert s["sample_fps"] == 15.0
        assert s["covered_start_sec"] == 0.0
        assert s["covered_end_sec"] == track[-1]["timestamp_sec"]
        assert s["point_count"] == 600
        assert s["backend"] == "fake"

    def test_replaces_even_an_existing_full_artifact(self, match_ctx):
        art_id = _add_artifact(match_ctx, _full_track(100), {"coverage": "full"})
        vi._save_tracknet_artifact(match_ctx["match"].id, _full_track(700), "fake", sample_fps=15.0)
        assert _artifact(match_ctx, art_id).frame_count == 700


class TestIdenticalRallyTimestampsGuard:
    def test_all_zero_starts_process_nothing_and_write_nothing(self, monkeypatch, match_ctx):
        _add_rally(match_ctx, 1, 0.0)
        _add_rally(match_ctx, 2, 0.0)
        _add_rally(match_ctx, 3, 0.0)
        job, built = _run(monkeypatch, match_ctx)
        db = match_ctx["db"]
        db.expire_all()
        assert [s.land_zone for s in db.query(Stroke).all()] == [None, None, None]
        assert db.query(MatchCVArtifact).count() == 0
        assert built["called"] == 0
        assert job["status"] == "complete"
        assert job["skipped_reason"] == "identical_rally_timestamps"
        assert "同一値" in job["message"]

    def test_distinct_starts_still_processed(self, monkeypatch, match_ctx):
        _add_rally(match_ctx, 1, 10.0)
        _add_rally(match_ctx, 2, 40.0)
        job, _ = _run(monkeypatch, match_ctx)
        db = match_ctx["db"]
        db.expire_all()
        assert all(s.land_zone == "BL" for s in db.query(Stroke).all())
        assert "skipped_reason" not in job

    def test_single_rally_is_not_treated_as_identical(self, monkeypatch, match_ctx):
        _add_rally(match_ctx, 1, 0.0)
        job, _ = _run(monkeypatch, match_ctx)
        assert "skipped_reason" not in job

    def test_human_entered_land_zone_untouched_in_skipped_run(self, monkeypatch, match_ctx):
        _add_rally(match_ctx, 1, 0.0, land_zone="NL")
        _add_rally(match_ctx, 2, 0.0, land_zone="NR")
        _run(monkeypatch, match_ctx)
        db = match_ctx["db"]
        db.expire_all()
        assert sorted(s.land_zone for s in db.query(Stroke).all()) == ["NL", "NR"]
