"""参加者向け未認証入口 (join / ice-config / heartbeat) の残存ギャップ対策。

対象:
  5. ice-config / heartbeat にレート制限が無く、セッション不在 / 参加者不在 /
     token 不一致の応答が違った。join も存在しない code は 404、既存 code は 401
     で、有効な code の oracle になっていた (所要時間も違う)。
  6. code 単位の失敗ロックアウトは、code を知る誰かが 10 回失敗するだけで
     正規の参加・再接続まで全部止められた。(code, IP) 単位に変える。
  7. password_hash が NULL のセッションはパスワード無しで参加できた。
  8. 制限用 dict が攻撃者の選ぶ code / IP でいくらでも伸びた。
"""
import time
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db import database as db_module
from backend.db.models import Match, Player, SharedSession
from backend.main import app
from backend.routers import sessions as sessions_mod
from backend.routers.sessions import _hash_password
from backend.utils import ws_ticket
from backend.ws.camera import camera_manager

_PASSWORD = "camera-pass-1234"


def _clear_limiters():
    with sessions_mod._JOIN_RATE_LOCK:
        sessions_mod._JOIN_FAILURES.clear()
        sessions_mod._JOIN_IP_FAILURES.clear()
        sessions_mod._JOIN_CODE_FAILURES.clear()


@pytest.fixture(autouse=True)
def _clean_state():
    _clear_limiters()
    yield
    _clear_limiters()
    camera_manager._sessions.clear()
    camera_manager._operator_owners.clear()
    ws_ticket.clear_ws_tickets()


def _make_session(code: str, password: str | None = _PASSWORD) -> None:
    db = db_module.SessionLocal()
    try:
        pa = Player(name=f"{code}_A")
        pb = Player(name=f"{code}_B")
        db.add_all([pa, pb])
        db.flush()
        match = Match(
            tournament="JH Test", tournament_level="IC", round="R1",
            date=date(2026, 8, 15), format="singles",
            player_a_id=pa.id, player_b_id=pb.id, result="win",
        )
        db.add(match)
        db.flush()
        db.add(SharedSession(
            match_id=match.id, session_code=code, created_by_role="analyst",
            is_active=True,
            password_hash=_hash_password(password) if password else None,
        ))
        db.commit()
    finally:
        db.close()


def _ip(n: str) -> dict[str, str]:
    """TestClient の peer は loopback 扱いなので X-Forwarded-For で送信元 IP を変えられる。"""
    return {"X-Forwarded-For": n}


def _join(client, code, ip="10.0.0.1", **overrides):
    body = {
        "role": "viewer", "device_name": "iPhone", "device_type": "iphone",
        "session_password": _PASSWORD,
    }
    body.update(overrides)
    return client.post(f"/api/sessions/{code}/join", json=body, headers=_ip(ip))


def _same(a, b):
    return (a.status_code, a.json()) == (b.status_code, b.json())


# ── 5. 一般化された 401 ────────────────────────────────────────────────────

def test_join_unknown_code_is_indistinguishable_from_wrong_password():
    _make_session("JHK001")
    with TestClient(app, base_url="http://localhost") as client:
        unknown = _join(client, "NOSUCH", ip="10.1.0.1")
        wrong = _join(client, "JHK001", ip="10.1.0.2", session_password="not-the-password")
        missing = _join(client, "JHK001", ip="10.1.0.3", session_password=None)
    assert unknown.status_code == 401
    assert _same(unknown, wrong)
    assert _same(unknown, missing)


def test_join_unknown_code_still_runs_a_pbkdf2_verify(monkeypatch):
    """存在しない code でも PBKDF2 を回し、所要時間で区別できないこと。"""
    calls = []
    real = sessions_mod._verify_password

    def spy(plain, stored):
        calls.append(stored)
        return real(plain, stored)

    monkeypatch.setattr(sessions_mod, "_verify_password", spy)
    with TestClient(app, base_url="http://localhost") as client:
        resp = _join(client, "NOSUCH", ip="10.1.1.1")
    assert resp.status_code == 401
    assert calls == [sessions_mod._DUMMY_PASSWORD_HASH]
    # ダミーは本物と同じ形式で、PBKDF2 を実際に実行して不一致になる
    assert real("anything", sessions_mod._DUMMY_PASSWORD_HASH) is False


def _joined(client, code, ip):
    resp = _join(client, code, ip=ip)
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


def test_ice_config_and_heartbeat_return_one_generic_401():
    _make_session("JHG001")
    with TestClient(app, base_url="http://localhost") as client:
        data = _joined(client, "JHG001", "10.2.0.1")
        pid, tok = data["participant_id"], data["participant_token"]

        def ice(code, p, token, ip):
            return client.get(
                f"/api/sessions/{code}/devices/{p}/ice-config",
                headers={"Authorization": f"Participant {token}", **_ip(ip)},
            )

        def hb(code, p, token, ip):
            return client.post(
                f"/api/sessions/{code}/devices/{p}/heartbeat",
                json={"participant_token": token}, headers=_ip(ip),
            )

        for call in (ice, hb):
            unknown_session = call("NOSUCH", pid, tok, "10.2.1.1")
            unknown_participant = call("JHG001", 999999, tok, "10.2.1.2")
            bad_token = call("JHG001", pid, "x" * 43, "10.2.1.3")
            assert unknown_session.status_code == 401
            assert _same(unknown_session, unknown_participant)
            assert _same(unknown_session, bad_token)

        # 正規の端末は影響を受けない (heartbeat は 200)
        assert hb("JHG001", pid, tok, "10.2.2.1").status_code == 200


def _ip_limit():
    return sessions_mod._JOIN_IP_RATE_LIMIT


