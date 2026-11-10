"""item #690 (案 A): POST /api/video_import/by_match/{match_id} の認可・入力検証テスト。

クライアントは生の filesystem パスも表示用ストリーム URL も送らず、match_id だけを送る。
サーバが試合レコード (video_local_path) から動画を解決してバックグラウンド解析を開始する。

- 非運用ロール (player/demo/llm) と anon は 403/401、ジョブは一切投入されない
- 他チームの analyst は自チーム外の試合に到達できない (403/404)
- 運用ロール (coach/analyst/admin, 自チーム) は 200 で _run_pipeline が呼ばれる
- サーバに動画が無い試合 (video_local_path 空 / 非ファイル URL) は 409 no_video_on_server で
  «自動で何も始めない»
- 同一 match の未完了ジョブがあるとき、二重開始は 409 analysis_already_running
- path_jail 外のパスは 403 (本物の is_allowed_video_path で検証)

TestClient は middleware を全部載せた本物の backend.main.app を通す。重い解析
(_run_pipeline) は差し替え、path_jail は原則 True 固定にして «認可と状態遷移だけ» を見る。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db import models as M
from backend.db.database import get_db
from backend.main import app
from backend.routers import video_import as vi
from backend.routers.auth import _hash_password
from backend.utils.jwt_utils import create_access_token

TEAM_A = 8811
TEAM_B = 8812


@pytest.fixture()
def env(db_session, monkeypatch, tmp_path):
    db = db_session
    db.add_all([
        M.Team(id=TEAM_A, display_id="VIM-A", name="VIM Team A"),
        M.Team(id=TEAM_B, display_id="VIM-B", name="VIM Team B"),
    ])
    pa = M.Player(name="VIM PA", name_normalized="vim pa", team_id=TEAM_A)
    pb = M.Player(name="VIM PB", name_normalized="vim pb", team_id=TEAM_A)
    db.add_all([pa, pb])
    db.flush()

    video = tmp_path / "match.mp4"
    video.write_bytes(b"\x00" * 32)

    def _match(video_local_path):
        m = M.Match(tournament="VIM", tournament_level="domestic", round="QF",
                    date=date(2026, 10, 18), format="singles", result="unknown",
                    is_public_pool=False, player_a_id=pa.id, player_b_id=pb.id,
                    owner_team_id=TEAM_A, video_local_path=video_local_path)
        db.add(m)
        db.flush()
        return m

    m = _match(str(video))
    m_novideo = _match(None)
    m_urlvideo = _match("https://example.com/stream.m3u8")

    users = {}
    for role, team in (("player", TEAM_A), ("demo", TEAM_A), ("llm", TEAM_A), ("coach", TEAM_A),
                       ("analyst", TEAM_A), ("admin", None), ("analystB", TEAM_B)):
        base = "analyst" if role == "analystB" else role
        u = M.User(username=f"vim_{role}", role=base, display_name=role,
                   hashed_credential=_hash_password("pw"),
                   player_id=pa.id if role == "player" else None,
                   team_id=team,
                   team_name=None if team is None else ("VIM Team A" if team == TEAM_A else "VIM Team B"),
                   consent_required=False)
        db.add(u)
        users[role] = u
    db.commit()

    monkeypatch.setattr(vi, "_jobs", {})
    calls: list[str] = []
    monkeypatch.setattr(vi, "_run_pipeline", lambda job_id: calls.append(job_id))
    from backend.utils import path_jail
    monkeypatch.setattr(path_jail, "is_allowed_video_path", lambda p: True)
    app.dependency_overrides[get_db] = lambda: db
    try:
        yield {"client": TestClient(app, raise_server_exceptions=False), "db": db,
               "mid": m.id, "mid_novideo": m_novideo.id, "mid_urlvideo": m_urlvideo.id,
               "users": users, "calls": calls, "video": video, "path_jail": path_jail}
    finally:
        app.dependency_overrides.clear()


def _hdr(env, role):
    if role == "anon":
        return {}
    u = env["users"][role]
    base = "analyst" if role == "analystB" else role
    tok = create_access_token(user_id=u.id, role=base, player_id=u.player_id,
                              team_name=u.team_name, team_id=u.team_id)
    return {"Authorization": f"Bearer {tok}"}


def _post(env, role, mid):
    return env["client"].post(f"/api/video_import/by_match/{mid}", headers=_hdr(env, role), json={})


# ─── 認可 ─────────────────────────────────────────

@pytest.mark.parametrize("role", ["player", "demo", "llm"])
def test_non_operator_roles_get_403_and_no_job(env, role):
    r = _post(env, role, env["mid"])
    assert r.status_code == 403, (role, r.status_code, r.text)
    assert env["calls"] == [] and vi._jobs == {}


def test_anonymous_is_rejected_and_no_job(env):
    r = _post(env, "anon", env["mid"])
    assert r.status_code in (401, 403), r.text
    assert env["calls"] == [] and vi._jobs == {}


def test_other_teams_analyst_cannot_start_for_team_a_match(env):
    r = _post(env, "analystB", env["mid"])
    assert r.status_code in (403, 404), r.text
    assert env["calls"] == [] and vi._jobs == {}


@pytest.mark.parametrize("role", ["coach", "analyst", "admin"])
def test_operators_start_analysis(env, role):
    r = _post(env, role, env["mid"])
    assert r.status_code == 200, r.text
    jid = r.json()["data"]["job_id"]
    assert env["calls"] == [jid]
    assert vi._jobs[jid]["match_id"] == env["mid"]
    # 生の filesystem パスはレスポンスに漏れない
    assert "video_path" not in r.text and str(env["video"]) not in r.text


# ─── 動画が無い試合は自動開始しない ────────────────────────

def test_match_without_video_returns_409_and_no_job(env):
    r = _post(env, "analyst", env["mid_novideo"])
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "no_video_on_server"
    assert env["calls"] == [] and vi._jobs == {}


def test_match_with_url_video_returns_409_and_no_job(env):
    r = _post(env, "analyst", env["mid_urlvideo"])
    assert r.status_code == 409, r.text
    assert r.json()["detail"]["code"] == "no_video_on_server"
    assert env["calls"] == [] and vi._jobs == {}


def test_missing_match_returns_404(env):
    r = _post(env, "analyst", 99999)
    assert r.status_code == 404, r.text
    assert env["calls"] == [] and vi._jobs == {}


# ─── 二重開始防止 ────────────────────────────────

def test_duplicate_start_is_rejected(env):
    r1 = _post(env, "analyst", env["mid"])
    assert r1.status_code == 200, r1.text
    r2 = _post(env, "analyst", env["mid"])
    assert r2.status_code == 409, r2.text
    assert r2.json()["detail"]["code"] == "analysis_already_running"
    # ジョブは 1 つのまま、_run_pipeline も 1 回だけ
    assert len(vi._jobs) == 1 and len(env["calls"]) == 1


# ─── path_jail ───────────────────────────────────

def test_path_outside_jail_is_rejected(env, monkeypatch):
    # 本物の is_allowed_video_path を使い、許可ルート外は 403
    monkeypatch.setattr(env["path_jail"], "is_allowed_video_path", lambda p: False)
    r = _post(env, "analyst", env["mid"])
    assert r.status_code == 403, r.text
    assert env["calls"] == [] and vi._jobs == {}
