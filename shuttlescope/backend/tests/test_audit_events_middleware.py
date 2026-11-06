"""audit_events(データ変更の主体追跡)の検証。

3 観点:
  1. 分類ロジック(audit_targets): path/method/status から entity_type/action を
     正しく導けること。値を保存しない要約(summarize_body)が「列名のみ+件数+
     SHA-256」を返し、値を一切含まないこと。
  2. 網羅性: 主要な変更系エンティティ(match/set/rally/stroke/player/user/
     settings)がすべて監査対象として分類されること(router に log_access を
     足して回る方式の書き漏れを、横断 middleware + この網羅テストで防ぐ)。
  3. E2E: 実際に変更 API を叩くと audit_events に行が入り、誰が(user_id/role)・
     どの entity に・どの action を行ったかが記録され、かつ変更値そのものは
     保存されていないこと。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from backend.utils import audit_targets as at


# ───────────────────────── 1. 分類ロジック単体 ─────────────────────────
class TestClassifyPath:
    @pytest.mark.parametrize("path,etype,eid", [
        ("/api/matches", "match", None),
        ("/api/matches/42", "match", "42"),
        ("/api/matches/42/result", "match", "42"),
        ("/api/sets/7", "set", "7"),
        ("/api/sets/7/end", "set", "7"),
        ("/api/rallies", "rally", None),
        ("/api/rallies/9", "rally", "9"),
        ("/api/strokes", "stroke", None),
        ("/api/strokes/batch", "stroke", None),
        ("/api/strokes/5", "stroke", "5"),
        ("/api/players", "player", None),
        ("/api/players/3", "player", "3"),
        ("/api/settings", "settings", None),
        ("/auth/users", "user", None),
        ("/api/auth/users/11", "user", "11"),
        ("/api/conditions", "condition", None),
        ("/api/conditions/88", "condition", "88"),
        ("/api/conditions/questionnaire", "condition", "questionnaire"),
        ("/api/condition_tags", "condition_tag", None),
        ("/api/condition_tags/4", "condition_tag", "4"),
        ("/api/auth/teams", "team", None),
        ("/api/auth/teams/2", "team", "2"),
    ])
    def test_classify(self, path, etype, eid):
        got = at.classify_path(path)
        assert got is not None, f"{path} should be audited"
        assert got[0] == etype
        assert got[1] == eid

    @pytest.mark.parametrize("path", [
        "/api/analysis/overview",
        "/api/health",
        "/api/auth/login",
        "/",
        "",
    ])
    def test_non_targets(self, path):
        assert at.classify_path(path) is None

    def test_action_for_method(self):
        assert at.action_for_method("POST") == "create"
        assert at.action_for_method("put") == "update"
        assert at.action_for_method("PATCH") == "update"
        assert at.action_for_method("DELETE") == "delete"
        assert at.action_for_method("GET") is None

    def test_should_audit_only_success_writes(self):
        assert at.should_audit("POST", "/api/matches", 200) is True
        assert at.should_audit("POST", "/api/matches", 201) is True
        assert at.should_audit("POST", "/api/matches", 403) is False
        assert at.should_audit("POST", "/api/matches", 500) is False
        assert at.should_audit("GET", "/api/matches", 200) is False
        assert at.should_audit("POST", "/api/analysis/x", 200) is False


# ───────────────────── 2. 値を保存しない要約の検証 ─────────────────────
class TestSummarizeBodyHidesValues:
    def test_only_field_names_and_hash(self):
        secret_value = "Yamada Taro (sensitive PII)"
        body = json.dumps({
            "display_name": secret_value,
            "dominant_hand": "left",
            "team_id": 999,
        }).encode("utf-8")
        fields, count, body_hash = at.summarize_body(body)
        # 列名は残る
        assert set(fields) == {"display_name", "dominant_hand", "team_id"}
        assert count == 3
        # ハッシュは 64 hex
        assert body_hash and len(body_hash) == 64
        int(body_hash, 16)  # hex であること
        # 値は changed_fields にもハッシュの「平文」にも現れない
        assert secret_value not in "".join(fields)
        assert secret_value not in body_hash

    def test_list_of_dicts_batch(self):
        body = json.dumps([
            {"rally_id": 1, "shot_type": "clear"},
            {"rally_id": 2, "shot_type": "smash"},
        ]).encode("utf-8")
        fields, count, body_hash = at.summarize_body(body)
        assert set(fields) == {"rally_id", "shot_type"}
        assert count == 2
        assert len(body_hash) == 64

    def test_non_json_body_keeps_hash_only(self):
        fields, count, body_hash = at.summarize_body(b"\x00\x01binarypayload")
        assert fields is None
        assert count is None
        assert len(body_hash) == 64

    def test_empty_body(self):
        assert at.summarize_body(None) == (None, None, None)
        assert at.summarize_body(b"") == (None, None, None)


# ───────────────────── 3. 網羅性(漏れ検知) ─────────────────────
class TestCoverageOfWriteEntities:
    """主要変更系エンティティがすべて監査対象に含まれること。

    ここが落ちたら「新しい変更系エンティティが監査から漏れている」合図。
    audit_targets._PATTERNS に追加して再度緑にする運用。
    """
    REQUIRED = {
        "match": "/api/matches/1",
        "set": "/api/sets/1",
        "rally": "/api/rallies/1",
        "stroke": "/api/strokes/1",
        "player": "/api/players/1",
        "user": "/api/auth/users/1",
        "settings": "/api/settings",
        "condition": "/api/conditions/1",
        "condition_tag": "/api/condition_tags/1",
        "team": "/api/auth/teams/1",
    }

    def test_all_required_entities_classified(self):
        missing = []
        for etype, sample in self.REQUIRED.items():
            got = at.classify_path(sample)
            if got is None or got[0] != etype:
                missing.append((etype, sample, got))
        assert not missing, f"監査対象から漏れているエンティティ: {missing}"


# ── 2b. 実ルーター列挙による網羅(固定サンプルではなく実際の app.routes を走査) ──
class TestEveryWriteRouteIsClassified:
    """FastAPI app に登録された全ルートのうち、対象ドメインの変更系
    (POST/PUT/PATCH/DELETE)が 1 つ残らず classify_path で分類されることを検証する。

    固定サンプルではなく実ルートを列挙するため、将来
    「変更系エンドポイントを足したのに _PATTERNS に入れ忘れた」場合にここが落ちる。
    ゴールの『列挙して記録の無いものがあれば落ちる試験』を満たす。

    対象ドメイン: 試合/セット/ラリー/ストローク/選手/ユーザー/設定/
    コンディション(conditions, condition_tags)/チーム(auth/teams)。
    これら以外(analysis, reports, auth/login 等の非変更台帳)は監査対象外。
    """

    # 監査すべきドメインの path 断片。ここに該当する変更系ルートは
    # 必ず classify_path が非 None でなければならない。
    _AUDITED_PREFIXES = (
        "/api/matches", "/api/sets", "/api/rallies", "/api/strokes",
        "/api/players", "/api/settings", "/api/conditions",
        "/api/condition_tags", "/api/auth/users", "/api/auth/teams",
    )

    # 変更系メソッドだが監査対象外にする個別ルート(認証フロー等。値台帳ではない)。
    # 例: /api/auth/teams/{team_name}/page-access はアクセス制御設定で team に紐付くため
    #     team として拾われる(除外しない)。ここは本当に対象外のものだけを列挙する。
    _EXCLUDE_EXACT: set[str] = set()

    def _iter_write_routes(self):
        from backend.main import app
        for route in app.routes:
            methods = getattr(route, "methods", None)
            path = getattr(route, "path", None)
            if not methods or not path:
                continue
            writes = methods & at.AUDITED_METHODS
            if not writes:
                continue
            yield path, writes

    def test_every_audited_domain_write_route_is_classified(self):
        import re as _re
        missing = []
        for path, writes in self._iter_write_routes():
            # FastAPI の {param} を実値サンプルに置換して分類にかける。
            sample = _re.sub(r"\{[^}]+\}", "1", path)
            if not sample.startswith(self._AUDITED_PREFIXES):
                continue
            if sample in self._EXCLUDE_EXACT:
                continue
            got = at.classify_path(sample)
            if got is None:
                missing.append((path, sorted(writes)))
        assert not missing, (
            "監査対象ドメインの変更系ルートが classify_path=None で記録から漏れている: "
            f"{missing}"
        )


# ───────────────────── 4. E2E (実 API → audit_events) ─────────────────────
ADMIN_USER = "admin_ae"
ADMIN_PASS = "AuditEvt1!"


@pytest.fixture()
def client(test_engine, monkeypatch):
    from backend.routers import auth as _auth_module
    _auth_module._IP_LOGIN_TIMES.clear()
    from backend.db.models import User, RefreshToken, RevokedToken, AccessLog, AuditEvent
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=test_engine)
    with Session() as s:
        s.query(AuditEvent).delete()
        s.query(AccessLog).delete()
        s.query(RefreshToken).delete()
        s.query(RevokedToken).delete()
        s.query(User).delete()
        s.commit()

    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", ADMIN_USER)
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", ADMIN_PASS)
    from backend.config import settings
    settings.BOOTSTRAP_ADMIN_USERNAME = ADMIN_USER
    settings.BOOTSTRAP_ADMIN_PASSWORD = ADMIN_PASS
    from backend.main import app
    with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as c:
        c._test_engine = test_engine
        yield c


def _login(client, username, password):
    r = client.post("/api/auth/login", json={
        "grant_type": "credential", "identifier": username, "password": password,
    })
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _audit_rows(client):
    from backend.db.models import AuditEvent
    from sqlalchemy.orm import sessionmaker
    Session = sessionmaker(bind=client._test_engine)
    with Session() as s:
        return s.query(AuditEvent).all()


def test_user_create_is_audited_without_values(client):
    admin = _login(client, ADMIN_USER, ADMIN_PASS)
    secret_name = "Confidential Analyst Name"
    resp = client.post(
        "/api/auth/users",
        json={"username": "an_ae1", "role": "analyst",
              "display_name": secret_name, "password": "AnalystPass1!",
              "team_name": "TeamAE"},
        headers={"Authorization": f"Bearer {admin}"},
    )
    assert resp.status_code in (200, 201), resp.text

    rows = _audit_rows(client)
    user_posts = [r for r in rows if r.entity_type == "user" and r.action == "create"]
    assert user_posts, f"user create が audit_events に無い。rows={[(r.entity_type, r.action, r.path) for r in rows]}"
    row = user_posts[-1]
    # 誰が: admin の user_id / role が記録されている
    assert row.user_id is not None
    assert row.role in ("admin",)
    assert row.method == "POST"
    assert row.status in (200, 201)
    # フィールド名は残るが値は残らない
    assert row.changed_fields is not None
    assert "display_name" in row.changed_fields
    assert secret_name not in (row.changed_fields or "")
    assert secret_name not in (row.body_hash or "")
    assert row.body_hash and len(row.body_hash) == 64
    assert row.request_id is not None  # request_logs と相関可能


def test_failed_write_is_not_audited_as_success(client):
    # 認証なしで保護された変更エンドポイントを叩く → 401/403。成功監査されないこと。
    before = len(_audit_rows(client))
    resp = client.post("/api/auth/users", json={"username": "x"})
    assert resp.status_code in (401, 403, 422)
    after = _audit_rows(client)
    # 失敗(非 2xx)は audit_events(成功変更の台帳)に積まれない
    success_user_creates = [r for r in after if r.entity_type == "user" and r.action == "create"]
    assert len(success_user_creates) == 0


def test_get_is_not_audited(client):
    admin = _login(client, ADMIN_USER, ADMIN_PASS)
    client.get("/api/auth/audit-logs", headers={"Authorization": f"Bearer {admin}"})
    rows = _audit_rows(client)
    assert all(r.method != "GET" for r in rows)
