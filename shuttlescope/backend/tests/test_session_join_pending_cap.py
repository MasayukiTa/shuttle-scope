"""W63 所見1: /sessions/{code}/join の承認待ち participant 氾濫(approval DoS)対策。

正しいセッションパスワードを握った相手が device_uid を変えながら join を連打すると、
pending の participant 行が無限に積もり、operator のデバイス一覧を埋めて承認運用を
妨害できる(CWE-770)。対策を 4 つ検証する:
  1. pending 上限 (_MAX_PENDING_PARTICIPANTS) を超える join は 429。
  2. 同じ device_uid の pending 行は 1 本に合流し、行が増えない。
  3. TTL (_PENDING_TTL) を過ぎた pending 行は次の join / 一覧取得で掃除され、枠が空く。
  4. 成功 join 自体の送信元 IP レート制限 (_JOIN_SUCCESS_IP_LIMIT/60s)。

併せて audit 要約が session_password / participant_token の値を
changed_fields にも body_hash の平文にも残さないことも確認する。
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.db.database import get_db
from backend.db.models import Player, Match, SharedSession, SessionParticipant
from backend.routers import sessions as sess_mod
from backend.utils import audit_targets as at


def _make_match(db) -> Match:
    pa = Player(name="A")
    pb = Player(name="B")
    db.add_all([pa, pb])
    db.flush()
    m = Match(
        tournament="T", tournament_level="IC", round="R1",
        date=date(2026, 4, 8), format="singles",
        player_a_id=pa.id, player_b_id=pb.id, result="win",
    )
    db.add(m)
    db.flush()
    return m


@pytest.fixture(autouse=True)
def _reset_join_state():
    """join のモジュール内レート制限 / pending ストアを毎テスト初期化する。"""
    for store in (
        sess_mod._JOIN_FAILURES, sess_mod._JOIN_CODE_FAILURES,
        sess_mod._JOIN_IP_FAILURES, sess_mod._JOIN_SUCCESS_IP_FAILURES,
    ):
        store.clear()
    yield
    for store in (
        sess_mod._JOIN_FAILURES, sess_mod._JOIN_CODE_FAILURES,
        sess_mod._JOIN_IP_FAILURES, sess_mod._JOIN_SUCCESS_IP_FAILURES,
    ):
        store.clear()


@pytest.fixture
def lan_session(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    client = TestClient(app, headers={"X-Role": "analyst"})
    match = _make_match(db_session)
    db_session.commit()
    resp = client.post("/api/sessions", json={"match_id": match.id})
    assert resp.status_code == 201, resp.text
    data = resp.json()["data"]
    yield client, data["session_code"], data["session_password"], db_session
    app.dependency_overrides.clear()


def _join(client, code, password, *, uid=None, name="dev", expect=200):
    body = {"role": "viewer", "device_name": name,
            "device_type": "iphone", "session_password": password}
    if uid is not None:
        body["device_uid"] = uid
    r = client.post(f"/api/sessions/{code}/join", json=body)
    assert r.status_code == expect, (expect, r.status_code, r.text)
    return r


def _pending_count(db, code):
    s = db.query(SharedSession).filter(SharedSession.session_code == code).first()
    return (
        db.query(SessionParticipant)
        .filter(SessionParticipant.session_id == s.id,
                SessionParticipant.approval_status == "pending")
        .count()
    )


# ───────────────────────── 1. pending 上限 ─────────────────────────
def test_pending_cap_returns_429(lan_session, monkeypatch):
    client, code, password, db = lan_session
    # 成功 IP レート制限はこのテストでは無効化し、純粋に pending 上限だけを見る。
    monkeypatch.setattr(sess_mod, "_JOIN_SUCCESS_IP_LIMIT", 10_000)
    cap = sess_mod._MAX_PENDING_PARTICIPANTS
    for i in range(cap):
        _join(client, code, password, uid=f"uid_{i}", name=f"d{i}")
    assert _pending_count(db, code) == cap
    # cap+1 本目は 429
    r = _join(client, code, password, uid=f"uid_{cap}", name="overflow", expect=429)
    assert _pending_count(db, code) == cap  # 行は増えていない


# ───────────────────── 2. 同一 device_uid は合流 ─────────────────────
def test_same_device_uid_pending_is_merged(lan_session, monkeypatch):
    client, code, password, db = lan_session
    monkeypatch.setattr(sess_mod, "_JOIN_SUCCESS_IP_LIMIT", 10_000)
    r1 = _join(client, code, password, uid="same-uid", name="first")
    pid1 = r1.json()["data"]["participant_id"]
    # 同じ uid で何度 join しても pending は 1 本のまま(token 無し再試行)
    for _ in range(5):
        r = _join(client, code, password, uid="same-uid", name="again")
        assert r.json()["data"]["participant_id"] == pid1
        assert r.json()["data"].get("reconnected") is True
    assert _pending_count(db, code) == 1


# ───────────────────── 3. TTL 掃除で枠が空く ─────────────────────
def test_stale_pending_is_pruned(lan_session, monkeypatch):
    client, code, password, db = lan_session
    monkeypatch.setattr(sess_mod, "_JOIN_SUCCESS_IP_LIMIT", 10_000)
    cap = sess_mod._MAX_PENDING_PARTICIPANTS
    for i in range(cap):
        _join(client, code, password, uid=f"uid_{i}", name=f"d{i}")
    assert _pending_count(db, code) == cap
    # 全 pending 行の生存時刻を TTL より過去に倒す
    s = db.query(SharedSession).filter(SharedSession.session_code == code).first()
    old = datetime.utcnow() - sess_mod._PENDING_TTL - timedelta(minutes=1)
    for p in db.query(SessionParticipant).filter(
        SessionParticipant.session_id == s.id).all():
        p.last_heartbeat = old
        p.authenticated_at = old
        p.joined_at = old
    db.commit()
    # 次の join で掃除され、受け付けられる(429 にならない)
    _join(client, code, password, uid="fresh", name="fresh", expect=200)
    # 古い行は消え、新しい 1 本だけが残る
    assert _pending_count(db, code) == 1


def test_list_devices_prunes_stale_pending(lan_session, monkeypatch):
    client, code, password, db = lan_session
    monkeypatch.setattr(sess_mod, "_JOIN_SUCCESS_IP_LIMIT", 10_000)
    _join(client, code, password, uid="u1", name="d1")
    _join(client, code, password, uid="u2", name="d2")
    s = db.query(SharedSession).filter(SharedSession.session_code == code).first()
    old = datetime.utcnow() - sess_mod._PENDING_TTL - timedelta(minutes=1)
    for p in db.query(SessionParticipant).filter(
        SessionParticipant.session_id == s.id).all():
        p.last_heartbeat = old; p.authenticated_at = old; p.joined_at = old
    db.commit()
    resp = client.get(f"/api/sessions/{code}/devices")
    assert resp.status_code == 200
    assert _pending_count(db, code) == 0


# ───────────────── 4. 成功 join の IP レート制限 ─────────────────
def test_successful_join_ip_rate_limit(lan_session):
    client, code, password, db = lan_session
    limit = sess_mod._JOIN_SUCCESS_IP_LIMIT
    # 上限ちょうどまでは成功(distinct uid で合流を避ける)
    for i in range(limit):
        _join(client, code, password, uid=f"rl_{i}", name=f"d{i}")
    # 次の 1 本は成功 IP レート制限で 429
    _join(client, code, password, uid=f"rl_{limit}", name="blocked", expect=429)


# ───────────────── 承認済み行は TTL で消えない ─────────────────
def test_approved_row_not_pruned_by_ttl(lan_session, monkeypatch):
    client, code, password, db = lan_session
    monkeypatch.setattr(sess_mod, "_JOIN_SUCCESS_IP_LIMIT", 10_000)
    r = _join(client, code, password, uid="appr", name="approved")
    pid = r.json()["data"]["participant_id"]
    # operator が承認
    ar = client.post(f"/api/sessions/{code}/devices/{pid}/approve")
    assert ar.status_code == 200, ar.text
    # 生存時刻を大過去に倒しても approved は掃除対象外
    s = db.query(SharedSession).filter(SharedSession.session_code == code).first()
    old = datetime.utcnow() - sess_mod._PENDING_TTL - timedelta(hours=1)
    p = db.get(SessionParticipant, pid)
    p.last_heartbeat = old; p.authenticated_at = old; p.joined_at = old
    db.commit()
    removed = sess_mod._prune_stale_pending(s.id, db)
    db.commit()
    assert removed == 0
    assert db.get(SessionParticipant, pid).approval_status == "approved"


# ───────────────── audit: 秘密値を残さない ─────────────────
class TestJoinBodySecretsRedacted:
    def test_session_password_and_token_not_in_summary(self):
        pw = "S3cretPass!"
        tok = "participant-token-abcdef0123456789"
        body = json.dumps({
            "role": "viewer", "device_name": "iPhone", "device_type": "iphone",
            "session_password": pw, "participant_token": tok,
        }).encode("utf-8")
        fields, count, body_hash = at.summarize_body(body)
        # 秘密キーは列挙ヒントも出さない
        assert "session_password" not in (fields or [])
        assert "participant_token" not in (fields or [])
        # 非秘密の列名は残る
        assert set(fields) == {"role", "device_name", "device_type"}
        assert count == 3
        # 値は changed_fields にも body_hash(hex)にも現れない
        joined = "".join(fields)
        assert pw not in joined and tok not in joined
        assert pw not in body_hash and tok not in body_hash
        assert len(body_hash) == 64

    def test_hash_is_invariant_to_secret_values(self):
        base = {"role": "viewer", "device_type": "iphone"}
        h1 = at.summarize_body(json.dumps(
            {**base, "session_password": "aaa", "participant_token": "xxx"}).encode())[2]
        h2 = at.summarize_body(json.dumps(
            {**base, "session_password": "bbb", "participant_token": "yyy"}).encode())[2]
        assert h1 == h2  # 低エントロピー値の総当たり oracle を塞ぐ (CWE-916)
        # 非秘密フィールドが変われば hash は変わる
        h3 = at.summarize_body(json.dumps(
            {"role": "coach", "device_type": "iphone",
             "session_password": "aaa", "participant_token": "xxx"}).encode())[2]
        assert h3 != h1


# ───────────────── audit 分類: session / participant ─────────────────
class TestSessionAuditClassification:
    @pytest.mark.parametrize("path,etype,eid", [
        ("/api/sessions", "session", None),
        ("/api/sessions/ABC", "session", "ABC"),
        ("/api/sessions/ABC/join", "session", "ABC"),
        ("/api/sessions/ABC/end", "session", "ABC"),
        ("/api/sessions/ABC/regenerate-password", "session", "ABC"),
        ("/api/sessions/ABC/devices", "participant", None),
        ("/api/sessions/ABC/devices/7/approve", "participant", "7"),
        ("/api/sessions/ABC/devices/7/reject", "participant", "7"),
        ("/api/sessions/ABC/devices/7/set-role", "participant", "7"),
    ])
    def test_classify(self, path, etype, eid):
        got = at.classify_path(path)
        assert got is not None, f"{path} should be audited"
        assert got[0] == etype
        assert got[1] == eid
