"""招待の peek が、受諾前に確認すべき情報 (チーム名・有効期限) を返すこと。

受諾画面は peek の結果だけで「どのチームの招待か」「いつまで有効か」を見せる。
チームは ID ではなく表示名で返し、期限は UTC であることが読み取れる形にする
(DB は naive な UTC。"Z" が無いとブラウザが端末のローカル時刻と読んで数時間ずれる)。

`backend.main` を import しないので Python 3.10 でも走る。
"""
from __future__ import annotations

import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from backend.db.models import Base, Team
from backend.routers.auth_email import peek_invitation
from backend.utils.email_token import issue_invitation_token


@pytest.fixture()
def db():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _peek(db, token: str) -> dict:
    return peek_invitation(token=token, request=None, db=db)["data"]


def test_peek_returns_team_name_and_utc_expiry(db):
    team = Team(name="テスト高校バドミントン部")
    db.add(team)
    db.commit()
    token = issue_invitation_token(
        db, "new@example.test", "coach", inviter_user_id=1, team_id=team.id, ttl_hours=72
    )

    data = _peek(db, token)

    assert data["team_id"] == team.id
    assert data["team_name"] == "テスト高校バドミントン部"
    assert data["role"] == "coach"
    assert data["expires_at"].endswith("Z")
    expires = datetime.datetime.fromisoformat(data["expires_at"].rstrip("Z"))
    assert expires > datetime.datetime.utcnow() + datetime.timedelta(hours=71)


def test_peek_without_team_has_null_team_name(db):
    token = issue_invitation_token(db, "solo@example.test", "analyst", inviter_user_id=1)
    data = _peek(db, token)
    assert data["team_id"] is None
    assert data["team_name"] is None


def test_peek_hides_name_of_a_deleted_team(db):
    team = Team(name="解散したチーム", deleted_at=datetime.datetime(2026, 1, 1))
    db.add(team)
    db.commit()
    token = issue_invitation_token(
        db, "x@example.test", "player", inviter_user_id=1, team_id=team.id
    )
    assert _peek(db, token)["team_name"] is None
