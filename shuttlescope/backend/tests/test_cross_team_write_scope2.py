"""他チーム / 低権限ロールからの非 GET 書き込みルート総当たり (test_cross_team_write_scope の続き)。

本物の backend.main:app を TestClient + 一時 SQLite で叩く (peer は remote 203.0.113.9。
loopback 専用ルートだけ 127.0.0.1)。ルートは app のルートツリーから列挙し、SPECS に載っていない
非 GET ルートがあれば test_every_remaining_write_route_is_listed が落ちる
(新ルート追加時に判定漏れを出さない)。

登場人物は test_cross_team_write_scope と同じ (team A = 試合1/選手1,2,3(外部)、team B = 試合2/選手4)。
追加: demo(31) / llm(32) ロール、team A の未紐付け選手 6、A の condition / recording / LLM 会話 /
チャットセッション / 注文 / sync 競合 / 録画 job。
  - 外部プロセス起動 / 外部通信は fixture で全面ブロックする (穴があって handler に届いても実行されない)。
  - 各リクエストの前に DB を seed し直し、前後で (監査ログ類を除く) 全テーブルと app_settings を比較する。
  - 「deny」= 401/403/404 で、かつ DB が 1 行も変わらない。「allow」= 401/403 にならない (陽性対照)。
"""
from __future__ import annotations

import json
import os
import re
import secrets
import socket
import subprocess
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from starlette.routing import Mount

from backend.db import models as M
from backend.db.database import get_db
from backend.main import app
from backend.tests.test_cross_team_write_scope import TA, U, _seed, tok
from backend.utils.jwt_utils import create_access_token

U2 = dict(U, demo=31, llm=32)
ACTORS = ["anon", "cA", "aA", "pA1", "pA2", "cB", "aB", "pB1", "demo", "llm", "admin"]
ORDER_A = "00000000-0000-4000-8000-00000000000a"
JOB_A = "ab" * 16
# 監査ログ / 計測 / 失効台帳など、拒否されたリクエストでも増えて良いテーブル
NOISE_TABLES = {
    "request_logs", "security_events", "error_logs", "access_logs", "product_events",
    "analysis_cache", "revoked_tokens", "consumed_export_nonces",
}
_STATE = {"sync_dir": ""}


def _hdr(kind: str) -> dict:
    if kind == "anon":
        return {}
    if kind in ("demo", "llm"):
        return {"Authorization": "Bearer " + create_access_token(
            user_id=U2[kind], role=kind, team_id=None, team_name=None)}
    return tok(kind)


def _seed2(db) -> None:
    _seed(db)
    for k in ("demo", "llm"):
        db.add(M.User(id=U2[k], username=f"u_{k}", role=k, consent_required=False))
    db.add(M.Player(id=6, name="A_UNLINKED", name_normalized="aunlinked", team_id=TA))
    db.flush()
    db.add(M.Condition(id=1, player_id=1, measured_at=date(2026, 9, 1), condition_type="weekly", weight_kg=60.0))
    db.add(M.Condition(id=2, player_id=4, measured_at=date(2026, 9, 1), condition_type="weekly", weight_kg=60.0))
    db.add(M.Recording(id=1, match_id=1, branch_no=1, kind="upload", status="ready", label="orig"))
    db.add(M.LlmConversation(id=1, user_id=U["cA"], title="orig"))
    db.add(M.ChatSession(id=1, user_id=U["cA"], role_at_creation="coach", lang="ja"))
    db.add(M.BillingProduct(id=1, code="p1", name="Prod", price_jpy=100))
    db.flush()
    db.add(M.BillingOrder(id=1, public_id=ORDER_A, user_id=U["cA"], product_id=1, amount_jpy=100, status="pending"))
    db.add(M.SyncConflict(id=1, record_table="matches", record_uuid="u-1", reason="t"))
    db.add(M.ServerVideoArtifact(id=1, match_id=1, file_path="x.mp4", sender_user_id=U["cA"]))
    db.commit()
    # app_settings は ORM 外のテーブル (settings ルータが遅延作成する)
    db.execute(text("CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)"))
    db.execute(text("DELETE FROM app_settings"))
    db.execute(text("INSERT INTO app_settings(key, value) VALUES('sync_folder_path', :v)"),
               {"v": json.dumps(_STATE["sync_dir"])})
    db.commit()


