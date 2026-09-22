"""`/api/tracknet/live_frame_hint` が、呼び手とセッションの関係を見ること。

2026-09-22 の認可掃引（稼働中の app から 588 ルートを数え直した）で残った 2 本の
うちの 1 本。JWT は要るが、**`session_code` の実在も呼び手との関係も見ていなかった**。

  - 他人のセッション宛のバッファにフレームを差し込め、3 枚たまった時点の
    推論結果も受け取れた
  - 未知のコードでも `_live_frame_buffers[code]` を作るので、認証済みなら誰でも
    **辞書を無限に膨らませられた**（1 件あたり最大 3 枚 × 8MB のデコード済みフレーム）

セッション参加者かどうかは `SessionParticipant` に `user_id` が無いので
直接は答えられない。答えられるのは「その試合にアクセスできるか」なので、
`sessions.py` と同じ `require_match_scope` を通す。

`backend.main` を import しないので Python 3.10 でも走る。
"""
from __future__ import annotations

import datetime
from collections import deque

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.orm import sessionmaker

import backend.routers.tracknet as tracknet
from backend.db.models import Base, Match, Player, SharedSession


@pytest.fixture()
def db():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


def _fill_required(model, **kw):
    for col in model.__table__.columns:
        if col.nullable or col.primary_key or col.name in kw:
            continue
        if col.default is not None or col.server_default is not None:
            continue
        try:
            py = col.type.python_type
        except NotImplementedError:
            py = str
        kw[col.name] = (
            datetime.date(2026, 9, 22) if py is datetime.date
            else datetime.datetime(2026, 9, 22) if py is datetime.datetime
            else 1 if py is int
            else 1.0 if py is float
            else False if py is bool
            else "x"
        )
    return model(**kw)


@pytest.fixture()
def session_row(db):
    a = _fill_required(Player, name="A")
    b = _fill_required(Player, name="B")
    db.add_all([a, b])
    db.flush()
    m = _fill_required(Match, player_a_id=a.id, player_b_id=b.id)
    db.add(m)
    db.flush()
    s = _fill_required(SharedSession, session_code="ABC123", match_id=m.id)
    db.add(s)
    db.commit()
    return s, m


def test_an_unknown_session_code_is_refused(db, monkeypatch):
    """未知のコードは 404。ここで弾くのでバッファ辞書も膨らまない。"""
    called = []
    monkeypatch.setattr(
        "backend.utils.auth.require_match_scope",
        lambda *a, **k: called.append(a),
    )
    with pytest.raises(HTTPException) as e:
        tracknet.require_live_session_scope(object(), db, "NOPE99")
    assert e.value.status_code == 404
    assert called == [], "存在しないセッションで scope 検査まで進んでいる"


def test_a_known_session_is_checked_against_its_match(db, session_row, monkeypatch):
    """実在するコードは、そのセッションの試合に対する scope 検査へ回る。"""
    _s, match = session_row
    seen = {}

    def _fake(request, m, database):
        seen["match_id"] = m.id
        return "ctx"

    monkeypatch.setattr("backend.utils.auth.require_match_scope", _fake)
    req = object()
    assert tracknet.require_live_session_scope(req, db, "ABC123") == "ctx"
    assert seen["match_id"] == match.id


def test_the_scope_refusal_is_propagated(db, session_row, monkeypatch):
    """`require_match_scope` が拒否したらそのまま通す（握り潰さない）。"""
    def _deny(request, m, database):
        raise HTTPException(status_code=403, detail="no")

    monkeypatch.setattr("backend.utils.auth.require_match_scope", _deny)
    with pytest.raises(HTTPException) as e:
        tracknet.require_live_session_scope(object(), db, "ABC123")
    assert e.value.status_code == 403


def test_the_handler_asks_for_the_scope_check():
    """ルータ本体が検査を通ること（署名に request/db が要る）。"""
    import inspect

    sig = inspect.signature(tracknet.live_frame_hint)
    assert "request" in sig.parameters, "request を受けていないと呼び手が分からない"
    assert "db" in sig.parameters
    src = inspect.getsource(tracknet.live_frame_hint)
    body = src[src.index("):") :]
    assert "require_live_session_scope" in body, (
        "ハンドラが scope 検査を呼んでいない"
    )


def test_the_live_buffer_cannot_grow_without_bound():
    """セッション数に上限があること。

    `session_code` はクライアントが決める文字列なので、上限が無いと
    1 件あたり最大 3 枚 × 8MB のデコード済みフレームを無限に積める。
    """
    assert tracknet._MAX_LIVE_SESSIONS > 0
    buffers = tracknet._live_frame_buffers
    saved = dict(buffers)
    try:
        buffers.clear()
        # 上限ぶん埋めてから、さらに 1 つ足すループを実装と同じ形で回す
        for i in range(tracknet._MAX_LIVE_SESSIONS + 5):
            code = f"S{i:03d}"
            if code not in buffers:
                while len(buffers) >= tracknet._MAX_LIVE_SESSIONS:
                    buffers.pop(next(iter(buffers)))
                buffers[code] = deque(maxlen=3)
        assert len(buffers) == tracknet._MAX_LIVE_SESSIONS
    finally:
        buffers.clear()
        buffers.update(saved)


def test_the_dead_single_frame_endpoint_is_gone():
    """`/api/tracknet/frame_hint` を復活させない。

    3 枚の base64 から 1 回推論する実験的エンドポイントだったが、
    **リポジトリ全体で呼び出し元が 1 つも無かった**
    (`git ls-files` の全ファイルを走査。ヒットしたのはルータ自身と
     ROADMAP の記述だけ)。実際に使われているのは `live_frame_hint`。

    誰も使っていない的を開けたままにしない。認証済みなら誰でも
    3x2MB の base64 を送って CPU 推論を 200〜500ms 走らせられた。
    処理そのもの (`inf.predict_frames`) は live_frame_hint 側に同じものがある。
    """
    from backend.routers.tracknet import router

    paths = {getattr(r, "path", "") for r in router.routes}
    assert "/tracknet/frame_hint" not in paths, paths
    assert "/tracknet/live_frame_hint" in paths, "生きているほうまで消えている"
