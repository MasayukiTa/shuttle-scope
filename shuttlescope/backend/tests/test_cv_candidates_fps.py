"""C-12: fps が分からなかったことを成果物に残す。

旧実装は `except Exception: pass` のあと黙って 60.0 を返していた。
30fps 素材では秒→フレーム換算が全て 2 倍ずれるのに、
出力には「推定できなかった」痕跡が一切残らない。
DB エラーと「Recording が無い」も区別していなかった。

`backend.main` を import しないので Python 3.10 でも走る。
"""
from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from backend.db.models import Base, Recording
from backend.routers.cv_candidates import _resolve_match_fps


@pytest.fixture()
def db():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _add_recording(db, match_id: int, fps: float) -> None:
    cols = {c.name for c in Recording.__table__.columns}
    kwargs = {"match_id": match_id, "fps": fps}
    if "branch_no" in cols:
        kwargs["branch_no"] = 1
    db.add(Recording(**kwargs))
    db.commit()


def test_missing_recording_is_reported_as_assumed(db):
    fps, known = _resolve_match_fps(db, 1)
    assert fps == 60.0
    assert known is False, "推定できなかったことが呼び出し側に伝わっていない"


def test_known_fps_is_used_and_marked_known(db):
    _add_recording(db, 1, 30.0)
    fps, known = _resolve_match_fps(db, 1)
    assert fps == 30.0
    assert known is True


def test_db_error_does_not_masquerade_as_a_known_fps(db, monkeypatch):
    """DB エラーと「Recording が無い」を区別する。

    どちらも 60.0 を返すが、known=False であることが呼び出し側に伝われば
    成果物に「仮定した」と残せる。
    """
    def _boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "query", _boom)
    fps, known = _resolve_match_fps(db, 1)
    assert fps == 60.0
    assert known is False
