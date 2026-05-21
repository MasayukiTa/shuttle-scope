"""demo ロールのチュートリアル限定 read-only 越権参照ゲートのテスト。

設計: private_docs/TUTORIAL_REVAMP_2026-05-21.md

検証する不変条件:
  1. player / coach / analyst は `?demo=1` かつ対象が demo データのとき GET 参照できる。
  2. その時レスポンスに X-Is-Demo: 1 が付く。
  3. `?demo=1` が無ければ従来どおり拒否される（越権不可）。
  4. `?demo=1` でも対象が **実データ** なら拒否される（実データ横展開を許さない）。
  5. demo 対象でも書き込み (PUT/POST/DELETE) は一切許可されない（GET-only）。
"""
from __future__ import annotations

import pytest
from datetime import date
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import User, Player, Match, Team
from backend.routers.auth import _hash_password
from backend.utils.jwt_utils import create_access_token
import backend.main as main_mod
from backend.main import app

# TrustedHostMiddleware は production posture で testserver を拒否するため
# 許可リストに含まれる localhost を base_url に使う。
_BASE = "http://localhost"

DEMO_TEAM_ID = 7777
REAL_TEAM_ID = 8888
DEMO_PLAYER_ID = 7001
DEMO_OPP_ID = 7002
REAL_PLAYER_ID = 8001
REAL_PLAYER2_ID = 8002
PLAYER_UID = 11       # 自分=REAL_PLAYER_ID
PLAYER2_UID = 12      # 自分=REAL_PLAYER2_ID


def _wipe(db):
    for model in (Match, Player, User, Team):
        db.query(model).delete()
    db.commit()


@pytest.fixture()
def seeded(db_session):
    _wipe(db_session)
    db_session.add(Team(id=DEMO_TEAM_ID, display_id="__demo__", name="DEMO"))
    db_session.add(Team(id=REAL_TEAM_ID, display_id="REAL", name="Real Team"))
    # demo user (role=demo)
    db_session.add(User(
        id=500, username="testtest", role="demo", display_name="Demo",
        team_id=DEMO_TEAM_ID, player_id=DEMO_PLAYER_ID,
        hashed_credential=_hash_password("x"),
    ))
    # 実 player ユーザ 2 名（middleware の player_id 一致チェックを通すため DB に必要）
    db_session.add(User(
        id=PLAYER_UID, username="realp1", role="player", display_name="P1",
        team_id=REAL_TEAM_ID, player_id=REAL_PLAYER_ID,
        hashed_credential=_hash_password("x"),
    ))
    db_session.add(User(
        id=PLAYER2_UID, username="realp2", role="player", display_name="P2",
        team_id=REAL_TEAM_ID, player_id=REAL_PLAYER2_ID,
        hashed_credential=_hash_password("x"),
    ))
    # demo players
    db_session.add(Player(id=DEMO_PLAYER_ID, name="デモ太郎", team_id=DEMO_TEAM_ID))
    db_session.add(Player(id=DEMO_OPP_ID, name="デモ次郎", team_id=DEMO_TEAM_ID))
    # real players (not demo)
    db_session.add(Player(id=REAL_PLAYER_ID, name="実選手1", team_id=REAL_TEAM_ID))
    db_session.add(Player(id=REAL_PLAYER2_ID, name="実選手2", team_id=REAL_TEAM_ID))
    # demo match owned by demo team
    db_session.add(Match(
        id=9100, tournament="demo", tournament_level="その他", round="F",
        date=date(2025, 1, 1), format="singles",
        player_a_id=DEMO_PLAYER_ID, player_b_id=DEMO_OPP_ID, result="win",
        owner_team_id=DEMO_TEAM_ID,
    ))
    db_session.commit()
    # demo team cache をリセット（60s キャッシュが他テストの値を持つのを防ぐ）
    main_mod._DEMO_TEAM_CACHE["team_id"] = None
    main_mod._DEMO_TEAM_CACHE["ts"] = 0.0
    app.dependency_overrides[get_db] = lambda: db_session
    yield db_session
    app.dependency_overrides.clear()
    _wipe(db_session)


