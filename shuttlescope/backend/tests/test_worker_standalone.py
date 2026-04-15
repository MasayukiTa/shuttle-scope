"""スタンドアロンワーカー (backend.pipeline.worker) の挙動検証。

- `SS_WORKER_STANDALONE=1` のとき FastAPI 側の start_job_runner() が no-op になる
- worker.main(['--once']) がキュー内のジョブを処理して 0 を返す
"""
from __future__ import annotations

from datetime import date

import pytest

from backend.db.models import AnalysisJob, GameSet, Match, Player, Rally, Stroke
from backend.pipeline import jobs as jobs_module
from backend.pipeline import worker as worker_module


@pytest.fixture()
def _seed_match(db_session):
    """最小のマッチ/セット/ラリー/ストロークを作成。"""
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
        end_type="unforced_error", rally_length=2,
    )
    db_session.add(r)
    db_session.flush()
    db_session.add_all([
        Stroke(rally_id=r.id, stroke_num=1, player="player_a", shot_type="clear"),
        Stroke(rally_id=r.id, stroke_num=2, player="player_b", shot_type="smash"),
    ])
    db_session.commit()
    return m


def test_start_job_runner_noop_when_standalone(monkeypatch):
    """SS_WORKER_STANDALONE=1 のとき start_job_runner() は None を返し no-op となる。"""
    monkeypatch.setenv("SS_WORKER_STANDALONE", "1")
    # 既存の RUNNER_TASK を念のためクリア
    monkeypatch.setattr(jobs_module, "_RUNNER_TASK", None, raising=False)
    result = jobs_module.start_job_runner()
    assert result is None
    # 呼んでも _RUNNER_TASK がセットされないこと（in-process runner が起動していない）
    assert jobs_module._RUNNER_TASK is None


def test_worker_once_processes_pending_job(db_session, _seed_match, monkeypatch):
    """worker.main(['--once', '--no-lock']) でキュー内のジョブが処理される。"""
    # CV mock を有効化（settings 経由）
    monkeypatch.setenv("SS_CV_MOCK", "1")
    from backend.config import settings as app_settings
    monkeypatch.setattr(app_settings, "ss_cv_mock", 1, raising=False)

    # ジョブを投入
    job = jobs_module.enqueue(db_session, _seed_match.id)
    assert job.status == "queued"

    # --once で 1 周だけ実行（ファイルロック取得はスキップ）
    rc = worker_module.main(["--once", "--no-lock"])
    assert rc == 0

    # 状態を再読込して done を確認
    db_session.expire_all()
    updated = db_session.get(AnalysisJob, job.id)
    assert updated is not None
    assert updated.status == "done"
    assert updated.progress == 1.0
    assert updated.error is None


def test_worker_once_empty_queue_returns_zero(monkeypatch):
    """キューが空でも --once は正常終了（rc=0）。"""
    rc = worker_module.main(["--once", "--no-lock"])
    assert rc == 0


def test_file_lock_prevents_double_acquire(tmp_path):
    """同一ロックファイルの 2 回目 acquire は失敗する（多重起動防止）。"""
    lock_path = tmp_path / "worker.lock"
    lock1 = worker_module._FileLock(lock_path)
    lock2 = worker_module._FileLock(lock_path)
    try:
        assert lock1.acquire() is True
        # 2 本目は取れない
        assert lock2.acquire() is False
    finally:
        lock1.release()
        lock2.release()
