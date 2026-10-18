"""S-4: ラリー 0 本の動画の全体走査（案 A）の API。

CV は Rally / Stroke / GameSet を作らない。人の決定は別種別 rally_boundary_decisions
（追記のみ）に置き、rally_boundaries の再ビルドで消えない。採用 API は人が押したときだけ、
未入力（None / 試合 32 型の 0.0）の既存ラリーの video_timestamp_start/end を書く。

TestClient は middleware を全部載せた本物の backend.main.app を通す。重い解析
(video_import._run_pipeline) と path_jail は差し替える（認可・状態遷移だけを見る）。
"""
from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from backend.db import models as M
from backend.db.database import get_db
from backend.main import app
from backend.routers import video_import as vi
from backend.routers.auth import _hash_password
from backend.utils.jwt_utils import create_access_token

TEAM_A = 9711
TEAM_B = 9712
MARK = "SEGSCAN_SECRET_MARK"
NOISE_TABLES = {
    "request_logs", "security_events", "error_logs", "access_logs", "product_events",
    "analysis_cache", "revoked_tokens", "consumed_export_nonces",
}

SEGMENTS = [
    {"start_sec": 10.0, "end_sec": 20.0, "duration": 10.0, "signal_score": 0.667,
     "open_ended": False, "open_side": None, "coverage_ratio": 0.9, "sample_count": 120,
     "data_status": "unverified", "confidence_basis": "signals_fired/3",
     "signals": {"start": ["a"], "end": ["b"]}},
    {"start_sec": 30.0, "end_sec": 41.5, "duration": 11.5, "signal_score": None,
     "open_ended": False, "open_side": None, "coverage_ratio": 0.2, "sample_count": 3,
     "data_status": "data_insufficient", "confidence_basis": "signals_fired/3",
     "signals": {"start": [], "end": []}},
    {"start_sec": 50.0, "end_sec": None, "duration": None, "signal_score": 0.5,
     "open_ended": True, "open_side": "end_missing", "coverage_ratio": None, "sample_count": None,
     "data_status": "unverified", "confidence_basis": "signals_fired/3",
     "signals": {"start": ["a"], "end": []}},
]


def _boundaries(segments=SEGMENTS, status="ok"):
    return {"match_id": 0, "fps": 30.0, "sample_fps": 15.0, "time_axis": "sample_rate",
            "sample_count": 900, "boundary_count": 4, "boundaries": [],
            "segments": segments, "segments_status": status, "note": MARK}