def _auth(role: str, *, user_id: int, player_id=None, team_id=None):
    tok = create_access_token(
        user_id=user_id, role=role, player_id=player_id,
        team_name="Real Team" if team_id else None, team_id=team_id,
    )
    return {"Authorization": f"Bearer {tok}"}


# ── player ロール ────────────────────────────────────────────────────────────

def test_player_can_read_demo_player_with_flag(seeded):
    client = TestClient(app, base_url=_BASE)
    h = _auth("player", user_id=PLAYER_UID, player_id=REAL_PLAYER_ID, team_id=REAL_TEAM_ID)
    r = client.get(f"/api/players/{DEMO_PLAYER_ID}?demo=1", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers.get("X-Is-Demo") == "1"


def test_player_denied_demo_player_without_flag(seeded):
    client = TestClient(app, base_url=_BASE)
    h = _auth("player", user_id=PLAYER_UID, player_id=REAL_PLAYER_ID, team_id=REAL_TEAM_ID)
    r = client.get(f"/api/players/{DEMO_PLAYER_ID}", headers=h)
    assert r.status_code == 403


def test_player_flag_does_not_unlock_real_data(seeded):
    """?demo=1 でも対象が実データなら越権不可（最重要の安全条件）。"""
    client = TestClient(app, base_url=_BASE)
    h = _auth("player", user_id=PLAYER2_UID, player_id=REAL_PLAYER2_ID, team_id=REAL_TEAM_ID)
    # 自分以外の実選手を demo フラグで覗こうとする → 越権不可
    r = client.get(f"/api/players/{REAL_PLAYER_ID}?demo=1", headers=h)
    assert r.status_code == 403


def test_demo_flag_is_get_only(seeded):
    """demo 対象でも書き込みは拒否。"""
    client = TestClient(app, base_url=_BASE)
    h = _auth("player", user_id=PLAYER_UID, player_id=REAL_PLAYER_ID, team_id=REAL_TEAM_ID)
    r = client.put(f"/api/players/{DEMO_PLAYER_ID}?demo=1", headers=h, json={"name": "hacked"})
    assert r.status_code in (403, 401)
    # 名前が書き換わっていないこと
    p = seeded.get(Player, DEMO_PLAYER_ID)
    assert p.name == "デモ太郎"


def test_player_demo_still_blocked_from_forbidden_analysis(seeded):
    """demo は「閲覧ロールの権限範囲」で見せる。player は demo でも
    EPV/弱点/research-tier を見られない（ロール階層制限は緩めない）。"""
    client = TestClient(app, base_url=_BASE)
    h = _auth("player", user_id=PLAYER_UID, player_id=REAL_PLAYER_ID, team_id=REAL_TEAM_ID)
    r = client.get(
        f"/api/analysis/received_vulnerability?player_id={DEMO_PLAYER_ID}&demo=1",
        headers=h,
    )
    assert r.status_code == 403, r.text


# ── coach ロール ─────────────────────────────────────────────────────────────

def test_coach_can_read_demo_match_with_flag(seeded):
    client = TestClient(app, base_url=_BASE)
    h = _auth("coach", user_id=22, team_id=REAL_TEAM_ID)
    r = client.get(f"/api/matches/9100?demo=1", headers=h)
    assert r.status_code == 200, r.text
    assert r.headers.get("X-Is-Demo") == "1"


def test_coach_denied_demo_match_without_flag(seeded):
    client = TestClient(app, base_url=_BASE)
    h = _auth("coach", user_id=22, team_id=REAL_TEAM_ID)
    r = client.get(f"/api/matches/9100", headers=h)
    # 他チーム所有の試合は存在を隠して 404
    assert r.status_code == 404
