"""`db.refresh()` 掃引: 応答を組み立てるためだけの再 SELECT をやめる。

ハンドラは `db.commit()` の直後に `db.refresh(obj)` を呼んでいた。既定の
`expire_on_commit=True` では commit した瞬間に全属性が expire するので、
応答に値を入れるには読み直すしかなかったからである。

その `refresh` は **トランザクションの外で走る 2 回目の SELECT** で、
その間に行が消えていれば `ObjectDeletedError` になり 500 を返す
（`create_player` で CI が実際に踏んだ）。同じ形が routers に 51 箇所あった。

ハンドラのセッションは 1 リクエストで閉じるので、commit 後に属性を保持して
困ることはない。`get_db` が配るセッションだけ `expire_on_commit=False` にして、
refresh を要らなくした。

**`SessionLocal` は変えていない。** 背景ワーカーは 1 セッションを長く持って
何度も commit するので、expire を切ると identity map の行が古い値を返し続ける。

`backend.main` を import しないので Python 3.10 でも走る。
"""
from __future__ import annotations

import ast
import pathlib

import sqlalchemy as sa

import backend.db.database as db_module
from backend.db.database import SessionLocal, get_db
from backend.db.models import Base, Player


def _scratch_engine():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


def _request_session(engine):
    """`get_db` と同じ設定のセッションを、テスト用 engine に向けて取る。

    `get_db` はジェネレータなので、engine を差し替えて 1 個取り出す。
    ここで独自に `sessionmaker(expire_on_commit=False)` を書くと
    **実装ではなく写しを検証する**ことになるので、本物を通す。
    """
    original = db_module.SessionLocal
    from sqlalchemy.orm import sessionmaker
    db_module.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine
    )
    try:
        gen = get_db()
        return next(gen)
    finally:
        db_module.SessionLocal = original


def test_get_db_goes_through_the_module_level_SessionLocal():
    """`get_db` が **その時点の** `SessionLocal` を使うこと。

    `backend/tests/conftest.py` はテスト用 engine に向けるために
    `db_module.SessionLocal` を差し替える。`get_db` が別の sessionmaker を
    持つと、**リクエスト経路だけ本物の DB を見に行く**。
    2026-09-22 に実際にそれをやって、CI のログイン系が全部 401 になった
    （テスト DB に作ったユーザが、ハンドラからは存在しないため）。
    """
    import sqlalchemy as sa
    from sqlalchemy.orm import sessionmaker

    marker = sa.create_engine("sqlite://")
    original = db_module.SessionLocal
    db_module.SessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=marker
    )
    try:
        gen = get_db()
        db = next(gen)
        assert db.get_bind() is marker, (
            "get_db が差し替え後の SessionLocal を通っていない。"
            "テストの engine 差し替えがリクエスト経路に効かない"
        )
        assert db.expire_on_commit is False
        db.close()
    finally:
        db_module.SessionLocal = original


def test_the_session_class_itself_still_expires_on_commit():
    """`SessionLocal()` を直に呼ぶ経路（背景ワーカー）は既定のまま。"""
    assert SessionLocal.kw.get("expire_on_commit", True) is True


def test_commit_does_not_expire_attributes_on_the_request_session():
    """commit 後に属性を読んでも SQL が飛ばないこと。

    「expire していない」を `inspect().expired` で見るだけでは、実際に
    SELECT が消えたことの証拠にならない（遅延ロードは別経路でも起きる）。
    発行 SQL を数える。
    """
    engine = _scratch_engine()
    statements: list[str] = []

    @sa.event.listens_for(engine, "before_cursor_execute")
    def _record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    db = _request_session(engine)
    try:
        p = Player(name="A")
        db.add(p)
        db.commit()
        statements.clear()
        # 応答を組み立てるつもりで属性を読む
        assert p.name == "A"
        assert p.id is not None
    finally:
        db.close()

    assert statements == [], f"commit 後の属性読み出しで SQL が飛んでいる: {statements}"


def test_the_worker_session_still_expires_on_commit():
    """長寿命セッションの側は既定のままであること。

    ここを一緒に変えると、ポーリングするワーカーが identity map に載った
    古い行をいつまでも返すようになる。
    """
    engine = _scratch_engine()
    db = SessionLocal(bind=engine)
    try:
        p = Player(name="A")
        db.add(p)
        db.commit()
        assert sa.inspect(p).expired is True
    finally:
        db.close()


def test_request_handlers_no_longer_refresh_after_commit():
    """`Depends(get_db)` を取るハンドラに `db.refresh` が残っていないこと。

    許すのは 1 箇所だけ: `auth.py` の `_on_login_failure` は
    `synchronize_session=False` の一括 UPDATE で ORM を迂回しているので、
    読み直さないと古い `failed_attempts` で判定してしまう。
    そこは `Depends(get_db)` を取るハンドラではないので、そもそもここの
    対象に入らない。
    """
    routers = pathlib.Path(__file__).resolve().parents[1] / "routers"
    offenders: list[str] = []

    for path in sorted(routers.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        if "db.refresh(" not in src:
            continue
        tree = ast.parse(src)
        # `str.splitlines()` は U+2028/U+2029 でも切るが Python のトークナイザは
        # 切らない。matches.py / uploads.py / text_sanitize.py は bidi サニタイザの
        # 定義として実際にその文字を持っているので、AST の行番号と 1 行ずれる。
        lines = src.split("\n")
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not _takes_request_db(node):
                continue
            for i in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                if "db.refresh(" in lines[i - 1]:
                    offenders.append(f"{path.name}:{i}: {lines[i - 1].strip()}")

    assert not offenders, (
        "commit 後の再 SELECT が戻っている。行が同時に消えると 500 になる:\n  "
        + "\n  ".join(offenders)
    )


def _takes_request_db(fn: ast.AST) -> bool:
    args = getattr(fn, "args", None)
    if args is None:
        return False
    padded = [None] * (len(args.args) - len(args.defaults)) + list(args.defaults)
    for default, arg in zip(padded, args.args):
        if arg.arg == "db" and default is not None and "get_db" in ast.dump(default):
            return True
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        if arg.arg == "db" and default is not None and "get_db" in ast.dump(default):
            return True
    return False