@pytest.fixture()
def env(db_session, monkeypatch, tmp_path):
    db = db_session
    db.add_all([
        M.Team(id=TEAM_A, display_id="SEG-A", name="SEG Team A"),
        M.Team(id=TEAM_B, display_id="SEG-B", name="SEG Team B"),
    ])
    pa = M.Player(name="SEG PA", name_normalized="seg pa", team_id=TEAM_A)
    pb = M.Player(name="SEG PB", name_normalized="seg pb", team_id=TEAM_A)
    db.add_all([pa, pb])
    db.flush()
    video = tmp_path / "match.mp4"
    video.write_bytes(b"\x00" * 16)

    def _match(video_local_path):
        m = M.Match(tournament="SEG", tournament_level="domestic", round="QF",
                    date=date(2026, 10, 18), format="singles", result="unknown",
                    is_public_pool=False, player_a_id=pa.id, player_b_id=pb.id,
                    owner_team_id=TEAM_A, video_local_path=video_local_path)
        db.add(m)
        db.flush()
        return m

    m = _match(str(video))
    gs = M.GameSet(match_id=m.id, set_num=1, winner="player_a", score_a=21, score_b=10)
    db.add(gs)
    db.flush()
    rallies = []
    for n in (1, 2, 3):
        r = M.Rally(set_id=gs.id, rally_num=n, server="player_a", winner="player_a",
                    end_type="forced_error", rally_length=2,
                    video_timestamp_start=0.0, video_timestamp_end=None)
        db.add(r)
        db.flush()
        db.add(M.Stroke(rally_id=r.id, stroke_num=1, player="player_a", shot_type="clear"))
        rallies.append(r)
    # 別の試合（ラリーは他試合に属する）
    other = _match(str(video))
    ogs = M.GameSet(match_id=other.id, set_num=1, winner="player_a", score_a=21, score_b=10)
    db.add(ogs)
    db.flush()
    other_rally = M.Rally(set_id=ogs.id, rally_num=1, server="player_a", winner="player_a",
                          end_type="forced_error", rally_length=2)
    db.add(other_rally)
    db.add(M.MatchCVArtifact(match_id=m.id, artifact_type="cv_candidates", frame_count=1,
                             data=json.dumps({"rallies": {}, "rally_boundaries": _boundaries()})))
    users = {}
    for role, team in (("player", TEAM_A), ("demo", TEAM_A), ("llm", TEAM_A), ("coach", TEAM_A),
                       ("analyst", TEAM_A), ("admin", None), ("analystB", TEAM_B)):
        base = "analyst" if role == "analystB" else role
        u = M.User(username=f"seg_{role}", role=base, display_name=role,
                   hashed_credential=_hash_password("pw"),
                   player_id=pa.id if role == "player" else None,
                   team_id=team, team_name=None if team is None else ("SEG Team A" if team == TEAM_A else "SEG Team B"),
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
               "mid": m.id, "other_mid": other.id, "rids": [r.id for r in rallies],
               "other_rid": other_rally.id, "users": users, "calls": calls,
               "video": video, "tmp": tmp_path, "make_match": _match}
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


def _call(env, role, method, path, body=None):
    path = path.format(mid=env["mid"], rid=env["rids"][0], other_mid=env["other_mid"])
    kw = {} if body is None else {"json": body}
    return env["client"].request(method, path, headers=_hdr(env, role), **kw)


def _snapshot(db) -> dict:
    db.rollback()
    snap = {}
    for t in M.Base.metadata.sorted_tables:
        if t.name in NOISE_TABLES:
            continue
        rows = db.execute(text(f'SELECT * FROM "{t.name}"')).fetchall()
        snap[t.name] = sorted(repr(tuple(r)) for r in rows)
    return snap


def _changed(a: dict, b: dict) -> list[str]:
    return [k for k in a if a[k] != b.get(k)]


def _put_boundaries(env, data):
    env["db"].add(M.MatchCVArtifact(match_id=env["mid"], artifact_type="rally_boundaries",
                                    frame_count=1, data=json.dumps(data)))
    env["db"].commit()


def _decisions(env):
    env["db"].expire_all()
    rows = (env["db"].query(M.MatchCVArtifact)
            .filter(M.MatchCVArtifact.match_id == env["mid"],
                    M.MatchCVArtifact.artifact_type == "rally_boundary_decisions")
            .order_by(M.MatchCVArtifact.id).all())
    return [(r.id, r.data) for r in rows]


DEC = {"start_sec": 10.0, "end_sec": 20.0, "action": "reject"}
ROUTES = [
    ("POST", "/api/cv-candidates/scan/{mid}", None),
    ("GET", "/api/cv-candidates/{mid}/segments", None),
    ("POST", "/api/cv-candidates/{mid}/segments/decisions", DEC),
    ("POST", "/api/cv-candidates/{mid}/segments/adopt",
     {"start_sec": 10.0, "end_sec": 20.0, "rally_id": 1}),
]
IDS = [f"{m} {p.replace('/api/cv-candidates/', '')}" for m, p, _ in ROUTES]


# ─── 認可 ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("role", ["player", "demo", "llm"])
@pytest.mark.parametrize("method,path,body", ROUTES, ids=IDS)
def test_non_operator_roles_get_403_and_nothing_changes(env, role, method, path, body):
    _put_boundaries(env, _boundaries())
    before = _snapshot(env["db"])
    r = _call(env, role, method, path, body)
    assert r.status_code == 403, (role, method, path, r.status_code, r.text)
    assert MARK not in r.text and "segments" not in r.text and "start_sec" not in r.text
    assert _changed(before, _snapshot(env["db"])) == []
    assert env["calls"] == [] and vi._jobs == {}


