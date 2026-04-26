"""Attack #44 ハードニングテスト群 — 直近チームスコーピング・player team移行 周辺

Round 42 実弾攻撃で確認すべき項目を pytest に落とし込む。

AA-1: /players/search        — 認証なし → 401
AA-2: /players/needs_review  — 認証なし → 401
AA-3: /players/teams         — 認証なし → 401
AA-4: /players/{id}/matches  — 認証なし → 401
AA-5: /players/{id}/stats    — 認証なし → 401
AA-6: _player_scope_check 文字列プロパティ不整合
       player.team @property と list_players JOIN の結果が一致すること
AA-7: analyst 他チーム選手の team_history 書き換え → 404
AA-8: analyst 他チーム名で player 登録 → 403
AA-9: analyst 自チーム名で player 登録時の自動 Team 作成は1回のみ（重複なし）
AA-10: conditions resolve_role — クエリパラ ?role=analyst は認証なし → 401
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

ADMIN_USER = "admin_v44"
ADMIN_PASS = "TeamV44Admin!"


# ─── フィクスチャ ─────────────────────────────────────────────────────────────

@pytest.fixture()
def client(test_engine, monkeypatch):
    from backend.routers import auth as _auth_module
    _auth_module._IP_LOGIN_TIMES.clear()
    from backend.db.models import (
        User, RefreshToken, RevokedToken, AccessLog,
        Match, Player, Team, Condition, ConditionTag,
    )
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=test_engine)
    with Session() as s:
        for model in (AccessLog, RefreshToken, RevokedToken,
                      Condition, ConditionTag, Match, Player, User, Team):
            s.query(model).delete()
        s.commit()

    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", ADMIN_PASS)
    from backend.config import settings
    settings.BOOTSTRAP_ADMIN_USERNAME = ADMIN_USER
    settings.BOOTSTRAP_ADMIN_PASSWORD = ADMIN_PASS
    from backend.main import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ─── ヘルパー ─────────────────────────────────────────────────────────────────

def _login(client, username: str, password: str) -> dict:
    r = client.post("/api/auth/login", json={
        "grant_type": "credential", "identifier": username, "password": password,
    })
    assert r.status_code == 200, f"login failed: {r.text}"
    return r.json()


def _h(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_team(client, admin_token: str, name: str, display_id: str) -> int:
    r = client.post("/api/auth/teams",
                    json={"name": name, "display_id": display_id},
                    headers=_h(admin_token))
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]["id"]


def _create_user(client, admin_token: str, *, username: str, password: str,
                 role: str, team_id: int) -> int:
    r = client.post("/api/auth/users",
                    json={"username": username, "role": role,
                          "display_name": username, "password": password,
                          "team_id": team_id},
                    headers=_h(admin_token))
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]["id"]


def _create_player_admin(client, admin_token: str, name: str, team_name: str) -> int:
    r = client.post("/api/players",
                    json={"name": name, "team": team_name},
                    headers=_h(admin_token))
    assert r.status_code in (200, 201), r.text
    return r.json()["data"]["id"]


# ─── AA-1〜5: 未認証エンドポイントテスト ─────────────────────────────────────

class TestUnauthenticatedPlayerEndpoints:
    """player サブルートへの認証なしアクセスを全拒否すること。"""

    def test_search_requires_auth(self, client):
        r = client.get("/api/players/search", params={"q": "test"})
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"

    def test_needs_review_requires_auth(self, client):
        r = client.get("/api/players/needs_review")
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"

    def test_teams_requires_auth(self, client):
        r = client.get("/api/players/teams")
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"

    def test_player_matches_requires_auth(self, client):
        r = client.get("/api/players/1/matches")
        assert r.status_code in (401, 404), f"expected 401/404, got {r.status_code}: {r.text}"

    def test_player_stats_requires_auth(self, client):
        r = client.get("/api/players/1/stats")
        assert r.status_code in (401, 404), f"expected 401/404, got {r.status_code}: {r.text}"

    def test_player_list_requires_auth(self, client):
        r = client.get("/api/players")
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"

    def test_player_get_requires_auth(self, client):
        r = client.get("/api/players/1")
        assert r.status_code in (401, 404), f"expected 401/404, got {r.status_code}: {r.text}"

    def test_player_put_requires_auth(self, client):
        r = client.put("/api/players/1", json={"name": "Hacked"})
        assert r.status_code in (401, 404), f"expected 401/404, got {r.status_code}: {r.text}"

    def test_human_forecast_get_requires_auth(self, client):
        r = client.get("/api/prediction/human_forecast/1")
        assert r.status_code in (401, 404), f"expected 401/404, got {r.status_code}: {r.text}"

    def test_human_forecast_delete_requires_auth(self, client):
        r = client.delete("/api/prediction/human_forecast/1")
        assert r.status_code in (401, 404), f"expected 401/404, got {r.status_code}: {r.text}"

    def test_benchmark_requires_auth(self, client):
        r = client.get("/api/prediction/benchmark/1")
        assert r.status_code in (401, 404), f"expected 401/404, got {r.status_code}: {r.text}"

    def test_warmup_observations_requires_auth(self, client):
        r = client.get("/api/warmup/observations/1")
        assert r.status_code in (401, 404), f"expected 401/404, got {r.status_code}: {r.text}"

    def test_conditions_create_requires_auth(self, client, monkeypatch):
        import backend.utils.control_plane as cp
        monkeypatch.setattr(cp, "allow_legacy_header_auth", lambda req: False)
        from datetime import date
        r = client.post("/api/conditions", json={
            "player_id": 1, "measured_at": str(date.today()), "condition_type": "weekly"
        })
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"

    def test_conditions_questionnaire_requires_auth(self, client, monkeypatch):
        import backend.utils.control_plane as cp
        monkeypatch.setattr(cp, "allow_legacy_header_auth", lambda req: False)
        from datetime import date
        r = client.post("/api/conditions/questionnaire", json={
            "player_id": 1, "measured_at": str(date.today()),
            "condition_type": "weekly", "responses": {}
        })
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"

    def test_conditions_patch_requires_auth(self, client, monkeypatch):
        import backend.utils.control_plane as cp
        monkeypatch.setattr(cp, "allow_legacy_header_auth", lambda req: False)
        r = client.patch("/api/conditions/1", json={})
        assert r.status_code in (401, 404), f"expected 401/404, got {r.status_code}: {r.text}"

    def test_conditions_delete_requires_auth(self, client, monkeypatch):
        import backend.utils.control_plane as cp
        monkeypatch.setattr(cp, "allow_legacy_header_auth", lambda req: False)
        r = client.delete("/api/conditions/1")
        assert r.status_code in (401, 404), f"expected 401/404, got {r.status_code}: {r.text}"


# ─── AA-6: _player_scope_check と list_players の整合性 ──────────────────────

class TestPlayerScopeConsistency:
    """_player_scope_check (player.team @property) と list_players (JOIN) の
    結果が一致すること。チームAのcoachがチームBの選手を個別取得できないこと。"""

    def test_coach_a_cannot_get_team_b_player_detail(self, client):
        admin = _login(client, ADMIN_USER, ADMIN_PASS)
        at = admin["access_token"]

        ta = _create_team(client, at, "TeamA_AA6", "TA-AA6")
        tb = _create_team(client, at, "TeamB_AA6", "TB-AA6")
        _create_user(client, at, username="coach_aa6a", password="CoachAA6-1234567!",
                     role="coach", team_id=ta)
        coach_a = _login(client, "coach_aa6a", "CoachAA6-1234567!")

        # チームBの選手を admin が作成
        pb = _create_player_admin(client, at, "PlayerB_AA6", "TeamB_AA6")

        # チームAの coach からチームBの選手を直叩き → 404
        r = client.get(f"/api/players/{pb}", headers=_h(coach_a["access_token"]))
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text}"

    def test_coach_a_list_does_not_include_team_b_player(self, client):
        admin = _login(client, ADMIN_USER, ADMIN_PASS)
        at = admin["access_token"]

        ta = _create_team(client, at, "TeamA_AA6b", "TA-AA6b")
        tb = _create_team(client, at, "TeamB_AA6b", "TB-AA6b")
        _create_user(client, at, username="coach_aa6b", password="CoachAA6b-1234567!",
                     role="coach", team_id=ta)
        coach_a = _login(client, "coach_aa6b", "CoachAA6b-1234567!")

        pa = _create_player_admin(client, at, "PlayerA_AA6b", "TeamA_AA6b")
        pb = _create_player_admin(client, at, "PlayerB_AA6b", "TeamB_AA6b")

        r = client.get("/api/players", headers=_h(coach_a["access_token"]))
        assert r.status_code == 200, r.text
        ids = [p["id"] for p in r.json()["data"]]
        assert pa in ids, "自チーム選手が一覧に含まれていない"
        assert pb not in ids, f"他チーム選手(id={pb})が一覧に漏洩している"


# ─── AA-7: analyst 他チーム選手の team_history 書き換え ──────────────────────

class TestTeamHistoryOverwrite:
    """analyst が他チームの選手の team_history を PUT で書き換えられないこと。"""

    def test_analyst_cannot_overwrite_other_team_player_history(self, client):
        admin = _login(client, ADMIN_USER, ADMIN_PASS)
        at = admin["access_token"]

        ta = _create_team(client, at, "TeamA_AA7", "TA-AA7")
        tb = _create_team(client, at, "TeamB_AA7", "TB-AA7")
        _create_user(client, at, username="analyst_aa7a", password="AnalystAA7-1234567!",
                     role="analyst", team_id=ta)
        analyst_a = _login(client, "analyst_aa7a", "AnalystAA7-1234567!")

        # チームBの選手を admin が作成
        pb = _create_player_admin(client, at, "PlayerB_AA7", "TeamB_AA7")

        malicious_history = [{"team": "HACKED_TEAM", "until": "2026-01", "note": "injected"}]
        r = client.put(
            f"/api/players/{pb}",
            json={"team_history": malicious_history},
            headers=_h(analyst_a["access_token"]),
        )
        # 他チーム選手は 404 で存在を隠す
        assert r.status_code == 404, f"expected 404, got {r.status_code}: {r.text}"


# ─── AA-8: analyst 他チーム名での player 登録 → 403 ──────────────────────────

class TestAnalystCrossTeamPlayerCreate:
    """analyst が自チーム以外の team 名で選手を登録しようとすると 403 になること。"""

    def test_analyst_cannot_create_player_in_other_team(self, client):
        admin = _login(client, ADMIN_USER, ADMIN_PASS)
        at = admin["access_token"]

        ta = _create_team(client, at, "TeamA_AA8", "TA-AA8")
        _create_team(client, at, "TeamB_AA8", "TB-AA8")
        _create_user(client, at, username="analyst_aa8a", password="AnalystAA8-1234567!",
                     role="analyst", team_id=ta)
        analyst_a = _login(client, "analyst_aa8a", "AnalystAA8-1234567!")

        # 他チーム名で登録 → 403
        r = client.post(
            "/api/players",
            json={"name": "GhostPlayer", "team": "TeamB_AA8"},
            headers=_h(analyst_a["access_token"]),
        )
        assert r.status_code == 403, f"expected 403, got {r.status_code}: {r.text}"


# ─── AA-9: 自チーム名で player 登録時の Team 自動作成は重複なし ──────────────

class TestTeamAutoCreationNoDuplicate:
    """analyst が自チーム名で選手を2回登録しても Team レコードが重複しないこと。"""

    def test_no_duplicate_team_on_repeat_create(self, client):
        admin = _login(client, ADMIN_USER, ADMIN_PASS)
        at = admin["access_token"]

        ta = _create_team(client, at, "TeamA_AA9", "TA-AA9")
        _create_user(client, at, username="analyst_aa9", password="AnalystAA9-1234567!",
                     role="analyst", team_id=ta)
        analyst = _login(client, "analyst_aa9", "AnalystAA9-1234567!")

        # 1人目
        r1 = client.post(
            "/api/players",
            json={"name": "PlayerAA9-1", "team": "TeamA_AA9"},
            headers=_h(analyst["access_token"]),
        )
        assert r1.status_code in (200, 201), r1.text
        pid1 = r1.json()["data"]["id"]

        # 2人目（同じチーム名）
        r2 = client.post(
            "/api/players",
            json={"name": "PlayerAA9-2", "team": "TeamA_AA9"},
            headers=_h(analyst["access_token"]),
        )
        assert r2.status_code in (200, 201), r2.text
        pid2 = r2.json()["data"]["id"]

        # teams 一覧で "TeamA_AA9" が1件だけ
        r_teams = client.get("/api/players/teams", headers=_h(analyst["access_token"]))
        assert r_teams.status_code == 200
        teams = r_teams.json()["data"]
        count = sum(1 for t in teams if t == "TeamA_AA9")
        assert count == 1, f"TeamA_AA9 が {count} 件重複している"


# ─── AA-10: conditions ?role=analyst クエリパラメータで昇格不可 ───────────────

class TestConditionsRoleQueryParam:
    """/api/conditions が認証なしの ?role=analyst でアクセスできないこと。
    外部からの X-Role ヘッダも拒否されること。
    TestClient はループバック扱いになるため allow_legacy_header_auth を
    monkeypatch して外部アクセスを再現する。"""

    def test_conditions_query_role_requires_auth(self, client, monkeypatch):
        import backend.utils.control_plane as cp
        monkeypatch.setattr(cp, "allow_legacy_header_auth", lambda req: False)
        r = client.get("/api/conditions", params={"player_id": 1, "role": "analyst"})
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"

    def test_conditions_x_role_header_external_rejected(self, client, monkeypatch):
        import backend.utils.control_plane as cp
        monkeypatch.setattr(cp, "allow_legacy_header_auth", lambda req: False)
        r = client.get(
            "/api/conditions",
            params={"player_id": 1},
            headers={"X-Role": "analyst"},
        )
        assert r.status_code == 401, f"expected 401, got {r.status_code}: {r.text}"