# ─── fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def client(db_session, monkeypatch, tmp_path):
    _STATE["sync_dir"] = str(tmp_path / "sync")
    _seed2(db_session)
    app.dependency_overrides[get_db] = lambda: db_session

    def _blocked(*a, **k):
        raise OSError("blocked by cross-team audit test")

    monkeypatch.setattr(subprocess, "Popen", _blocked)
    monkeypatch.setattr(subprocess, "run", _blocked)
    monkeypatch.setattr(subprocess, "check_output", _blocked)
    monkeypatch.setattr(os, "system", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    monkeypatch.setattr(socket, "getaddrinfo", _blocked)
    from backend.services import youtube_live_recorder as ylr
    monkeypatch.setitem(ylr._jobs, JOB_A, ylr.RecordJob(
        job_id=JOB_A, url="https://example.invalid/x", out_path=Path(tmp_path) / "j.webm", method="drm",
        status="recording", match_id=1, owner_user_id=U["cA"], owner_team_id=TA))
    # video_import: 実解析 (cv2) とパス jail は本テストの対象外。認可だけを見る
    import backend.routers.video_import as vi
    monkeypatch.setattr(vi, "_run_pipeline", lambda job_id: None)
    from backend.utils import path_jail
    monkeypatch.setattr(path_jail, "is_allowed_video_path", lambda p: True)
    vid = tmp_path / "v.mp4"
    vid.write_bytes(b"\x00" * 16)
    app.state._audit_video = str(vid)
    c = TestClient(app, raise_server_exceptions=False, client=("203.0.113.9", 50000))
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


def _apply_opts(monkeypatch, spec) -> None:
    from backend.config import settings
    o = spec["opts"]
    if o.get("billing"):
        monkeypatch.setattr(settings, "ss_billing_enabled", 1, raising=False)
        monkeypatch.setenv("SS_BILLING_WEBHOOKS_ENABLED", "1")
    if o.get("worker"):
        # 実在しない使い捨て値。ユーザ JWT はこの token を持たない
        monkeypatch.setattr(settings, "ss_worker_auth_token", secrets.token_hex(24), raising=False)


def _snapshot(db) -> dict:
    db.rollback()
    snap = {}
    for t in M.Base.metadata.sorted_tables:
        if t.name in NOISE_TABLES:
            continue
        rows = db.execute(text(f'SELECT * FROM "{t.name}"')).fetchall()
        snap[t.name] = sorted(repr(tuple(r)) for r in rows)
    snap["app_settings"] = sorted(repr(tuple(r)) for r in db.execute(text("SELECT * FROM app_settings")).fetchall())
    return snap


def _diff(a: dict, b: dict) -> list[str]:
    return [k for k in a if a[k] != b.get(k)]


# ─── 仕様表 ─────────────────────────────────────────────────────────────────
# deny   : 必ず 401/403/404 になり、DB が変わらない
# allow  : 401/403 にならない (陽性対照。副作用の無いルートだけ)
# observe: 観測のみ (判定は audit_post_routes.md)

def _all_but(*ok: str) -> list[str]:
    return [a for a in ACTORS if a not in ok]


ADMIN_ONLY = _all_but("admin")
NON_TEAM = ["anon", "demo", "llm"]
FOREIGN = ["cB", "aB", "pB1"]
STROKE_BODY = dict(stroke_num=1, player="player_b", shot_type="clear")
RALLY_BODY = dict(rally_num=2, server="player_a", winner="player_a", end_type="ace", rally_length=1,
                  score_a_after=1, score_b_after=0)
NEW_MATCH = dict(tournament="Probe", tournament_level="国内", round="QF", date="2026-09-30",
                 format="singles", player_a_id=1, player_b_id=3, result="win")
SIX = [dict(x=0.1, y=0.1), dict(x=0.9, y=0.1), dict(x=0.9, y=0.9), dict(x=0.1, y=0.9),
       dict(x=0.4, y=0.5), dict(x=0.6, y=0.5)]
PKG = {"file": ("p.sspkg", b"{}", "application/octet-stream")}
NEW_USER_A = dict(role="coach", display_name="d", username="probe_user", password="Aa1!probe-pass-99",
                  team_id=1, team_name="ScopeTeamA")
NEW_USER_B = dict(NEW_USER_A, team_id=2, team_name="ScopeTeamB")


def S(sid, method, path, deny, kw=None, allow=(), observe=(), **opts):
    return dict(id=sid, method=method, path=path, deny=list(deny), kw=kw or {}, allow=list(allow),
                observe=list(observe), opts=opts)


WRITE_DENY = NON_TEAM + FOREIGN + ["pA2"]    # A の試合・選手・セット等を書き換えさせない集合
NO_PLAYER_ETC = NON_TEAM + ["pA1", "pA2", "pB1"]
ANALYST_GLOBAL = NON_TEAM + ["pA1", "pA2", "pB1", "cA", "cB"]

SPECS = [
    # --- players ---
    S("players.create", "POST", "/api/players", NON_TEAM + ["pA1", "pA2", "pB1", "cA", "cB"], dict(json=dict(name="Probe1", team="ScopeTeamA")), allow=["aA"]),
    S("players.create_into_foreign_team", "POST", "/api/players", NON_TEAM + ["pA1", "pA2", "pB1", "cA", "cB", "aB"],
      dict(json=dict(name="Probe1", team="ScopeTeamA"))),
    S("players.update_foreign", "PUT", "/api/players/1", WRITE_DENY, dict(json=dict(notes="PWN")), allow=["cA", "aA", "admin"], observe=["pA1"]),
    S("players.update_external", "PUT", "/api/players/3", NON_TEAM + FOREIGN + ["pA2"], dict(json=dict(notes="PWN"))),
    S("players.delete_foreign", "DELETE", "/api/players/1", WRITE_DENY + ["pA1"]),
    S("players.delete_external", "DELETE", "/api/players/3", NON_TEAM + FOREIGN + ["pA1", "pA2"]),
    # --- matches ---
    S("matches.create", "POST", "/api/matches", NON_TEAM + ["pA1", "pA2", "pB1"], dict(json=NEW_MATCH), allow=["cA", "aA"]),
    S("matches.create_without_own_player", "POST", "/api/matches", ["cB", "aB"], dict(json=NEW_MATCH)),
    S("matches.update", "PUT", "/api/matches/1", WRITE_DENY, dict(json=dict(notes="PWN")), allow=["cA", "aA", "admin"], observe=["pA1"]),
    S("matches.delete", "DELETE", "/api/matches/1", WRITE_DENY + ["pA1"]),
    S("matches.download", "POST", "/api/matches/1/download", WRITE_DENY, dict(json={}), observe=["pA1"]),
    S("matches.regen_variants", "POST", "/api/matches/1/regenerate_variants", WRITE_DENY, observe=["pA1"]),
    S("matches.quick_start", "POST", "/api/matches/quick-start", NON_TEAM + ["pA1", "pA2", "pB1"],
      dict(json=dict(player_a_id=1, opponent_id=3, opponent_name="zz")), allow=["cA", "aA"]),
    S("matches.quick_start_foreign_players", "POST", "/api/matches/quick-start", ["cB", "aB"],
      dict(json=dict(player_a_id=1, opponent_id=3, opponent_name="zz"))),
    S("matches.probe_url", "POST", "/api/matches/probe-url", NON_TEAM + ["pA1", "pA2", "pB1"],
      dict(json=dict(url="https://example.invalid/v.mp4"))),
    S("matches.reissue_video_token", "POST", "/api/matches/1/reissue_video_token", WRITE_DENY, allow=["cA", "aA", "admin"], observe=["pA1"]),
    S("matches.court_calibration", "POST", "/api/matches/1/court_calibration", WRITE_DENY, dict(json=dict(points=SIX)), allow=["cA", "aA", "admin"], observe=["pA1"]),
    S("matches.recordings_create", "POST", "/api/matches/1/recordings", WRITE_DENY, dict(json={}), allow=["cA", "aA", "admin"], observe=["pA1"]),
    S("recordings.patch", "PATCH", "/api/recordings/1", WRITE_DENY, dict(json=dict(label="PWN")), allow=["cA", "aA", "admin"], observe=["pA1"]),
    S("warmup.save", "POST", "/api/warmup/observations/1", WRITE_DENY,
      dict(json=dict(observations=[dict(player_id=1, observation_type="handedness", observation_value="R")])),
      allow=["cA", "aA", "admin"], observe=["pA1"]),
    S("annotation.undo", "POST", "/api/annotation/1/undo", WRITE_DENY, allow=["cA", "aA", "admin"], observe=["pA1"]),
    # --- sets / rallies / strokes ---
    S("sets.create", "POST", "/api/sets", WRITE_DENY, dict(json=dict(match_id=1, set_num=2)), allow=["cA", "aA", "admin"], observe=["pA1"]),
    S("sets.end", "PUT", "/api/sets/1/end", WRITE_DENY, dict(json=dict(winner="player_a", score_a=21, score_b=10)), allow=["cA", "aA", "admin"], observe=["pA1"]),
    S("rallies.create", "POST", "/api/rallies", WRITE_DENY, dict(json=dict(set_id=1, **RALLY_BODY)), allow=["cA", "aA", "admin"], observe=["pA1"]),
    S("rallies.update", "PUT", "/api/rallies/1", WRITE_DENY, dict(json=dict(winner="player_b")), allow=["cA", "aA", "admin"], observe=["pA1"]),
    S("rallies.delete", "DELETE", "/api/rallies/1", WRITE_DENY, allow=["cA", "aA", "admin"], observe=["pA1"]),
    S("strokes.create", "POST", "/api/strokes?rally_id=1", WRITE_DENY, dict(json=dict(STROKE_BODY, stroke_num=2)), allow=["cA", "aA", "admin"], observe=["pA1"]),
    S("strokes.batch", "POST", "/api/strokes/batch", WRITE_DENY,
      dict(json=dict(rally=dict(set_id=1, **RALLY_BODY), strokes=[STROKE_BODY])), allow=["cA", "aA", "admin"], observe=["pA1"]),
    S("strokes.update", "PUT", "/api/strokes/1", WRITE_DENY, dict(json=dict(stroke_num=1, player="player_b", shot_type="smash")), allow=["cA", "aA", "admin"], observe=["pA1"]),
    S("strokes.delete", "DELETE", "/api/strokes/1", WRITE_DENY, allow=["cA", "aA", "admin"], observe=["pA1"]),
    # --- conditions (選手個人の健康データ) ---
    S("conditions.create", "POST", "/api/conditions", NON_TEAM + FOREIGN + ["pA2"],
      dict(json=dict(player_id=1, measured_at="2026-09-30", weight_kg=70.0)), allow=["cA", "aA", "admin"]),
    S("conditions.questionnaire", "POST", "/api/conditions/questionnaire", NON_TEAM + FOREIGN + ["pA2"],
      dict(json=dict(player_id=1, measured_at="2026-09-30", condition_type="weekly", responses={}))),
    S("conditions.patch", "PATCH", "/api/conditions/1", NON_TEAM + FOREIGN + ["pA2"], dict(json=dict(weight_kg=65.0)),
      allow=["cA", "aA", "admin"]),
    S("conditions.delete", "DELETE", "/api/conditions/1", NON_TEAM + FOREIGN + ["pA2"]),
    # 自チーム選手の記録を他チームの試合 (match 1) に結び付けさせない (B の condition 2 を A の試合へ)
    S("conditions.patch_link_to_foreign_match", "PATCH", "/api/conditions/2", ["cB", "aB"], dict(json=dict(match_id=1))),
    S("conditions.patch_link_to_own_match", "PATCH", "/api/conditions/2", [], dict(json=dict(match_id=2)), allow=["cB", "aB"]),
    # --- expert / pipeline / video_import / youtube_live ---
    S("expert.labels", "POST", "/api/v1/expert/labels", WRITE_DENY + ["pA1"],
      dict(json=dict(match_id=1, stroke_id=1, annotator_role="coach", posture_collapse="none",
                     weight_distribution="center", shot_timing="optimal")), allow=["cA", "aA", "admin"]),
    S("expert.labels_stroke_of_other_match", "POST", "/api/v1/expert/labels", ["cB", "aB"],
      dict(json=dict(match_id=2, stroke_id=1, annotator_role="coach", posture_collapse="none",
                     weight_distribution="center", shot_timing="optimal"))),
    S("expert.shot_labels", "POST", "/api/v1/expert/shot_labels", ADMIN_ONLY,
      dict(json=dict(match_id=1, stroke_id=1, shot_type="clear"))),
    S("pipeline.run", "POST", "/api/v1/pipeline/run", WRITE_DENY + ["pA1"], dict(json=dict(match_id=1))),
    S("video_import.path", "POST", "/api/video_import/path", WRITE_DENY + ["pA1"],
      dict(json=dict(video_path="@VIDEO@", match_id=1)), allow=["cA", "aA", "admin"], loopback=True),
    # S-4: 全体走査の入口 / 区間への人の決定 / 採用。運用ロール (自チーム coach/analyst/admin) だけ。
    # player は自分の出る試合 (pA1) でも 403。cv_candidates モジュールは COVERED_ELSEWHERE だが、
    # 新しい書き込み口なので他チームの総当たりにも載せる (詳細は test_cv_segments_scan.py)。
    S("cv_candidates.scan", "POST", "/api/cv-candidates/scan/1", WRITE_DENY + ["pA1"], allow=["cA", "aA", "admin"]),
    S("cv_candidates.segment_decision", "POST", "/api/cv-candidates/1/segments/decisions", WRITE_DENY + ["pA1"],
      dict(json=dict(start_sec=1.0, end_sec=2.0, action="reject")), allow=["cA", "aA", "admin"]),
    S("cv_candidates.segment_adopt", "POST", "/api/cv-candidates/1/segments/adopt", WRITE_DENY + ["pA1"],
      dict(json=dict(start_sec=1.0, end_sec=2.0, rally_id=1)), allow=["cA", "aA", "admin"]),
    S("youtube_live.start", "POST", "/api/youtube_live/start", NON_TEAM + FOREIGN,
      dict(json=dict(url="https://www.youtube.com/watch?v=abcdefghijk", match_id=1)), observe=["pA1", "pA2"]),
    S("youtube_live.chunk", "POST", f"/api/youtube_live/{JOB_A}/chunk", NON_TEAM + FOREIGN,
      dict(content=b"abc", headers={"Content-Type": "application/octet-stream"}), observe=["pA1", "pA2"]),
    S("youtube_live.stop", "POST", f"/api/youtube_live/{JOB_A}/stop", NON_TEAM + FOREIGN, allow=["cA", "aA"], observe=["pA1", "pA2"]),
    # --- settings / db / sync / tunnel / benchmark / cluster (global) ---
    S("settings.update", "PUT", "/api/settings", ADMIN_ONLY,
      dict(json=dict(settings={"tracknet_max_cpu_pct": 40}))),
    S("db.maintenance", "POST", "/api/db/maintenance", ADMIN_ONLY),
    S("db.set_auto_vacuum", "POST", "/api/db/set_auto_vacuum", ADMIN_ONLY, dict(json=dict(mode="off"))),
    S("sync.backup", "POST", "/api/sync/backup", ADMIN_ONLY),
    S("sync.cloud_copy", "POST", "/api/sync/cloud/copy", ADMIN_ONLY, dict(files=PKG)),
    S("sync.cloud_import_from_path", "POST", "/api/sync/cloud/import_from_path?path=nope.sspkg&dry_run=true",
      ADMIN_ONLY),
    S("sync.resolve_conflict", "POST", "/api/sync/conflicts/1/resolve", ANALYST_GLOBAL + ["aB"],
      dict(json=dict(resolution="keep_local")), observe=["aA"]),
    S("sync.import", "POST", "/api/sync/import", ANALYST_GLOBAL, dict(files=PKG), observe=["aA", "aB"]),
    S("sync.preview", "POST", "/api/sync/preview", ANALYST_GLOBAL, dict(files=PKG), observe=["aA", "aB"]),
    S("sync.validate", "POST", "/api/sync/validate", ANALYST_GLOBAL, dict(files=PKG), allow=["aA", "aB", "admin"]),
    S("data_package.import", "POST", "/api/import/package", NO_PLAYER_ETC, dict(content=b"{}", headers={"Content-Type": "application/json"}),
      observe=["cA", "aA", "cB", "aB"]),
    S("tunnel.start", "POST", "/api/tunnel/start", ADMIN_ONLY),
    S("tunnel.stop", "POST", "/api/tunnel/stop", ADMIN_ONLY),
    S("tunnel.test_turn", "POST", "/api/webrtc/test-turn", ADMIN_ONLY),
    S("benchmark.run", "POST", "/api/v1/benchmark/run", ADMIN_ONLY, dict(json=dict(device_ids=["cpu"], targets=["yolo"]))),
    S("benchmark.cancel", "DELETE", "/api/v1/benchmark/jobs/nojob", ADMIN_ONLY),
    S("cv_benchmark.run", "POST", "/api/cv/benchmark", ADMIN_ONLY),
    S("archive.scan", "POST", "/api/archive/scan", ADMIN_ONLY),
    S("network.lan_mode", "POST", "/api/network/lan-mode?enable=true", ADMIN_ONLY),
    S("cache.invalidate", "POST", "/api/cache/invalidate", NO_PLAYER_ETC, observe=["cA", "aA", "cB", "aB"]),
    S("peer_cohort_stats", "POST", "/api/analysis/research/peer_cohort_stats", ADMIN_ONLY, dict(json={})),
    S("spine.promotion_override_set", "POST", "/api/analysis/meta/promotion_override", ADMIN_ONLY,
      dict(json=dict(analysis_type="x", status="promoted"))),
    S("spine.promotion_override_del", "DELETE", "/api/analysis/meta/promotion_override/x", ADMIN_ONLY),
    S("admin_security.reissue", "POST", "/api/admin/security/reissue_all_video_tokens", ADMIN_ONLY),
    S("admin_security.revoke_all", "POST", "/api/admin/security/revoke_all_tokens", ADMIN_ONLY),
    S("admin_security.limits_reset", "POST", "/api/admin/security/user_limits/11/reset", ADMIN_ONLY),
    S("admin_training.records", "POST", "/api/admin/training_data/records", ADMIN_ONLY,
      dict(json=dict(dataset_id="d", acquisition_date="2026-01-01", license_type="cc0", scope_description="s"))),
    S("internal_videos.mark_synced", "POST", "/api/_internal/videos/server_artifacts/1/mark_synced", ACTORS, worker=True),
    # cluster (全て admin 専用)
    S("cluster.config", "POST", "/api/cluster/config", ADMIN_ONLY, dict(json={})),
    S("cluster.detect", "POST", "/api/cluster/nodes/10.0.0.1/detect", ADMIN_ONLY),
    S("cluster.disable_sleep", "POST", "/api/cluster/nodes/10.0.0.1/disable-sleep", ADMIN_ONLY),
    S("cluster.ray_join", "POST", "/api/cluster/nodes/10.0.0.1/ray-join", ADMIN_ONLY),
    S("cluster.ray_restart", "POST", "/api/cluster/nodes/10.0.0.1/ray-restart", ADMIN_ONLY),
    S("cluster.wake", "POST", "/api/cluster/nodes/10.0.0.1/wake", ADMIN_ONLY),
    S("cluster.ping", "POST", "/api/cluster/ping", ADMIN_ONLY, dict(json={})),
    S("cluster.ray_start", "POST", "/api/cluster/ray/start", ADMIN_ONLY),
    S("cluster.ray_start_head", "POST", "/api/cluster/ray/start-head", ADMIN_ONLY),
    S("cluster.ray_stop", "POST", "/api/cluster/ray/stop", ADMIN_ONLY),
    # billing (SS_BILLING_ENABLED=1 / webhooks 有効にして認可を見る)
    S("billing.grant", "POST", "/api/_internal/billing/admin/grant_entitlement", ADMIN_ONLY,
      dict(json=dict(user_id=13, entitlement_type="premium")), billing=True),
    S("billing.product", "POST", "/api/_internal/billing/admin/products", ADMIN_ONLY,
      dict(json=dict(code="px", name="PX", price_jpy=1)), billing=True),
    S("billing.refund", "POST", "/api/_internal/billing/admin/refund/1", ADMIN_ONLY, billing=True),
    S("billing.cancel_foreign_order", "POST", f"/api/_internal/billing/orders/{ORDER_A}/cancel",
      _all_but("cA", "admin"), billing=True),
    S("billing.webhook_stripe", "POST", "/api/_internal/billing/webhooks/stripe", ACTORS,
      dict(content=b"{}", headers={"Content-Type": "application/json"}), billing=True),
    S("billing.webhook_komoju", "POST", "/api/_internal/billing/webhooks/komoju", ACTORS,
      dict(content=b"{}", headers={"Content-Type": "application/json"}), billing=True),
    S("billing.webhook_univapay", "POST", "/api/_internal/billing/webhooks/univapay", ACTORS,
      dict(content=b"{}", headers={"Content-Type": "application/json"}), billing=True),
    # auth: ユーザ / チーム管理 (id は他チームのもの)
    S("auth.team_create", "POST", "/api/auth/teams", ADMIN_ONLY, dict(json=dict(name="ProbeTeam"))),
    S("auth.team_patch", "PATCH", "/api/auth/teams/1", _all_but("admin", "cA"), dict(json=dict(notes="PWN"))),
    S("auth.team_delete", "DELETE", "/api/auth/teams/1", ADMIN_ONLY),
    S("auth.team_page_access", "PUT", "/api/auth/teams/ScopeTeamA/page-access", _all_but("admin", "cA", "aA"), dict(json=dict(page_keys=[]))),
    S("auth.user_create_in_A", "POST", "/api/auth/users", NON_TEAM + ["pA1", "pA2", "pB1", "cA", "cB", "aB"], dict(json=NEW_USER_A),
      allow=["aA", "admin"]),
    S("auth.user_create_in_B_by_aB", "POST", "/api/auth/users", NON_TEAM + ["pA1", "pA2", "pB1", "cA", "cB", "aA"], dict(json=NEW_USER_B),
      allow=["aB", "admin"]),
    S("auth.user_create_links_foreign_player", "POST", "/api/auth/users", ["aB"],
      dict(json=dict(NEW_USER_B, role="player", player_id=6))),
    S("auth.user_update_A", "PUT", "/api/auth/users/11", NON_TEAM + FOREIGN + ["pA1", "pA2"], dict(json=dict(display_name="PWN")),
      allow=["cA", "aA", "admin"]),
    S("auth.user_escalate_self", "PUT", "/api/auth/users/22", NON_TEAM + ["pA1", "pA2", "pB1"], dict(json=dict(role="admin"))),
    S("auth.user_delete_A", "DELETE", "/api/auth/users/11", ADMIN_ONLY),
    S("auth.user_page_access_A", "PUT", "/api/auth/users/13/page-access", NON_TEAM + FOREIGN + ["pA1", "pA2"], dict(json=dict(page_keys=[])),
      allow=["cA", "aA", "admin"]),
    S("auth.user_reset_password_A", "POST", "/api/auth/users/11/reset-password", ADMIN_ONLY),
    S("auth.user_unlock_A", "POST", "/api/auth/users/11/unlock", ADMIN_ONLY),
    S("auth_email.invite_into_A", "POST", "/api/auth/invitation/create", NON_TEAM + ["pA1", "pA2", "pB1", "aA", "aB", "cB"],
      dict(json=dict(email="probe@example.com", role="player", team_id=1)), allow=["cA", "admin"]),
    S("auth_email.approve_A", "POST", "/api/auth/users/12/approve", ADMIN_ONLY, dict(json=dict(role="player", team_id=1))),
    S("auth_email.reject_A", "POST", "/api/auth/users/12/reject", ADMIN_ONLY),
    # 他人の会話 / チャットセッション (所有者 cA = user 11。admin は運用上許容)
    S("llm.rename_foreign", "PATCH", "/api/llm/conversations/1", _all_but("cA", "admin"), dict(json=dict(title="PWN"))),
    S("llm.delete_foreign", "DELETE", "/api/llm/conversations/1", _all_but("cA", "admin")),
    S("llm.post_message_foreign", "POST", "/api/llm/conversations/1/messages", _all_but("cA", "admin"), dict(json=dict(content="hi"))),
    S("insights_chat.delete_foreign", "DELETE", "/api/insights/chat/sessions/1", _all_but("cA", "admin")),
    S("insights_chat.message_foreign", "POST", "/api/insights/chat/sessions/1/messages", _all_but("cA", "admin"), dict(json=dict(content="hi"))),
]

# 先行監査で動的検証済み / 罠・公開口 (別テストあり) のモジュール
COVERED_ELSEWHERE_MODULES = {
    "uploads", "media", "yolo", "tracknet", "cv_candidates", "comments", "bookmarks", "condition_tags",
    "human_forecast", "sessions",
    "canary", "decoy_maze", "public_site", "status_page", "telemetry",
}
# 認証前 / 本人自身の操作 (他人の id を取らない) — 認可の対象が「呼び出し本人」だけのもの
SELF_OR_PUBLIC = {
    "/api/auth/login", "/api/auth/logout", "/api/auth/refresh", "/api/auth/consents", "/api/auth/password",
    "/api/auth/mfa/confirm", "/api/auth/mfa/disable", "/api/auth/mfa/login", "/api/auth/mfa/setup",
    "/api/auth/mfa/recovery/regenerate", "/api/csp_report", "/api/auth/register", "/api/auth/invitation/accept",
    "/api/auth/password/request_reset", "/api/auth/password/reset", "/api/auth/email/resend_verification",
    "/api/auth/consents/{consent_type}", "/api/_internal/billing/orders",
    "/api/llm/conversations", "/api/insights/chat/sessions",
}


def _walk(routes, prefix=""):
    for r in routes:
        ctx = getattr(r, "include_context", None)
        if ctx is not None and getattr(ctx, "included_router", None) is not None:
            yield from _walk(ctx.included_router.routes, prefix + (getattr(ctx, "prefix", "") or ""))
            continue
        if isinstance(r, Mount):
            yield from _walk(r.routes, prefix + r.path)
            continue
        if isinstance(getattr(r, "path", None), str):
            yield (prefix + r.path, set(getattr(r, "methods", set()) or set()),
                   getattr(getattr(r, "endpoint", None), "__module__", "").split(".")[-1])


def _canon(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path.split("?")[0])


def _canon_concrete(path: str) -> str:
    p = path.split("?")[0]
    return re.sub(r"/(\d+|[0-9a-f]{32}|[0-9a-f-]{36}|nojob|x|ScopeTeamA|10\.0\.0\.1)(?=/|$)", "/{}", p)


def test_every_remaining_write_route_is_listed():
    """app のルートツリーから非 GET を列挙し、SPECS / 除外表のどちらにも無いものがあれば落とす。"""
    specs = {(s["method"], _canon_concrete(s["path"])) for s in SPECS}
    missing = []
    for path, methods, mod in _walk(app.router.routes):
        if mod in COVERED_ELSEWHERE_MODULES or not path.startswith("/api/") or path in SELF_OR_PUBLIC:
            continue
        for m in methods - {"GET", "HEAD", "OPTIONS"}:
            if (m, _canon(path)) not in specs:
                missing.append((m, path, mod))
    assert not missing, missing


# ─── 実行 ───────────────────────────────────────────────────────────────────

def _send(client, spec, actor):
    kw = dict(spec["kw"])
    headers = dict(kw.pop("headers", {}))
    headers.update(_hdr(actor))
    if "json" in kw and isinstance(kw["json"], dict):
        kw["json"] = {k: (app.state._audit_video if v == "@VIDEO@" else v) for k, v in kw["json"].items()}
    c = client
    if spec["opts"].get("loopback"):
        c = TestClient(app, raise_server_exceptions=False, client=("127.0.0.1", 50001))
    return c.request(spec["method"], spec["path"], headers=headers, **kw)


def _run(client, db, spec, actor):
    _seed2(db)
    before = _snapshot(db)
    r = _send(client, spec, actor)
    after = _snapshot(db)
    return r, _diff(before, after)


DENY_CASES = [(s["id"], a) for s in SPECS for a in s["deny"]]
ALLOW_CASES = [(s["id"], a) for s in SPECS for a in s["allow"]]
BY_ID = {s["id"]: s for s in SPECS}


@pytest.mark.parametrize("sid,actor", DENY_CASES)
def test_denied_and_untouched(client, db_session, monkeypatch, sid, actor):
    spec = BY_ID[sid]
    _apply_opts(monkeypatch, spec)
    r, changed = _run(client, db_session, spec, actor)
    assert r.status_code in (401, 403, 404), (sid, actor, r.status_code, r.text[:300])
    assert changed == [], (sid, actor, changed)


@pytest.mark.parametrize("sid,actor", ALLOW_CASES)
def test_positive_control_not_blocked(client, db_session, monkeypatch, sid, actor):
    spec = BY_ID[sid]
    _apply_opts(monkeypatch, spec)
    r, _ = _run(client, db_session, spec, actor)
    assert r.status_code not in (401, 403), (sid, actor, r.status_code, r.text[:300])


@pytest.mark.skipif(not os.environ.get("SS_PROBE_DUMP"), reason="exploration only")
def test_dump_matrix(client, db_session, monkeypatch):
    out = {}
    for spec in SPECS:
        _apply_opts(monkeypatch, spec)
        for actor in ACTORS:
            r, changed = _run(client, db_session, spec, actor)
            out[f"{spec['id']}|{actor}"] = [r.status_code, changed, r.text[:160]]
        with open(os.environ["SS_PROBE_DUMP"], "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=0)