@pytest.mark.parametrize("role", ["player", "demo", "llm"])
def test_status_route_and_candidate_read_are_closed_to_non_operators(env, role):
    """GET /cv-candidates/{id} に rally_boundaries / segments が入っている。player に出ない。"""
    r = _call(env, "analyst", "POST", "/api/cv-candidates/scan/{mid}")
    job_id = r.json()["data"]["job_id"]
    s = _call(env, role, "GET", f"/api/cv-candidates/scan-status/{job_id}")
    assert s.status_code == 403 and job_id not in s.text
    c = _call(env, role, "GET", "/api/cv-candidates/{mid}")
    assert c.status_code == 403
    assert MARK not in c.text and "rally_boundaries" not in c.text and "segments" not in c.text
    # 運用ロールには従来どおり返る（既存挙動を壊していない）
    ok = _call(env, "analyst", "GET", "/api/cv-candidates/{mid}")
    assert ok.status_code == 200 and "rally_boundaries" in ok.text


@pytest.mark.parametrize("method,path,body", ROUTES, ids=IDS)
def test_anonymous_is_rejected(env, method, path, body):
    before = _snapshot(env["db"])
    r = _call(env, "anon", method, path, body)
    assert r.status_code in (401, 403), (r.status_code, r.text)
    assert _changed(before, _snapshot(env["db"])) == []
    assert env["calls"] == []


@pytest.mark.parametrize("method,path,body", ROUTES, ids=IDS)
def test_other_teams_analyst_cannot_reach_a_match_of_team_a(env, method, path, body):
    _put_boundaries(env, _boundaries())
    before = _snapshot(env["db"])
    r = _call(env, "analystB", method, path, body)
    assert r.status_code in (403, 404), (method, path, r.status_code, r.text)
    assert MARK not in r.text
    assert _changed(before, _snapshot(env["db"])) == []
    assert env["calls"] == [] and vi._jobs == {}


def test_other_teams_analyst_cannot_read_scan_status(env):
    job_id = _call(env, "analyst", "POST", "/api/cv-candidates/scan/{mid}").json()["data"]["job_id"]
    r = _call(env, "analystB", "GET", f"/api/cv-candidates/scan-status/{job_id}")
    assert r.status_code in (403, 404) and job_id not in r.text


@pytest.mark.parametrize("role", ["coach", "analyst", "admin"])
def test_operators_pass_every_new_route(env, role):
    _put_boundaries(env, _boundaries())
    assert _call(env, role, "GET", "/api/cv-candidates/{mid}/segments").status_code == 200
    assert _call(env, role, "POST", "/api/cv-candidates/{mid}/segments/decisions", DEC).status_code == 200
    r = _call(env, role, "POST", "/api/cv-candidates/scan/{mid}")
    assert r.status_code == 200, r.text
    jid = r.json()["data"]["job_id"]
    assert _call(env, role, "GET", f"/api/cv-candidates/scan-status/{jid}").status_code == 200


# ─── scan ───────────────────────────────────────────────────────────────────

def test_scan_registers_a_video_import_job_and_creates_no_rows(env):
    before = _snapshot(env["db"])
    r = _call(env, "analyst", "POST", "/api/cv-candidates/scan/{mid}")
    assert r.status_code == 200, r.text
    jid = r.json()["data"]["job_id"]
    assert env["calls"] == [jid]                      # video_import の既存パイプラインを呼ぶ
    job = vi._jobs[jid]
    assert job["match_id"] == env["mid"] and job["video_path"] == str(env["video"].resolve())
    assert _changed(before, _snapshot(env["db"])) == []   # Rally/Stroke/GameSet も成果物も増えない
    st = _call(env, "analyst", "GET", f"/api/cv-candidates/scan-status/{jid}").json()["data"]
    assert st["phase"] == "queued" and st["match_id"] == env["mid"]
    assert str(env["video"]) not in json.dumps(st) and "video_path" not in st


