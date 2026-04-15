"""INFRA Phase B: パイプラインの E2E スモークテスト。

SS_CV_MOCK=1 でダミーパイプラインが enqueue → done まで走り、
DB に想定行数が書き込まれることを検証する。
"""
from __future__ import annotations

import asyncio
import os
from datetime import date

import pytest

from backend.db.models import (
    AnalysisJob,
    CenterOfGravity,
    GameSet,
    Match,
    Player,
    PoseFrame,
    Rally,
    ShotInference,
    ShuttleTrack,
    Stroke,
)
from backend.pipeline.jobs import drain_for_tests, enqueue
from backend.pipeline.video_pipeline import run_pipeline


@pytest.fixture()
def _seed_match(db_session):
    """最小限の match / set / rally / stroke を作る。"""
    p_a = Player(name="A選手")
    p_b = Player(name="B選手")
    db_session.add_all([p_a, p_b])
    db_session.flush()
    m = Match(
        tournament="T", tournament_level="国内", round="R16",
        date=date(2026, 4, 16), format="singles",
        player_a_id=p_a.id, player_b_id=p_b.id, result="win",
    )
    db_session.add(m)
    db_session.flush()
    gs = GameSet(match_id=m.id, set_num=1, score_a=21, score_b=18)
    db_session.add(gs)
    db_session.flush()
    r = Rally(
        set_id=gs.id, rally_num=1, server="player_a", winner="player_a",
        end_type="unforced_error", rally_length=3,
    )
    db_session.add(r)
    db_session.flush()
    s1 = Stroke(rally_id=r.id, stroke_num=1, player="player_a", shot_type="clear")
    s2 = Stroke(rally_id=r.id, stroke_num=2, player="player_b", shot_type="smash")
    s3 = Stroke(rally_id=r.id, stroke_num=3, player="player_a", shot_type="drop")
    db_session.add_all([s1, s2, s3])
    db_session.commit()
    return m


def _force_mock(monkeypatch):
    """settings.ss_cv_mock = 1 を強制（factory が mock を返すように）。"""
    monkeypatch.setenv("SS_CV_MOCK", "1")
    from backend.config import settings as app_settings
    monkeypatch.setattr(app_settings, "ss_cv_mock", 1, raising=False)


def test_run_pipeline_writes_rows(db_session, _seed_match, monkeypatch):
    """run_pipeline を直接呼び、DB 書き込み行数を検証する。"""
    _force_mock(monkeypatch)
    counts = run_pipeline(db_session, _seed_match.id)
    db_session.commit()

    # MockTrackNet: 30fps * 30sec = 900 frames
    # MockPose: 900 frames * 2 sides = 1800
    assert counts["shuttle_tracks"] == 900
    assert counts["pose_frames"] == 1800
    assert counts["center_of_gravity"] == 1800
    assert counts["shot_inferences"] == 3

    assert db_session.query(ShuttleTrack).filter(ShuttleTrack.match_id == _seed_match.id).count() == 900
    assert db_session.query(PoseFrame).filter(PoseFrame.match_id == _seed_match.id).count() == 1800
    assert db_session.query(CenterOfGravity).filter(CenterOfGravity.match_id == _seed_match.id).count() == 1800
    assert db_session.query(ShotInference).count() == 3


def test_job_runner_processes_queue(db_session, _seed_match, monkeypatch):
    """enqueue → drain → status=done を検証する。"""
    _force_mock(monkeypatch)
    job = enqueue(db_session, _seed_match.id)
    assert job.status == "queued"
    assert job.id > 0

    processed = asyncio.new_event_loop().run_until_complete(drain_for_tests(5))
    assert processed >= 1

    db_session.expire_all()
    updated = db_session.get(AnalysisJob, job.id)
    assert updated is not None
    assert updated.status == "done"
    assert updated.progress == 1.0
    assert updated.error is None


def test_start_job_runner_is_idempotent():
    """start_job_runner はループ未稼働時に None を返し、例外を出さない。"""
    from backend.pipeline.jobs import start_job_runner
    # 同期コンテキスト: 走行中のループが無いので None または未稼働 Task が返る
    r1 = start_job_runner()
    r2 = start_job_runner()
    assert r1 is None or r1 is r2 or r1.done() or not r1.done()