@pytest.mark.parametrize("route", ["ice-config", "heartbeat"])
def test_participant_routes_are_ip_rate_limited(route):
    _make_session("JHR001")
    with TestClient(app, base_url="http://localhost") as client:
        data = _joined(client, "JHR001", "10.3.0.1")
        pid = data["participant_id"]

        def hit(ip):
            if route == "ice-config":
                return client.get(
                    f"/api/sessions/JHR001/devices/{pid}/ice-config",
                    headers={"Authorization": "Participant bad", **_ip(ip)},
                )
            return client.post(
                f"/api/sessions/JHR001/devices/{pid}/heartbeat",
                json={"participant_token": "bad"}, headers=_ip(ip),
            )

        attacker = "10.3.9.9"
        codes = [hit(attacker).status_code for _ in range(_ip_limit() + 3)]
        assert codes[: _ip_limit()] == [401] * _ip_limit()
        assert set(codes[_ip_limit():]) == {429}
        # 別 IP は巻き込まれない
        assert hit("10.3.9.10").status_code == 401


# ── 6. ロックアウトは (code, IP) 単位 ────────────────────────────────────────

def test_lockout_is_keyed_by_code_and_ip():
    _make_session("JHL001")
    limit = sessions_mod._JOIN_RATE_LIMIT
    assert limit < sessions_mod._JOIN_IP_RATE_LIMIT, "前提: (code,IP) 上限 < IP 上限"
    with TestClient(app, base_url="http://localhost") as client:
        attacker = "10.4.0.66"
        for _ in range(limit):
            assert _join(client, "JHL001", ip=attacker, session_password="wrong").status_code == 401
        # 攻撃者はこの code についてロックされる
        assert _join(client, "JHL001", ip=attacker, session_password="wrong").status_code == 429
        assert _join(client, "JHL001", ip=attacker).status_code == 429
        # 別 IP の正規端末は参加できる
        ok = _join(client, "JHL001", ip="10.4.0.7")
        assert ok.status_code == 200, ok.text


def test_per_code_global_brake_still_exists():
    """全 IP 合算のブレーキは残るが、(code,IP) 上限よりずっと高い。"""
    assert sessions_mod._JOIN_CODE_RATE_LIMIT >= sessions_mod._JOIN_RATE_LIMIT * 10
    _make_session("JHB001")
    now = time.time()
    with sessions_mod._JOIN_RATE_LOCK:
        sessions_mod._JOIN_CODE_FAILURES["JHB001"] = [now] * sessions_mod._JOIN_CODE_RATE_LIMIT
    with TestClient(app, base_url="http://localhost") as client:
        assert _join(client, "JHB001", ip="10.5.0.1").status_code == 429


# ── 7. パスワード未設定セッション ───────────────────────────────────────────

def test_join_refused_when_session_has_no_password_hash():
    _make_session("JHN001", password=None)
    with TestClient(app, base_url="http://localhost") as client:
        for pw in (None, "", "anything"):
            resp = _join(client, "JHN001", ip="10.6.0.1", session_password=pw)
            assert resp.status_code == 403, resp.text
            assert "パスワード" in resp.json()["detail"]


def test_production_session_creation_always_sets_a_hash():
    """create_session のソースが必ず password_hash=hashed を渡すこと。"""
    import inspect
    src = inspect.getsource(sessions_mod.create_session)
    assert "password_hash=hashed" in src


# ── 8. 制限用 dict の肥大化防止 ─────────────────────────────────────────────

def test_limiter_state_is_bounded_and_empty_keys_are_removed(monkeypatch):
    monkeypatch.setattr(sessions_mod, "_JOIN_STATE_MAX_KEYS", 50)
    for i in range(500):
        sessions_mod._record_join_failure(f"C{i}", None)
    assert len(sessions_mod._JOIN_FAILURES) <= 50
    assert len(sessions_mod._JOIN_CODE_FAILURES) <= 50
    # 古いキーから捨てられ、最新は残る
    assert "C499" in sessions_mod._JOIN_CODE_FAILURES
    assert "C0" not in sessions_mod._JOIN_CODE_FAILURES

    # チェックだけではキーが作られず、窓を過ぎた空キーは消える
    before = len(sessions_mod._JOIN_CODE_FAILURES)
    sessions_mod._check_join_rate_limit("NEVER-SEEN", None)
    assert len(sessions_mod._JOIN_CODE_FAILURES) == before
    assert ("NEVER-SEEN", "") not in sessions_mod._JOIN_FAILURES

    old = time.time() - sessions_mod._JOIN_RATE_WINDOW - 5
    with sessions_mod._JOIN_RATE_LOCK:
        sessions_mod._JOIN_CODE_FAILURES.clear()
        sessions_mod._JOIN_CODE_FAILURES["STALE"] = [old]
        sessions_mod._JOIN_FAILURES[("STALE", "")] = [old]
    sessions_mod._check_join_rate_limit("STALE", None)
    assert "STALE" not in sessions_mod._JOIN_CODE_FAILURES
    assert ("STALE", "") not in sessions_mod._JOIN_FAILURES


def test_limiter_state_does_not_grow_on_unknown_code_floods():
    """HTTP 経由でも、code / IP を変え続けて dict を無制限に太らせられない。"""
    cap = sessions_mod._JOIN_STATE_MAX_KEYS
    with TestClient(app, base_url="http://localhost") as client:
        for i in range(30):
            _join(client, f"FLOOD{i}", ip=f"10.7.{i // 200}.{i % 200 + 1}")
    assert len(sessions_mod._JOIN_FAILURES) <= cap
    assert len(sessions_mod._JOIN_IP_FAILURES) <= cap
    assert len(sessions_mod._JOIN_CODE_FAILURES) <= cap