def test_second_concurrent_scan_of_same_match_is_409(env):
    first = _call(env, "analyst", "POST", "/api/cv-candidates/scan/{mid}")
    assert first.status_code == 200
    second = _call(env, "coach", "POST", "/api/cv-candidates/scan/{mid}")
    assert second.status_code == 409, second.text
    assert first.json()["data"]["job_id"] in second.json()["detail"]
    assert len(env["calls"]) == 1
    # 別の試合は止めない
    other = _call(env, "analyst", "POST", "/api/cv-candidates/scan/{other_mid}")
    assert other.status_code == 200
    # 終わったジョブは次の走査を止めない
    vi._jobs[first.json()["data"]["job_id"]]["phase"] = vi.Phase.DONE
    again = _call(env, "analyst", "POST", "/api/cv-candidates/scan/{mid}")
    assert again.status_code == 200


def test_a_running_video_import_job_for_the_match_also_blocks_a_scan(env):
    job = vi._new_job("x.mp4", env["mid"])
    job["job_id"] = "legacy01"
    job["phase"] = vi.Phase.YOLO
    vi._jobs["legacy01"] = job
    r = _call(env, "analyst", "POST", "/api/cv-candidates/scan/{mid}")
    assert r.status_code == 409 and env["calls"] == []


def _set_video(env, value, **extra):
    m = env["db"].get(M.Match, env["mid"])
    m.video_local_path = value
    for k, v in extra.items():
        setattr(m, k, v)
    env["db"].commit()


@pytest.mark.parametrize("value,extra,needle", [
    (None, {}, "設定されていません"),
    ("", {}, "設定されていません"),
    (None, {"video_url": "https://example.invalid/v.mp4"}, "URL"),
    ("https://example.invalid/v.mp4", {}, "URL"),
    ("rtsp://example.invalid/stream.mp4", {}, "URL"),
    ("server://not-a-uuid.mp4", {}, "server://"),
])
def test_scan_rejects_sources_video_import_cannot_read(env, value, extra, needle):
    _set_video(env, value, **extra)
    r = _call(env, "analyst", "POST", "/api/cv-candidates/scan/{mid}")
    assert r.status_code == 400, (value, r.status_code, r.text)
    assert needle in r.json()["detail"]
    assert env["calls"] == [] and vi._jobs == {}


def test_scan_rejects_server_ref_outside_the_readable_roots(env, monkeypatch):
    from backend.utils import path_jail
    monkeypatch.setattr(path_jail, "is_allowed_video_path", lambda p: False)
    _set_video(env, "server://0b1f3a52-6a5e-4a3f-9f43-2b1c7d9e8a10.mp4")
    r = _call(env, "analyst", "POST", "/api/cv-candidates/scan/{mid}")
    assert r.status_code == 400 and "server://" in r.json()["detail"]
    assert env["calls"] == []


def test_scan_rejects_local_path_outside_jail_missing_file_and_non_video(env, monkeypatch):
    from backend.utils import path_jail
    monkeypatch.setattr(path_jail, "is_allowed_video_path", lambda p: False)
    assert _call(env, "analyst", "POST", "/api/cv-candidates/scan/{mid}").status_code == 403
    monkeypatch.setattr(path_jail, "is_allowed_video_path", lambda p: True)
    _set_video(env, str(env["tmp"] / "missing.mp4"))
    assert _call(env, "analyst", "POST", "/api/cv-candidates/scan/{mid}").status_code == 400
    txt = env["tmp"] / "notes.txt"
    txt.write_text("x")
    _set_video(env, str(txt))
    assert _call(env, "analyst", "POST", "/api/cv-candidates/scan/{mid}").status_code == 400
    assert env["calls"] == [] and vi._jobs == {}


def test_scan_accepts_localfile_scheme(env):
    _set_video(env, "localfile:///" + str(env["video"]).replace("\\", "/"))
    assert _call(env, "analyst", "POST", "/api/cv-candidates/scan/{mid}").status_code == 200


