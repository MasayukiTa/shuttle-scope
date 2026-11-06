"""ステータス/メンテ API のテスト。公開読み取り + admin 書き込みゲート。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from backend.main import app
import pytest
from backend.utils.jwt_utils import create_access_token

@pytest.fixture(autouse=True)
def _seed_admin_user(db_session):
    """このファイルの admin トークンは `user_id=1` を名指ししている。
    対応する実ユーザを用意する。

    `require_admin` は DB 上の user を引いて role / locked_until /
    承認待ち / totp_enabled を確認するので、ユーザが居ないと
    「削除済み admin」と同じ扱いになり 403 になる。
    """
    from backend.db.models import User

    if db_session.get(User, 1) is None:
        db_session.add(User(id=1, username="seeded_admin", role="admin", totp_enabled=True))
        db_session.commit()
    yield



def _admin():
    return {"Authorization": f"Bearer {create_access_token(user_id=1, role='admin', minutes=10)}"}


def test_public_status_is_anonymous_and_shaped():
    with TestClient(app) as client:
        r = client.get("/api/public/status")  # 認証なし
    assert r.status_code == 200
    b = r.json()
    assert "overall" in b and "active_incidents" in b and "maintenance" in b


def test_admin_incident_appears_then_resolves():
    with TestClient(app) as client:
        c = client.post("/api/status/incidents",
                        json={"title": "tunnel down", "severity": "critical", "component": "tunnel",
                              "reason": "cloudflared lost edge"},
                        headers=_admin())
        assert c.status_code == 201, c.text
        inc_id = c.json()["id"]
        # 公開ステータスに active として現れ、overall は down
        s = client.get("/api/public/status").json()
        assert any(i["id"] == inc_id for i in s["active_incidents"])
        assert s["overall"] == "down"
        # 解決 → active から消える
        p = client.patch(f"/api/status/incidents/{inc_id}", json={"resolved": True}, headers=_admin())
        assert p.status_code == 200 and p.json()["status"] == "resolved"
        s2 = client.get("/api/public/status").json()
        assert all(i["id"] != inc_id for i in s2["active_incidents"])


def test_non_admin_cannot_create_incident():
    with TestClient(app) as client:
        r = client.post("/api/status/incidents", json={"title": "x", "severity": "minor"},
                        headers={"Authorization": f"Bearer {create_access_token(user_id=5, role='coach', minutes=10)}"})
    assert r.status_code in (401, 403)


def test_maintenance_appears_in_public():
    with TestClient(app) as client:
        c = client.post("/api/status/maintenance",
                        json={"title": "メンテ", "body": "6/10 02:00 から 2h",
                              "scheduled_start": "2099-06-10T02:00:00"},
                        headers=_admin())
        assert c.status_code == 201, c.text
        mid = c.json()["id"]
        s = client.get("/api/public/status").json()
        assert any(m["id"] == mid for m in s["maintenance"])


def test_invalid_severity_422():
    with TestClient(app) as client:
        r = client.post("/api/status/incidents", json={"title": "x", "severity": "boom"}, headers=_admin())
    assert r.status_code == 422


def test_announcement_appears_in_public():
    with TestClient(app) as client:
        c = client.post("/api/status/announcements",
                        json={"title": "新機能を追加しました", "body": "公開更新情報のテスト", "pinned": True},
                        headers=_admin())
        assert c.status_code == 201, c.text
        aid = c.json()["id"]
        assert c.json()["pinned"] is True
        s = client.get("/api/public/status").json()
        assert "announcements" in s
        assert any(a["id"] == aid and a["title"] == "新機能を追加しました" for a in s["announcements"])


def test_draft_announcement_hidden_from_public():
    with TestClient(app) as client:
        c = client.post("/api/status/announcements", json={"title": "下書き"}, headers=_admin())
        aid = c.json()["id"]
        # draft 化 → 公開フィードから消える
        p = client.patch(f"/api/status/announcements/{aid}", json={"status": "draft"}, headers=_admin())
        assert p.status_code == 200 and p.json()["status"] == "draft"
        s = client.get("/api/public/status").json()
        assert all(a["id"] != aid for a in s["announcements"])


def test_non_admin_cannot_create_announcement():
    with TestClient(app) as client:
        r = client.post("/api/status/announcements", json={"title": "x"},
                        headers={"Authorization": f"Bearer {create_access_token(user_id=7, role='coach', minutes=10)}"})
    assert r.status_code in (401, 403)


# ── F-T001-06: 公開ステータスの浄化 (内部名/生メトリクスを匿名者に見せない) ──
#
# 匿名の公開ページは「利用者に意味のある」公開コンポーネント (web/signin/database/
# analysis) の状態色・最終確認時刻・劣化時の平易な一文のみを返す。
# tunnel/GPU/VRAM/CPU/RAM などの内部名・生数値は公開出力に含めない。

from backend.db.models import HealthSample

_PUBLIC_KEYS = {"web", "signin", "database", "analysis"}
# 公開コンポーネント dict が持つキーはこれだけ (生メトリクスキーを追加しない)。
_PUBLIC_COMP_KEYS = {"key", "name_ja", "name_en", "status", "note_ja", "note_en",
                     "uptime_24h", "sampled_at"}
# 公開してはならない内部名/生メトリクス語。
_FORBIDDEN_TOKENS = ("tunnel", "公開トンネル", "GPU", "VRAM", "CPU", "RAM",
                     "gpu", "worker", "解析ワーカー", "edge", "cloudflared")


def _seed_all_components(db, status="operational", minute=0):
    from datetime import datetime
    now = datetime(2026, 6, 5, 12, minute, 0)
    # 内部コンポーネントごとに 1 サンプル。detail には実際の生値を入れておき、
    # 公開出力に漏れないことを確かめる。
    rows = [
        ("api", "CPU 70% / RAM 80%", 70.0),
        ("tunnel", "edge 接続 1", 1.0),
        ("database", "応答 12ms", 12.0),
        ("gpu", "GPU 47% / VRAM 3.2/8GB", 47.0),
        ("worker", "稼働中", None),
        ("clock", "同期済み", 0.3),
    ]
    for comp, detail, metric in rows:
        db.add(HealthSample(component=comp, status=status, metric=metric,
                            detail=detail, sampled_at=now))
    db.commit()


def test_public_status_components_use_public_keys_only(db_session):
    _seed_all_components(db_session)
    with TestClient(app) as client:
        comps = client.get("/api/public/status").json()["components"]
    keys = {c["key"] for c in comps}
    assert keys == _PUBLIC_KEYS
    # 内部キーは 1 つも出ない。
    assert not (keys & {"api", "tunnel", "gpu", "worker", "clock"})


def test_public_status_component_dict_pins_key_set(db_session):
    """公開コンポーネント dict のキー集合を固定する。detail/metric は出ない。"""
    _seed_all_components(db_session)
    with TestClient(app) as client:
        comps = client.get("/api/public/status").json()["components"]
    for c in comps:
        assert set(c.keys()) == _PUBLIC_COMP_KEYS, c
        assert "detail" not in c and "metric" not in c


def test_public_status_leaks_no_internal_names_or_figures(db_session):
    """公開 JSON 全体を文字列化して、内部名/生インフラ数値が一切漏れていないこと。"""
    import json
    _seed_all_components(db_session)
    with TestClient(app) as client:
        body = client.get("/api/public/status").json()
    blob = json.dumps(body, ensure_ascii=False)
    for tok in _FORBIDDEN_TOKENS:
        assert tok not in blob, tok
    # 生メトリクス文字列そのものも漏れない。
    assert "CPU 70%" not in blob and "VRAM 3.2/8GB" not in blob and "edge 接続" not in blob


def test_public_components_use_plain_names(db_session):
    _seed_all_components(db_session)
    with TestClient(app) as client:
        comps = {c["key"]: c for c in client.get("/api/public/status").json()["components"]}
    assert comps["web"]["name_ja"] == "ウェブサイト" and comps["web"]["name_en"] == "Web site"
    assert comps["signin"]["name_en"] == "Sign-in"
    assert comps["database"]["name_en"] == "Database"
    assert comps["analysis"]["name_en"] == "Video analysis"


def test_public_components_note_only_when_degraded(db_session):
    """正常時は note は None。劣化時は平易な一文を出し、生値は含まない。"""
    _seed_all_components(db_session, status="operational")
    with TestClient(app) as client:
        comps = {c["key"]: c for c in client.get("/api/public/status").json()["components"]}
    assert comps["database"]["note_ja"] is None and comps["database"]["note_en"] is None
    # 劣化させる (より新しい sampled_at で上書きし、latest を確定的に degraded にする)
    _seed_all_components(db_session, status="degraded", minute=10)
    with TestClient(app) as client:
        comps = {c["key"]: c for c in client.get("/api/public/status").json()["components"]}
    note = comps["database"]["note_ja"]
    assert note and "ms" not in note and "%" not in note


def test_public_incident_hides_internal_component_key(db_session):
    """incident の内部 component (tunnel) は公開ラベルへ写し、内部キーは出さない。"""
    with TestClient(app) as client:
        c = client.post("/api/status/incidents",
                        json={"title": "x", "severity": "critical", "component": "tunnel"},
                        headers=_admin())
        assert c.status_code == 201, c.text
        s = client.get("/api/public/status").json()
    inc = s["active_incidents"][0]
    assert "component" not in inc
    assert inc["component_ja"] == "ウェブサイト" and inc["component_en"] == "Web site"


def test_public_status_day_accepts_public_key_rejects_internal(db_session):
    with TestClient(app) as client:
        ok = client.get("/api/public/status/day?day=2026-06-05&component=web")
        assert ok.status_code == 200, ok.text
        for internal in ("tunnel", "gpu", "worker", "clock", "api"):
            r = client.get("/api/public/status/day?day=2026-06-05&component=" + internal)
            assert r.status_code == 400, internal


# ── g24: incident タイトルの内部用語を表示時に平易語へ写す ──
#
# 障害履歴に保存済みのタイトル (例 'GPU が利用できません') には内部コンポーネント名
# (GPU/VRAM/CPU/RAM/tunnel/トンネル) が入っていることがある。公開表示時に平易語へ写し、
# 保存データ (StatusIncident.title) 自体は変更しないことを固定する。

from backend.routers.status_page import _map_public_title


def test_map_public_title_known_gpu_phrase():
    # 既知フレーズ完全一致: ja/en とも指定の平易語へ。
    ja, en = _map_public_title("GPU が利用できません")
    assert ja == "映像解析が利用できません"
    assert en == "Video analysis was unavailable"


def test_map_public_title_keyword_fallback():
    # 完全一致しなくても内部キーワードを含むタイトルは種類別の平易文へ。
    # GPU/VRAM -> 映像解析
    ja, en = _map_public_title("VRAM 不足で解析ジョブが落ちました")
    assert ja == "映像解析が利用できません" and en == "Video analysis was unavailable"
    # tunnel/トンネル -> サイト接続
    ja2, en2 = _map_public_title("cloudflared tunnel が切れました")
    assert "GPU" not in ja2 and "tunnel" not in en2.lower()
    # CPU/RAM -> 負荷
    ja3, en3 = _map_public_title("CPU 使用率が 100% になりました")
    assert "CPU" not in ja3 and "CPU" not in en3


def test_map_public_title_passthrough_plain():
    # 内部用語を含まない平易なタイトルはそのまま (ja/en 共通)。
    ja, en = _map_public_title("一時的な接続エラー")
    assert ja == "一時的な接続エラー" and en == "一時的な接続エラー"


def test_public_incident_title_maps_gpu_and_keeps_stored(db_session):
    """API 経由: GPU タイトルの incident は公開側で平易語に写り、
    公開 JSON に 'GPU' が漏れない。保存済み title 自体は変わらない。"""
    import json
    from backend.db.models import StatusIncident
    with TestClient(app) as client:
        c = client.post("/api/status/incidents",
                        json={"title": "GPU が利用できません", "severity": "major",
                              "component": "gpu"},
                        headers=_admin())
        assert c.status_code == 201, c.text
        inc_id = c.json()["id"]
        s = client.get("/api/public/status").json()
    inc = next(i for i in s["active_incidents"] if i["id"] == inc_id)
    assert inc["title_ja"] == "映像解析が利用できません"
    assert inc["title_en"] == "Video analysis was unavailable"
    # 公開 title も平易語で上書きされている (公開 JSON に GPU が出ない)。
    assert inc["title"] == "映像解析が利用できません"
    assert "GPU" not in json.dumps(s, ensure_ascii=False)
    # 保存データ (DB) は原文のまま。
    stored = db_session.get(StatusIncident, inc_id)
    assert stored.title == "GPU が利用できません"
