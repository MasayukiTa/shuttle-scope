"""「ログインできる」と「見てよい」を混同していた箇所 (2026-09-23)。

公開登録を開けたままにする判断をしたので、**誰でも取れるトークン**で何が
読めるのかを洗った。出てきたのは「role が None でなければ通す」「scope が
NULL なら照合を飛ばす」という形の 4 件で、いずれも認証と認可を取り違えている。

- `/api/insights/growth_snapshot`: player_id を持たない player は照合ごと
  飛ばされ、任意の ?player_id= を指定できた
- `/api/players/teams`: 認証さえ通れば全チーム名を列挙できた
- `/api/youtube_live/jobs`: 認証さえ通れば全 job とサーバの絶対パスが読めた
- `WS /ws/live/{session_code}`: 有効な JWT と 6 文字のコードだけで、その試合の
  スナップショット (スコア・直近ラリー・選手名) を購読できた
"""
from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import Match, Player, SharedSession, Team, User
from backend.main import app, _ws_session_allowed
from backend.routers.auth import _hash_password
from backend.utils.jwt_utils import create_access_token


def _headers(role: str, user_id: int, player_id=None, team_id=None, team_name=None) -> dict:
    token = create_access_token(user_id=user_id, role=role, player_id=player_id,
                                team_name=team_name, team_id=team_id)
    return {"Authorization": f"Bearer {token}"}


def _seed_player_user(db_session, username: str, player_name: str) -> tuple[User, Player]:
    p = Player(name=player_name)
    db_session.add(p)
    db_session.flush()
    u = User(username=username, role="player", display_name=player_name,
             hashed_credential=_hash_password("pw"), player_id=p.id,
             consent_required=False)
    db_session.add(u)
    db_session.commit()
    return u, p


def _seed_match(db_session, player_a: Player, player_b: Player) -> Match:
    m = Match(tournament="テスト大会", tournament_level="practice", round="R1",
              date=date(2026, 9, 23), venue="体育館", format="singles",
              result="win", final_score="21-10",
              player_a_id=player_a.id, player_b_id=player_b.id)
    db_session.add(m)
    db_session.commit()
    return m


class TestGrowthSnapshotIdentityCheck:
    """`ctx.player_id is not None` を条件に入れると、NULL が素通りになる。"""

    def test_a_player_without_a_player_id_cannot_pass_an_arbitrary_player_id(self):
        # HTTP 経由では PlayerAccessControlMiddleware が player_id 無しの player を
        # 先に 401 にするため、この欠陥はリクエストからは踏めない。
        # 「middleware のその一行が守っている」だけなので、ハンドラの判定そのものを
        # 直接呼んで閉じていることを確かめる (TestClient 経由だと middleware の
        # 401 で必ず通ってしまい、テストが欠陥を見逃す)。
        import pytest as _pytest
        from fastapi import HTTPException as _HTTPException
        from backend.routers.insights import get_growth_snapshot
        from backend.utils.auth import AuthCtx

        ctx = AuthCtx("player", None, None, user_id=1, team_id=None)
        with _pytest.raises(_HTTPException) as err:
            get_growth_snapshot(request=None, player_id=1234, period_days=30,
                                lang="ja", ctx=ctx)
        assert err.value.status_code == 403

    def test_a_player_can_still_read_their_own(self, db_session):
        u, p = _seed_player_user(db_session, "own_snapshot", "本人")
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(f"/api/insights/growth_snapshot?player_id={p.id}",
                              headers=_headers("player", u.id, player_id=p.id))
            assert resp.status_code == 200, resp.text
        finally:
            app.dependency_overrides.clear()

    def test_a_player_cannot_read_someone_elses(self, db_session):
        u, p = _seed_player_user(db_session, "not_yours", "本人2")
        other = Player(name="他人")
        db_session.add(other)
        db_session.commit()
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get(f"/api/insights/growth_snapshot?player_id={other.id}",
                              headers=_headers("player", u.id, player_id=p.id))
            assert resp.status_code == 403, resp.text
        finally:
            app.dependency_overrides.clear()


class TestOperationalReadsAreNotOpenToPlayers:
    def test_team_listing_is_closed_to_players(self, db_session):
        u, p = _seed_player_user(db_session, "team_list_player", "選手")
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/players/teams",
                              headers=_headers("player", u.id, player_id=p.id))
            assert resp.status_code == 403, resp.text
        finally:
            app.dependency_overrides.clear()

    def test_team_listing_still_works_for_an_analyst(self, db_session):
        team = Team(display_id="TEST-7001", name="テストチーム")
        db_session.add(team)
        db_session.flush()
        db_session.add(Player(name="所属選手", team_id=team.id))
        u = User(username="an_analyst_tl", role="analyst", display_name="A",
                 hashed_credential=_hash_password("pw"), team_id=team.id,
                 team_name=team.name, consent_required=False)
        db_session.add(u)
        db_session.commit()
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/players/teams",
                              headers=_headers("analyst", u.id, team_id=team.id,
                                               team_name=team.name))
            assert resp.status_code == 200, resp.text
            assert "テストチーム" in resp.json()["data"]
        finally:
            app.dependency_overrides.clear()

    def test_recording_jobs_are_closed_to_players(self, db_session):
        u, p = _seed_player_user(db_session, "yt_player", "選手2")
        app.dependency_overrides[get_db] = lambda: db_session
        try:
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/api/youtube_live/jobs",
                              headers=_headers("player", u.id, player_id=p.id))
            assert resp.status_code == 403, resp.text
        finally:
            app.dependency_overrides.clear()


class TestLiveFeedNeedsMatchAccessNotJustACode:
    def _session_for(self, db_session, match: Match, code: str) -> SharedSession:
        s = SharedSession(match_id=match.id, session_code=code, is_active=True)
        db_session.add(s)
        db_session.commit()
        return s

    def test_a_player_in_the_match_may_subscribe(self, db_session):
        u, p = _seed_player_user(db_session, "live_in", "出場選手")
        other = Player(name="相手")
        db_session.add(other)
        db_session.flush()
        m = _seed_match(db_session, p, other)
        self._session_for(db_session, m, "AAA111")
        payload = {"role": "player", "sub": str(u.id), "player_id": p.id}
        assert _ws_session_allowed(payload, "AAA111", db_session) is True

    def test_a_player_not_in_the_match_may_not(self, db_session):
        _u_in, p_in = _seed_player_user(db_session, "live_owner", "出場選手2")
        other = Player(name="相手2")
        db_session.add(other)
        db_session.flush()
        m = _seed_match(db_session, p_in, other)
        self._session_for(db_session, m, "BBB222")

        outsider_u, outsider_p = _seed_player_user(db_session, "live_outsider", "無関係")
        payload = {"role": "player", "sub": str(outsider_u.id),
                   "player_id": outsider_p.id}
        assert _ws_session_allowed(payload, "BBB222", db_session) is False

    def test_a_player_without_a_player_id_may_not(self, db_session):
        _u, p = _seed_player_user(db_session, "live_pidless_owner", "出場選手3")
        other = Player(name="相手3")
        db_session.add(other)
        db_session.flush()
        m = _seed_match(db_session, p, other)
        self._session_for(db_session, m, "CCC333")
        assert _ws_session_allowed({"role": "player", "sub": "0"},
                                   "CCC333", db_session) is False

    def test_an_unknown_session_code_is_refused(self, db_session):
        assert _ws_session_allowed({"role": "admin", "sub": "1"},
                                   "ZZZ999", db_session) is False