def test_scan_status_unknown_or_foreign_kind_job_is_404(env):
    assert _call(env, "analyst", "GET", "/api/cv-candidates/scan-status/nojob").status_code == 404
    job = vi._new_job("x.mp4", env["mid"])
    job["job_id"] = "legacy02"
    vi._jobs["legacy02"] = job      # video_import/path のジョブ（kind なし）は露出しない
    assert _call(env, "analyst", "GET", "/api/cv-candidates/scan-status/legacy02").status_code == 404


# ─── segments GET ───────────────────────────────────────────────────────────

def test_segments_without_artifact_say_insufficient_data(env):
    r = _call(env, "analyst", "GET", "/api/cv-candidates/{mid}/segments")
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "insufficient_data" and d["segments"] == [] and d["reason"]


def test_segments_carry_the_artifact_semantics(env):
    _put_boundaries(env, _boundaries())
    d = _call(env, "coach", "GET", "/api/cv-candidates/{mid}/segments").json()["data"]
    assert d["status"] == "ok" and d["sample_fps"] == 15.0 and d["time_axis"] == "sample_rate"
    segs = d["segments"]
    assert [s["start_sec"] for s in segs] == [10.0, 30.0, 50.0]
    assert segs[0]["signal_score"] == 0.667 and segs[0]["data_status"] == "unverified"
    assert segs[1]["data_status"] == "data_insufficient" and segs[1]["signal_score"] is None
    assert segs[2]["open_ended"] is True and segs[2]["end_sec"] is None
    assert all(s["latest_decision"] is None for s in segs)


def test_segments_data_insufficient_and_legacy_artifacts_are_explicit(env):
    _put_boundaries(env, _boundaries(segments=[], status="data_insufficient"))
    d = _call(env, "analyst", "GET", "/api/cv-candidates/{mid}/segments").json()["data"]
    assert d["status"] == "insufficient_data" and d["segments"] == [] and d["reason"]
    env["db"].query(M.MatchCVArtifact).filter_by(artifact_type="rally_boundaries").delete()
    _put_boundaries(env, {"boundaries": [], "boundary_count": 0})     # segments キー無しの旧形式
    d = _call(env, "analyst", "GET", "/api/cv-candidates/{mid}/segments").json()["data"]
    assert d["status"] == "insufficient_data" and "旧形式" in d["reason"]


def test_segments_no_segments_status_is_not_called_insufficient(env):
    _put_boundaries(env, _boundaries(segments=[], status="no_segments"))
    d = _call(env, "analyst", "GET", "/api/cv-candidates/{mid}/segments").json()["data"]
    assert d["status"] == "no_segments" and d["segments"] == []


# ─── decisions ──────────────────────────────────────────────────────────────

def test_decisions_are_appended_not_updated_and_touch_nothing_else(env):
    _put_boundaries(env, _boundaries())
    before = _snapshot(env["db"])
    uid = env["users"]["analyst"].id
    r1 = _call(env, "analyst", "POST", "/api/cv-candidates/{mid}/segments/decisions", DEC)
    r2 = _call(env, "coach", "POST", "/api/cv-candidates/{mid}/segments/decisions",
               {"start_sec": 10.0, "end_sec": 20.0, "action": "accept"})
    r3 = _call(env, "analyst", "POST", "/api/cv-candidates/{mid}/segments/decisions",
               {"start_sec": 30.0, "end_sec": 41.5, "action": "assign", "rally_id": env["rids"][1]})
    assert (r1.status_code, r2.status_code, r3.status_code) == (200, 200, 200), (r1.text, r2.text, r3.text)
    d1 = r1.json()["data"]
    assert d1["decided_by_user_id"] == uid and d1["decided_at"] and d1["action"] == "reject"
    rows = _decisions(env)
    assert len(rows) == 3 and json.loads(rows[0][1])["action"] == "reject"   # 1 行目は上書きされていない
    after = _snapshot(env["db"])
    assert _changed(before, after) == ["match_cv_artifacts"]
    # 既存の成果物行は 1 つも変わっていない（追加のみ）
    assert set(before["match_cv_artifacts"]) <= set(after["match_cv_artifacts"])
    seg = _call(env, "analyst", "GET", "/api/cv-candidates/{mid}/segments").json()["data"]
    assert seg["segments"][0]["latest_decision"]["action"] == "accept"
    assert seg["segments"][1]["latest_decision"]["rally_id"] == env["rids"][1]
    assert len(seg["decisions"]) == 3


