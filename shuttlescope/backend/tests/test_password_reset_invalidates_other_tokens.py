"""パスワードリセットが「他に発行済みのトークン」まで落とすこと。

リセットの要求は**メールアドレスさえ知っていれば誰でも出せる**。
成功したリセットがセッションしか失効させないと、乗っ取り対応にならない:

  1. 攻撃者が被害者のアドレスでリセットを要求し、メールを横取りして 1 通確保する
  2. 被害者が気づいて自分でリセットする。セッションは失効する
  3. 攻撃者の手元のトークンはまだ未使用・未期限なので、もう一度リセットできる

「パスワードを変える」が乗っ取り対応の標準手段である以上、
変えた時点で他の鍵も落ちていないと効かない。

`backend.main` を import しないので Python 3.10 でも走る。
"""
from __future__ import annotations

import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

from backend.db.models import Base, PasswordResetToken, User
from backend.utils.email_token import (
    consume_password_reset_token,
    invalidate_outstanding_password_reset_tokens,
    issue_password_reset_token,
    peek_invitation_token,
)


@pytest.fixture()
def db():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _make_user(db, username="victim") -> User:
    kw = {}
    for col in User.__table__.columns:
        if col.nullable or col.primary_key or col.name in kw:
            continue
        if col.default is not None or col.server_default is not None:
            continue
        try:
            py = col.type.python_type
        except NotImplementedError:
            py = str
        kw[col.name] = (
            datetime.datetime(2026, 9, 22) if py is datetime.datetime
            else datetime.date(2026, 9, 22) if py is datetime.date
            else 1 if py is int
            else 1.0 if py is float
            else False if py is bool
            else "x"
        )
    kw["username"] = username
    u = User(**kw)
    db.add(u)
    db.commit()
    return u


def _unconsumed(db, user_id: int) -> int:
    return (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.consumed_at.is_(None),
        )
        .count()
    )


def test_an_attackers_outstanding_token_dies_when_the_victim_resets(db):
    user = _make_user(db)
    attacker_token = issue_password_reset_token(db, user.id, requested_ip="203.0.113.9")
    victim_token = issue_password_reset_token(db, user.id, requested_ip="198.51.100.4")
    assert _unconsumed(db, user.id) == 2

    # 被害者が自分のトークンでリセットする
    assert consume_password_reset_token(db, victim_token) == user.id
    invalidate_outstanding_password_reset_tokens(db, user.id)

    assert _unconsumed(db, user.id) == 0
    # 攻撃者のトークンはもう通らない
    assert consume_password_reset_token(db, attacker_token) is None


def test_it_only_touches_that_user(db):
    a = _make_user(db, "a")
    b = _make_user(db, "b")
    issue_password_reset_token(db, a.id)
    b_token = issue_password_reset_token(db, b.id)

    invalidate_outstanding_password_reset_tokens(db, a.id)

    assert _unconsumed(db, a.id) == 0
    assert _unconsumed(db, b.id) == 1
    assert consume_password_reset_token(db, b_token) == b.id


def test_an_already_consumed_token_is_not_counted_again(db):
    user = _make_user(db)
    token = issue_password_reset_token(db, user.id)
    assert consume_password_reset_token(db, token) == user.id
    assert invalidate_outstanding_password_reset_tokens(db, user.id) == 0


def test_the_route_invalidates_the_others():
    """`reset_password` がこの後始末を通ること。"""
    import pathlib

    src = (
        pathlib.Path(__file__).resolve().parents[1] / "routers" / "auth_email.py"
    ).read_text(encoding="utf-8")
    body = src[src.index("def reset_password("):]
    body = body[: body.index("\n@router.")]
    assert "invalidate_outstanding_password_reset_tokens" in body, (
        "リセット成功後も他の発行済みトークンが生きている"
    )
    assert "revoke_all_sessions_or_500" in body, (
        "セッション失効まで戻っている（こちらは既存の対策）"
    )


def test_peek_does_not_consume(db):
    """招待の peek は消費しない（表示用）ことを確認しておく。"""
    assert peek_invitation_token(db, "no-such-token") is None
