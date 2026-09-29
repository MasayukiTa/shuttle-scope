"""テスト基盤の guardrail。

CI で再発させたくない 2 点を明示的に固定する:

1. test_engine / Base.metadata.create_all により shared_sessions などの
   LAN / WebSocket 系テーブルまで in-memory DB に作られること
2. WebSocket 系テストヘルパが backend.db.database.SessionLocal の差し替えを
   実行時に参照し、古い import 済みセッションを握らないこと
"""

from datetime import date

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.db import database as db_module
from backend.db.database import Base
from backend.db.models import Match, Player, SessionParticipant, SharedSession
from backend.tests.test_websocket_signaling import _ensure_active_session


class TestInMemoryHarnessSchema:
    def test_shared_session_tables_exist_in_test_engine(self, test_engine):
        """WebSocket / LAN 系テーブルまで test_engine に作られている。"""
        tables = set(inspect(test_engine).get_table_names())
        assert "shared_sessions" in tables
        assert "session_participants" in tables
        assert "live_sources" in tables


class TestSessionLocalRebinding:
    def test_websocket_helper_uses_runtime_sessionlocal(self, monkeypatch):
        """_ensure_active_session が import 時の SessionLocal ではなく runtime の差し替えを見る。"""
        alt_engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(alt_engine)
        alt_session_local = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=alt_engine,
        )

        monkeypatch.setattr(db_module, "engine", alt_engine)
        monkeypatch.setattr(db_module, "SessionLocal", alt_session_local)

        code = "GDR" + "A1B2C3"
        _ensure_active_session(code)

        db = alt_session_local()
        try:
            session = (
                db.query(SharedSession)
                .filter(SharedSession.session_code == code)
                .first()
            )
            assert session is not None
            assert session.is_active is True

            participants = (
                db.query(SessionParticipant)
                .filter(SessionParticipant.session_id == session.id)
                .all()
            )
            assert len(participants) == 3

            match = db.get(Match, session.match_id)
            assert match is not None
            player_a = db.get(Player, match.player_a_id)
            player_b = db.get(Player, match.player_b_id)
            assert player_a is not None and player_b is not None
            assert match.date == date(2026, 4, 12)
        finally:
            db.close()
            alt_engine.dispose()


class TestSessionsDoNotShareOneConnection:
    """test_engine の Session どうしがトランザクションを共有していないこと。

    以前の test_engine は `:memory:` + StaticPool だった。StaticPool は DBAPI
    接続を 1 本しか持たないので、プロセス内の全 Session が同じ接続 = 同じ
    トランザクションに乗る。アプリの同期エンドポイントは threadpool の別
    スレッドで動き、`_stale_device_cleanup` は 30 秒ごとに event loop
    スレッドで `with SessionLocal() as db:` を開いて閉じる (= ROLLBACK)。
    その ROLLBACK が別スレッドの flush 済み・commit 前の INSERT を消す。

    CI (linux, xdist) で実際に観測した症状:

        POST /api/players -> players.py db.refresh(player)
        sqlalchemy.exc.InvalidRequestError: Could not refresh instance '<Player>'

    commit した直後の行が 1 文あとに消えていた。間欠的にしか出ないので
    「flaky」で片付きやすい。ここで機構そのものを固定する。
    """

    def test_a_rollback_in_one_session_does_not_destroy_anothers_write(self, test_engine):
        Session = sessionmaker(bind=test_engine)
        writer = Session()
        try:
            p = Player(name="ハーネス隔離確認", dominant_hand="R")
            writer.add(p)
            writer.flush()          # INSERT 済み・未 commit
            pid = p.id

            # 別 Session が同じ engine で読み、閉じる (= ROLLBACK)。
            # 接続が共有されていれば、この ROLLBACK が上の INSERT を巻き戻す。
            other = Session()
            try:
                other.query(Player).count()
            finally:
                other.close()

            writer.commit()
        finally:
            writer.close()

        reader = Session()
        try:
            assert reader.get(Player, pid) is not None, (
                "別 Session の rollback で commit 済みの行が消えた"
                " — Session が 1 本の接続を共有している"
            )
            reader.query(Player).filter(Player.id == pid).delete()
            reader.commit()
        finally:
            reader.close()