@pytest.mark.parametrize("body", [
    {"start_sec": 10.0, "end_sec": 20.0, "action": "delete"},
    {"start_sec": 20.0, "end_sec": 10.0, "action": "reject"},
    {"action": "reject"},
    {"start_sec": -1.0, "end_sec": 5.0, "action": "reject"},
    {"start_sec": 1.0, "end_sec": 5.0, "action": "assign"},
    {"start_sec": 1.0, "end_sec": 5.0, "action": "reject", "rally_id": 1},
    {"start_sec": 1.0, "end_sec": 5.0, "action": "reject", "decided_by_user_id": 1},
    {"start_sec": 1.0, "end_sec": 5.0, "action": "reject", "adopted": True},
])
def test_decision_body_validation(env, body):
    before = _snapshot(env["db"])
    r = _call(env, "analyst", "POST", "/api/cv-candidates/{mid}/segments/decisions", body)
    assert r.status_code == 422, (body, r.status_code, r.text)
    assert _changed(before, _snapshot(env["db"])) == []


def test_assign_to_a_rally_of_another_match_is_404(env):
    before = _snapshot(env["db"])
    r = _call(env, "analyst", "POST", "/api/cv-candidates/{mid}/segments/decisions",
              {"start_sec": 1.0, "end_sec": 5.0, "action": "assign", "rally_id": env["other_rid"]})
    assert r.status_code == 404
    assert _changed(before, _snapshot(env["db"])) == []


