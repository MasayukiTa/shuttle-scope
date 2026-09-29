"""D-7: 動画差し替え時に旧動画依存の CV 成果物を無効化する。"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from sqlalchemy.orm import sessionmaker

import pytest
from types import SimpleNamespace

from starlette.requests import Request

from backend.db.database import get_db
from backend.db.models import Match, MatchCVArtifact, Player
from backend.routers.matches import MatchUpdate, update_match
from backend.services.video_source_lifecycle import (
    effective_video_source,
    invalidate_match_cv_artifacts_if_source_replaced,
)


def _local_url(name: str) -> str:
    root = Path(__file__).resolve().parents[1] / "data"
    return "localfile:///" + str(root / name).replace("\\", "/")


def _add_artifacts(db, match_id: int) -> None:
    db.add_all([
        MatchCVArtifact(match_id=match_id, artifact_type="court_calibration", summary="{}"),
        MatchCVArtifact(match_id=match_id, artifact_type="yolo_player_detections", data="[]"),
        MatchCVArtifact(match_id=match_id, artifact_type="tracknet_shuttle_track", data="[]"),
        MatchCVArtifact(match_id=match_id, artifact_type="cv_alignment", data="[]"),
    ])
    db.commit()


@pytest.fixture()
def match(db_session):
    a = Player(name="D7-A", dominant_hand="R")
    b = Player(name="D7-B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="D7 video lifecycle",
        tournament_level="practice",
        round="R1",
        date=date(2026, 9, 26),
        format="singles",
        player_a_id=a.id,
        player_b_id=b.id,
        result="unknown",
        video_local_path=_local_url("d7-old.mp4"),
        video_url="https://example.com/source-old",
    )
    db_session.add(m)
    db_session.commit()
    return m


def test_effective_source_prefers_local_over_url():
    assert effective_video_source(" localfile:///x.mp4 ", "https://example.com/x") == (
        "local",
        "localfile:///x.mp4",
    )
    assert effective_video_source("", " https://example.com/x ") == (
        "url",
        "https://example.com/x",
    )
    assert effective_video_source(None, None) is None


def test_same_effective_source_preserves_artifacts(db_session, match):
    _add_artifacts(db_session, match.id)

    deleted = invalidate_match_cv_artifacts_if_source_replaced(
        db_session,
        match.id,
        old_video_local_path=match.video_local_path,
        old_video_url="https://example.com/old",
        new_video_local_path=match.video_local_path,
        new_video_url="https://example.com/new",
    )
    db_session.commit()

    assert deleted == 0
    assert db_session.query(MatchCVArtifact).filter(
        MatchCVArtifact.match_id == match.id
    ).count() == 4


def test_source_replacement_deletes_all_recoverable_cv_artifacts(db_session, match):
    _add_artifacts(db_session, match.id)

    deleted = invalidate_match_cv_artifacts_if_source_replaced(
        db_session,
        match.id,
        old_video_local_path=match.video_local_path,
        old_video_url=match.video_url,
        new_video_local_path=_local_url("d7-new.mp4"),
        new_video_url=match.video_url,
    )
    db_session.commit()

    assert deleted == 4
    assert db_session.query(MatchCVArtifact).filter(
        MatchCVArtifact.match_id == match.id
    ).count() == 0


def test_update_match_video_replacement_invalidates_cv_artifacts(
    monkeypatch, db_session, match
):
    import backend.routers.matches as matches_mod
    import backend.utils.access_log as access_log_mod
    import backend.utils.auth as auth_mod

    _add_artifacts(db_session, match.id)
    monkeypatch.setattr(
        matches_mod,
        "get_auth",
        lambda _request: SimpleNamespace(
            is_player=False,
            is_admin=True,
            user_id=123,
            role="admin",
        ),
    )
    monkeypatch.setattr(matches_mod, "user_can_access_match", lambda *_a, **_k: True)
    monkeypatch.setattr(auth_mod, "require_match_scope", lambda *_a, **_k: None)
    monkeypatch.setattr(access_log_mod, "log_access", lambda *_a, **_k: None)

    request = Request({
        "type": "http",
        "method": "PUT",
        "path": f"/api/matches/{match.id}",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
    })
    new_path = _local_url("d7-replacement.mp4")

    result = update_match(
        match.id,
        MatchUpdate(video_local_path=new_path),
        request,
        db_session,
    )

    assert result["success"] is True
    db_session.expire_all()
    refreshed = db_session.get(Match, match.id)
    assert refreshed.video_local_path == new_path
    assert db_session.query(MatchCVArtifact).filter(
        MatchCVArtifact.match_id == match.id
    ).count() == 0

def test_youtube_archive_relocation_preserves_cv_artifacts(monkeypatch, db_session, match):
    import backend.db.database as database_mod
    from backend.services.youtube_live_recorder import (
        _path_to_localfile_url,
        _update_match_video_path,
    )

    old_path = Path(__file__).resolve().parents[1] / "data" / "yt-live-ssd.mp4"
    new_path = Path(__file__).resolve().parents[1] / "data" / "archive" / "yt-live-hdd.mp4"
    match.video_local_path = _path_to_localfile_url(old_path)
    db_session.commit()
    _add_artifacts(db_session, match.id)

    TestSession = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(database_mod, "SessionLocal", TestSession)

    updated = _update_match_video_path(old_path, new_path, match.id)

    assert updated >= 1
    db_session.expire_all()
    refreshed = db_session.get(Match, match.id)
    assert refreshed.video_local_path == _path_to_localfile_url(new_path)
    assert db_session.query(MatchCVArtifact).filter(
        MatchCVArtifact.match_id == match.id
    ).count() == 4


def test_youtube_archive_explicit_overwrite_of_unrelated_video_invalidates(
    monkeypatch, db_session, match
):
    import backend.db.database as database_mod
    from backend.services.youtube_live_recorder import (
        _path_to_localfile_url,
        _update_match_video_path,
    )

    old_path = Path(__file__).resolve().parents[1] / "data" / "yt-live-ssd.mp4"
    new_path = Path(__file__).resolve().parents[1] / "data" / "archive" / "yt-live-hdd.mp4"
    match.video_local_path = _local_url("unrelated-existing-video.mp4")
    db_session.commit()
    _add_artifacts(db_session, match.id)

    TestSession = sessionmaker(bind=db_session.get_bind(), expire_on_commit=False)
    monkeypatch.setattr(database_mod, "SessionLocal", TestSession)

    _update_match_video_path(old_path, new_path, match.id)

    db_session.expire_all()
    assert db_session.query(MatchCVArtifact).filter(
        MatchCVArtifact.match_id == match.id
    ).count() == 0
