"""C-12: 壊れた CV 成果物を「何も無かった」として扱わない。

旧実装は artifact の JSON 解析に失敗すると warning を 1 行出して空リストで
続行し、候補 0 件を `success: true` で返していた。画面には «CV は走ったが
何も見つからなかった» と映る。両方壊れていたときに出る 400 の文面は
「先に CV 解析を実行してください」で、実際には解析済み・成果物が壊れて
いるのに逆のことを言っていた。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import Match, MatchCVArtifact, Player
from backend.main import app
from backend.routers.cv_candidates import (
    ARTIFACT_TYPE_TRACKNET,
    ARTIFACT_TYPE_YOLO,
)


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app, headers={"X-Role": "admin"})
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def match_id(db_session) -> int:
    a = Player(name="壊れ成果物A", dominant_hand="R")
    b = Player(name="壊れ成果物B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="CV成果物テスト",
        tournament_level="practice",
        round="R1",
        date=date(2026, 9, 19),
        format="singles",
        player_a_id=a.id,
        player_b_id=b.id,
        result="unknown",
    )
    db_session.add(m)
    db_session.flush()
    db_session.commit()
    return m.id


def _artifact(db_session, match_id: int, artifact_type: str, data: str) -> None:
    db_session.add(MatchCVArtifact(
        match_id=match_id,
        artifact_type=artifact_type,
        data=data,
    ))
    db_session.commit()


def _build(client, match_id: int):
    return client.post(f"/api/cv-candidates/build/{match_id}")


class TestCorruptArtifactsAreNotSilentlyEmpty:
    def test_a_corrupt_tracknet_artifact_stops_the_build(self, client, db_session, match_id):
        _artifact(db_session, match_id, ARTIFACT_TYPE_TRACKNET, "{not json")
        res = _build(client, match_id)
        assert res.status_code == 500, res.text
        assert "TrackNet" in res.text

    def test_a_corrupt_yolo_artifact_stops_the_build(self, client, db_session, match_id):
        _artifact(db_session, match_id, ARTIFACT_TYPE_YOLO, "[[[")
        res = _build(client, match_id)
        assert res.status_code == 500, res.text
        assert "YOLO" in res.text

    def test_the_message_does_not_tell_the_user_to_run_the_analysis_again(
        self, client, db_session, match_id,
    ):
        """解析は済んでいる。要るのは «やり直し» であって «まず実行» ではない。"""
        _artifact(db_session, match_id, ARTIFACT_TYPE_TRACKNET, "{not json")
        _artifact(db_session, match_id, ARTIFACT_TYPE_YOLO, "{not json")
        res = _build(client, match_id)
        assert res.status_code == 500, res.text
        assert "壊れて" in res.json()["detail"]

    def test_no_artifacts_at_all_is_still_a_400(self, client, match_id):
        """«無い» はこれまでどおり 400。壊れているのと区別が付くこと。"""
        res = _build(client, match_id)
        assert res.status_code == 400, res.text