def test_decisions_survive_a_rebuild_of_rally_boundaries(env):
    """実際の POST /build（rally_boundaries を上書き保存する経路）の前後で決定が変わらない。"""
    ts = [round(i / 15.0, 3) for i in range(0, 15 * 40)]
    frames = [{"timestamp_sec": t, "x": 0.5, "y": 0.5, "confidence": 0.9 if (i // 30) % 2 == 0 else 0.0}
              for i, t in enumerate(ts)]
    env["db"].add(M.MatchCVArtifact(match_id=env["mid"], artifact_type="tracknet_shuttle_track",
                                    frame_count=len(frames), data=json.dumps(frames)))
    env["db"].commit()
    assert _call(env, "analyst", "POST", "/api/cv-candidates/{mid}/segments/decisions", DEC).status_code == 200
    assert _call(env, "analyst", "POST", "/api/cv-candidates/{mid}/segments/decisions",
                 {"start_sec": 30.0, "end_sec": 41.5, "action": "accept"}).status_code == 200
    kept = _decisions(env)
    assert len(kept) == 2

    def _boundary_rows():
        env["db"].expire_all()
        return [(r.id, r.data) for r in env["db"].query(M.MatchCVArtifact).filter_by(
            match_id=env["mid"], artifact_type="rally_boundaries").all()]

    b1 = _call(env, "analyst", "POST", "/api/cv-candidates/build/{mid}")
    assert b1.status_code == 200, b1.text
    first = _boundary_rows()
    assert first and json.loads(first[0][1])["sample_count"] == len(frames)   # 本当に再ビルドされた
    # 入力を変えてもう一度（rally_boundaries の中身が変わる）
    env["db"].query(M.MatchCVArtifact).filter_by(artifact_type="tracknet_shuttle_track").update(
        {"data": json.dumps(frames[: len(frames) // 2])})
    env["db"].commit()
    assert _call(env, "analyst", "POST", "/api/cv-candidates/build/{mid}").status_code == 200
    second = _boundary_rows()
    assert second[0][1] != first[0][1]                                         # 上書きは起きた
    assert _decisions(env) == kept                                              # 決定は 1 バイトも変わらない
    seg = _call(env, "analyst", "GET", "/api/cv-candidates/{mid}/segments").json()["data"]
    assert [d["action"] for d in seg["decisions"]] == ["reject", "accept"]


# ─── adopt ──────────────────────────────────────────────────────────────────

def _adopt(env, role="analyst", rally_id=None, start=10.0, end=20.0):
    return _call(env, role, "POST", "/api/cv-candidates/{mid}/segments/adopt",
                 {"start_sec": start, "end_sec": end,
                  "rally_id": env["rids"][0] if rally_id is None else rally_id})


def _rally_rows(env):
    env["db"].rollback()
    return {r["id"]: dict(r) for r in env["db"].execute(text("SELECT * FROM rallies")).mappings().all()}


SYNC_COLS = {"updated_at", "revision", "content_hash"}


def test_adopt_on_match_32_pattern_changes_only_the_two_timestamp_columns(env):
    """全ラリーが 0.0 の試合: 対象ラリーの start/end だけが変わり、他は差分ゼロ。"""
    _put_boundaries(env, _boundaries())
    snap_before = _snapshot(env["db"])
    rows_before = _rally_rows(env)
    r = _adopt(env)
    assert r.status_code == 200, r.text
    rid = env["rids"][0]
    assert r.json()["data"]["rally"]["video_timestamp_start"] == 10.0
    snap_after = _snapshot(env["db"])
    # 変わる表は rallies（対象 1 行）と match_cv_artifacts（決定 1 行の追加）だけ。strokes/sets/matches は同一
    assert sorted(_changed(snap_before, snap_after)) == ["match_cv_artifacts", "rallies"]
    for t in ("strokes", "sets", "matches", "players", "teams", "users"):
        assert snap_before.get(t) == snap_after.get(t), t
    rows_after = _rally_rows(env)
    assert set(rows_after) == set(rows_before)                       # Rally 行は増えも減りもしない
    for other in set(rows_before) - {rid}:
        assert rows_after[other] == rows_before[other], other         # updated_at を含め他ラリーは同一
    diff_cols = {c for c in rows_before[rid] if rows_before[rid][c] != rows_after[rid][c]}
    assert diff_cols - SYNC_COLS == {"video_timestamp_start", "video_timestamp_end"}, diff_cols
    assert rows_after[rid]["video_timestamp_end"] == 20.0
    assert "updated_at" in diff_cols                                  # PUT /rallies と同じ sync メタ更新
    # 追加された成果物行は決定 1 件だけ（既存の行は不変）
    assert set(snap_before["match_cv_artifacts"]) < set(snap_after["match_cv_artifacts"])
    assert len(snap_after["match_cv_artifacts"]) == len(snap_before["match_cv_artifacts"]) + 1
    dec = [json.loads(d) for _, d in _decisions(env)]
    assert dec[0]["adopted"] is True and dec[0]["rally_id"] == rid and dec[0]["decided_by_user_id"]


def test_adopt_writes_sync_metadata_like_put_rallies(env):
    _put_boundaries(env, _boundaries())
    before = _rally_rows(env)[env["rids"][0]]
    assert _adopt(env).status_code == 200
    after = _rally_rows(env)[env["rids"][0]]
    assert after["revision"] == (before["revision"] or 0) + 1
    assert after["content_hash"] and after["content_hash"] != before["content_hash"]
    assert after["updated_at"] != before["updated_at"]


def test_adopt_sequentially_assigns_segments_in_a_match_32_pattern_match(env):
    _put_boundaries(env, _boundaries())
    assert _adopt(env, rally_id=env["rids"][0], start=10.0, end=20.0).status_code == 200
    assert _adopt(env, rally_id=env["rids"][1], start=30.0, end=41.5).status_code == 200
    rows = _rally_rows(env)
    assert [rows[i]["video_timestamp_start"] for i in env["rids"]] == [10.0, 30.0, 0.0]


def test_adopt_into_a_rally_with_no_timestamp_is_allowed(env):
    _put_boundaries(env, _boundaries())
    db = env["db"]
    db.get(M.Rally, env["rids"][0]).video_timestamp_start = None
    db.get(M.Rally, env["rids"][1]).video_timestamp_start = 77.0     # 他に人の値があっても、None の行は書ける
    db.commit()
    assert _adopt(env).status_code == 200
    assert _rally_rows(env)[env["rids"][0]]["video_timestamp_start"] == 10.0


@pytest.mark.parametrize("target_start,target_end", [(7.5, None), (7.5, 9.0), (0.0, 9.0), (None, 9.0)])
def test_adopt_refuses_to_overwrite_human_timestamps(env, target_start, target_end):
    _put_boundaries(env, _boundaries())
    db = env["db"]
    r0 = db.get(M.Rally, env["rids"][0])
    r0.video_timestamp_start, r0.video_timestamp_end = target_start, target_end
    db.commit()
    before = _snapshot(db)
    r = _adopt(env)
    assert r.status_code == 409, (target_start, target_end, r.status_code, r.text)
    assert "上書きしません" in r.json()["detail"]
    assert _changed(before, _snapshot(db)) == []                       # 1 バイトも変わらない（決定行も無い）


def test_adopt_refuses_zero_when_another_rally_has_a_human_value(env):
    """0.0 を「未入力」とみなせるのは全ラリーが 0.0/None のときだけ。"""
    _put_boundaries(env, _boundaries())
    db = env["db"]
    db.get(M.Rally, env["rids"][2]).video_timestamp_start = 123.4     # 人が入れた値
    db.commit()
    before = _snapshot(db)
    r = _adopt(env, rally_id=env["rids"][0])
    assert r.status_code == 409 and "123.4" in r.json()["detail"]
    assert _changed(before, _snapshot(db)) == []


def test_adopt_only_accepts_a_real_candidate_segment_and_a_rally_of_the_match(env):
    _put_boundaries(env, _boundaries())
    before = _snapshot(env["db"])
    assert _adopt(env, start=11.0, end=20.0).status_code == 404            # 候補にない区間
    assert _adopt(env, start=50.0, end=60.0).status_code == 404            # open_ended の区間は採用できない
    assert _adopt(env, rally_id=env["other_rid"]).status_code == 404       # 他試合のラリー
    assert _adopt(env, rally_id=999999).status_code == 404
    assert _changed(before, _snapshot(env["db"])) == []
    # 候補成果物が無ければ採用できない
    env["db"].query(M.MatchCVArtifact).filter_by(artifact_type="rally_boundaries").delete()
    env["db"].commit()
    assert _adopt(env).status_code == 404


def test_adopt_validation_and_unknown_fields(env):
    _put_boundaries(env, _boundaries())
    for body in ({"start_sec": 20.0, "end_sec": 10.0, "rally_id": 1},
                 {"start_sec": 10.0, "end_sec": 20.0},
                 {"start_sec": 10.0, "end_sec": 20.0, "rally_id": 1, "winner": "player_b"}):
        r = _call(env, "analyst", "POST", "/api/cv-candidates/{mid}/segments/adopt", body)
        assert r.status_code == 422, (body, r.status_code)


def test_adopt_never_creates_rally_set_or_stroke_rows(env):
    _put_boundaries(env, _boundaries())
    counts = lambda: [env["db"].query(m).count() for m in (M.Rally, M.GameSet, M.Stroke)]  # noqa: E731
    before = counts()
    for k, (s, e) in enumerate(((10.0, 20.0), (30.0, 41.5))):
        assert _adopt(env, rally_id=env["rids"][k], start=s, end=e).status_code == 200
    assert _adopt(env, rally_id=env["rids"][0], start=30.0, end=41.5).status_code == 409
    assert counts() == before
