"""PR1: match_cv_artifacts.data (本番で約 6GB/行) の遅延読み込み検証。

背景(2026-11-06 本番調査): バックエンドが 1 コア張り付き、メモリが
10.8GB まで増え、静的ページすら 8〜18 秒かかった。原因の一つが
match_cv_artifacts.data を必要ないときにまで SELECT していたこと。

data 列は models.py で deferred=True 。このテストは:
  (1) 通常の db.query(MatchCVArtifact) で data が SELECT されない(unloaded)
  (2) data を実際に読む箸所は undefer()/with_data=True でロードされる
  (3) summary だけで足る箸所(court_calibration)は data を触らない
を固定する。
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import undefer

from backend.db.models import Match, MatchCVArtifact, Player
from backend.routers.cv_candidates import _latest_artifact, ARTIFACT_TYPE_CANDIDATES


@pytest.fixture()
def match_id(db_session) -> int:
    a = Player(name="deferredA", dominant_hand="R")
    b = Player(name="deferredB", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="deferredテスト",
        tournament_level="practice",
        round="R1",
        date=date(2026, 11, 6),
        format="singles",
        player_a_id=a.id,
        player_b_id=b.id,
        result="unknown",
    )
    db_session.add(m)
    db_session.flush()
    db_session.commit()
    return m.id


def _add(db_session, match_id, artifact_type, data, summary=None, frame_count=None):
    db_session.add(MatchCVArtifact(
        match_id=match_id,
        artifact_type=artifact_type,
        data=data,
        summary=summary,
        frame_count=frame_count,
    ))
    db_session.commit()


def test_data_is_deferred_on_plain_query(db_session, match_id):
    """素の db.query() では data が unloaded(SELECTされていない)。"""
    _add(db_session, match_id, "yolo_player_detections", "[1,2,3]",
         summary='{"n":3}', frame_count=3)
    db_session.expire_all()
    art = db_session.query(MatchCVArtifact).filter(
        MatchCVArtifact.match_id == match_id).first()
    unloaded = sa_inspect(art).unloaded
    assert "data" in unloaded, f"data が deferred でない: {unloaded}"
    # 軽量列は通常通りロード済み
    assert "summary" not in unloaded
    assert "frame_count" not in unloaded


def test_accessing_data_triggers_load(db_session, match_id):
    """deferred でも .data アクセス時に個別 SELECT され、値は正しい。"""
    _add(db_session, match_id, "yolo_player_detections", "[1,2,3]")
    db_session.expire_all()
    art = db_session.query(MatchCVArtifact).filter(
        MatchCVArtifact.match_id == match_id).first()
    assert "data" in sa_inspect(art).unloaded
    assert art.data == "[1,2,3]"          # ここで遅延ロード
    assert "data" not in sa_inspect(art).unloaded


def test_undefer_loads_data_eagerly(db_session, match_id):
    """undefer() を付けると最初から data がロード済み。"""
    _add(db_session, match_id, "yolo_player_detections", "[9,9]")
    db_session.expire_all()
    art = (db_session.query(MatchCVArtifact)
           .options(undefer(MatchCVArtifact.data))
           .filter(MatchCVArtifact.match_id == match_id).first())
    assert "data" not in sa_inspect(art).unloaded
    assert art.data == "[9,9]"


def test_latest_artifact_default_keeps_data_deferred(db_session, match_id):
    """_latest_artifact(..., with_data=False 既定) は data を引かない。"""
    _add(db_session, match_id, ARTIFACT_TYPE_CANDIDATES, '{"rallies":[]}')
    db_session.expire_all()
    art = _latest_artifact(db_session, match_id, ARTIFACT_TYPE_CANDIDATES)
    assert art is not None
    assert "data" in sa_inspect(art).unloaded


def test_latest_artifact_with_data_loads_data(db_session, match_id):
    """_latest_artifact(..., with_data=True) は data を 1 クエリでロード。"""
    _add(db_session, match_id, ARTIFACT_TYPE_CANDIDATES, '{"rallies":[1]}')
    db_session.expire_all()
    art = _latest_artifact(db_session, match_id, ARTIFACT_TYPE_CANDIDATES, with_data=True)
    assert art is not None
    assert "data" not in sa_inspect(art).unloaded
    assert art.data == '{"rallies":[1]}'


def test_load_calibration_reads_summary_not_data(db_session, match_id):
    """court_calibration は summary だけで足り、data(6GB)を触らない。"""
    from backend.routers.court_calibration import load_calibration_from_db
    _add(db_session, match_id, "court_calibration",
         data="X" * 1000, summary='{"homography": [1,0,0]}')
    db_session.expire_all()
    cal = load_calibration_from_db(match_id, db_session)
    assert cal == {"homography": [1, 0, 0]}
    # 読み込んだ art を探して data が unloaded のままか確認
    art = db_session.query(MatchCVArtifact).filter(
        MatchCVArtifact.match_id == match_id,
        MatchCVArtifact.artifact_type == "court_calibration").first()
    assert "data" in sa_inspect(art).unloaded, "summary 経路なのに data が読まれている"
