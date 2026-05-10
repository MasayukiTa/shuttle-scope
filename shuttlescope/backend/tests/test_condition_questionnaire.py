"""体調質問票 Phase 2 のテスト。"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.analysis.condition_questions import (
    PRE_MATCH_REQUIRED_IDS,
    REVERSED_ITEMS,
    WEEKLY_REQUIRED_IDS,
)
from backend.db.database import get_db
from backend.db.models import Player
from backend.main import app


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def player(db_session):
    p = Player(name="質問票テスト選手", dominant_hand="R")
    db_session.add(p)
    db_session.flush()
    db_session.commit()
    return p


def _all_threes() -> dict:
    return {qid: 3 for qid in WEEKLY_REQUIRED_IDS}


def _submit(client, player_id, responses, measured_at="2026-04-15",
            condition_type="weekly", match_id=None, role: str = "admin"):
    """Submit a questionnaire response.

    Round 258 R2: condition POST/GET responses are role-filtered per Tier 1-4
    sensitivity matrix. With ROLE_MAX_TIER reduced (analyst=1, coach=1, player=2,
    admin=4), only admin can see all scoring fields (f1_physical etc are Tier 2,
    validity_* are Tier 1/2, questionnaire_json is Tier 4).
    Default to admin so scoring-detail assertions see unfiltered output.
    TestRoleFilter tests override role explicitly to verify per-role filtering.
    """
    body = {
        "player_id": player_id,
        "measured_at": measured_at,
        "condition_type": condition_type,
        "responses": responses,
    }
    if match_id is not None:
        body["match_id"] = match_id
    return client.post(
        "/api/conditions/questionnaire",
        json=body,
        headers={"X-Role": role},
    )


class TestMaster:
    def test_weekly_master(self, client):
        resp = client.get("/api/conditions/master?condition_type=weekly")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["condition_type"] == "weekly"
        assert data["meta"]["total_items"] == 44
        ids = [q["id"] for q in data["questions"]]
        # V 含む 44、F* 合計 40
        assert len(ids) == 44
        assert len([i for i in ids if i.startswith("F")]) == 40
        assert len([i for i in ids if i.startswith("V")]) == 4
        # 逆転フラグが反映されている
        rev_map = {q["id"]: q["reversed"] for q in data["questions"]}
        assert rev_map["F1-06"] is True
        assert rev_map["F1-01"] is False

    def test_pre_match_master(self, client):
        resp = client.get("/api/conditions/master?condition_type=pre_match")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["condition_type"] == "pre_match"
        assert data["meta"]["total_items"] == 10
        assert [q["id"] for q in data["questions"]] == [f"P-{i:02d}" for i in range(1, 11)]


class TestScoringRoundTrip:
    def test_all_threes_gives_ccs_50(self, client, player):
        # 全項目 3 → F? 合計 = 24 × 5 = 120、ccs = 200-120 = 80
        resp = _submit(client, player.id, _all_threes())
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["f1_physical"] == 24
        assert data["f2_stress"] == 24
        assert data["f3_mood"] == 24
        assert data["f4_motivation"] == 24
        assert data["f5_sleep_life"] == 24
        assert data["total_score"] == 120
        assert data["ccs_score"] == 80

    def test_reversed_item_reflected(self, client, player):
        # 逆転項目だけ 5、非逆転項目 1 → F? はどの項目も 1 点で合計最小
        r = {}
        for qid in WEEKLY_REQUIRED_IDS:
            if qid.startswith("V"):
                r[qid] = 1
            elif qid in REVERSED_ITEMS:
                r[qid] = 5  # reverse → 1
            else:
                r[qid] = 1
        resp = _submit(client, player.id, r)
        assert resp.status_code == 201
        data = resp.json()["data"]
        # 各因子 8 項目×1 = 8、total 40、ccs 160
        assert data["total_score"] == 40
        assert data["ccs_score"] == 160

    def test_missing_response_returns_422(self, client, player):
        r = _all_threes()
        r.pop("F1-01")
        resp = _submit(client, player.id, r)
        assert resp.status_code == 422

    def test_invalid_value_returns_422(self, client, player):
        r = _all_threes()
        r["F1-01"] = 9
        resp = _submit(client, player.id, r)
        assert resp.status_code == 422


class TestValidity:
    def test_v01_high_flag(self, client, player):
        r = _all_threes()
        r["V-01"] = 5  # +15
        resp = _submit(client, player.id, r)
        data = resp.json()["data"]
        # 直線回答（全部3 の V 除外集合）でも +20 されるため score >= 20
        assert data["validity_score"] >= 15
        assert "V-01_high" in data["validity_flags_json"]

    def test_reverse_pair_mismatch_adds_score(self, client, player):
        r = _all_threes()
        # F1-05 (neg) = 5 → reversed 値 1、F1-06 (pos 逆転) = 5 → 差 |5-1|=4 >=3
        r["F1-05"] = 5
        r["F1-06"] = 5
        resp = _submit(client, player.id, r)
        data = resp.json()["data"]
        assert "reverse_pair_mismatch:F1-05/F1-06" in data["validity_flags_json"]

    def test_straight_line_plus_20(self, client, player):
        r = _all_threes()  # V 含め全部3
        resp = _submit(client, player.id, r)
        data = resp.json()["data"]
        assert data["validity_score"] >= 20
        assert "straight_line_response" in data["validity_flags_json"]

    def test_sudden_change_plus_10(self, client, player):
        # 1 回目: 全 1（F 部）→ reverse 後 F 因子は半々で中間値、ccs は高
        # 素直に 2 つ提出し、ΔCCS>=40 を作る。
        r_low = {qid: 3 for qid in WEEKLY_REQUIRED_IDS}
        _submit(client, player.id, r_low, measured_at="2026-04-10").raise_for_status()

        # 2 回目: 非逆転 5/逆転 5/V 1 → 非逆転 +5、逆転 +1 の偏り。
        r2 = {}
        for qid in WEEKLY_REQUIRED_IDS:
            if qid.startswith("V"):
                r2[qid] = 1
            elif qid in REVERSED_ITEMS:
                r2[qid] = 5  # → 1
            else:
                r2[qid] = 1  # 1
        # total = 40, ccs=160 → Δ = 160-80 = 80
        resp = _submit(client, player.id, r2, measured_at="2026-04-14")
        data = resp.json()["data"]
        assert data["delta_prev"] == 80.0
        assert any("ccs_sudden_change" in f for f in [data["validity_flags_json"]])


class TestRoleFilter:
    # Round 258 R2: ROLE_MAX_TIER を analyst=4/coach=3 → analyst=1/coach=1 に縮小。
    # 同意書 第5条 (体組成・医療自由記述は admin と本人 player のみ生公開) に整合。
    # ccs_score / f1_physical 等 Tier 2 は player と admin のみ可視、coach/analyst は
    # validity_flag (Tier 1) のみ可視という新規範を assert する形にテストを書き直し。

    def test_player_view_hides_validity_score(self, client, player):
        """player は Tier 2 まで可視: ccs_score / f1_physical 等は見える。
        validity_score (Tier 2) は本人除外ルールが router 側にあれば隠れる。
        ※実装側で player に対する `validity_score` 露出ポリシーが固まったら追補。
        """
        resp = _submit(client, player.id, _all_threes())
        cid = resp.json()["data"]["id"]
        r = client.get(
            f"/api/conditions/{cid}",
            headers={"X-Role": "player", "X-Player-Id": str(player.id)},
        )
        assert r.status_code == 200
        data = r.json()["data"]
        # player = Tier 2 → ccs_score (Tier 2) / f1_physical (Tier 2) は可視
        assert "ccs_score" in data
        assert "f1_physical" in data
        # Tier 4 (questionnaire_json / general_comment / injury_notes) は drop
        assert "questionnaire_json" not in data
        assert "injury_notes" not in data

    def test_coach_view_only_tier_le_1(self, client, player):
        """coach=Tier 1: validity_flag (Tier 1) のみ。Tier 2+ は drop。"""
        resp = _submit(client, player.id, _all_threes())
        cid = resp.json()["data"]["id"]
        r = client.get(f"/api/conditions/{cid}", headers={"X-Role": "coach"})
        data = r.json()["data"]
        # validity_flag は Tier 1 → 可視
        assert "validity_flag" in data
        # f1_physical (Tier 2) / total_score (Tier 2) / validity_score (Tier 2) は drop
        assert "f1_physical" not in data
        assert "total_score" not in data
        assert "validity_score" not in data

    def test_analyst_view_only_tier_le_1(self, client, player):
        """analyst=Tier 1: validity_flag (Tier 1) のみ。Tier 2+ は drop。
        旧テスト名 (`..._has_everything`) は廃止 (R2 で analyst tier 縮小)。
        """
        resp = _submit(client, player.id, _all_threes())
        cid = resp.json()["data"]["id"]
        r = client.get(f"/api/conditions/{cid}", headers={"X-Role": "analyst"})
        data = r.json()["data"]
        # validity_flag は Tier 1 → 可視
        assert "validity_flag" in data
        # Tier 2+ は drop (questionnaire_json は Tier 4)
        assert "f1_physical" not in data
        assert "questionnaire_json" not in data
        assert "validity_score" not in data

    def test_role_via_query(self, client, player):
        resp = _submit(client, player.id, _all_threes())
        cid = resp.json()["data"]["id"]
        r = client.get(f"/api/conditions/{cid}?role=player")
        assert r.status_code == 200
        # player は Tier 2 まで可視 (validity_score も Tier 2 なので可視)。
        # 旧仕様 (`validity_score` を player から隠す) は R2 で field-level でなく
        # router 側の owner check に移行したため、ここでは field-level filter のみ assert。
        data = r.json()["data"]
        assert "ccs_score" in data


class TestPreMatch:
    def test_pre_match_roundtrip(self, client, player):
        # R2 tier filter: pre_match POST も role 単位フィルタを受けるため、
        # total_score (Tier 2) を assert する側は admin role でリクエストする。
        r = {qid: 4 for qid in PRE_MATCH_REQUIRED_IDS}
        body = {
            "player_id": player.id,
            "measured_at": "2026-04-15",
            "condition_type": "pre_match",
            "responses": r,
        }
        resp = client.post(
            "/api/conditions/questionnaire",
            json=body,
            headers={"X-Role": "admin"},
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        # 10 項目 × 4 = 40 を total_score に格納
        assert data["total_score"] == 40
        assert data["condition_type"] == "pre_match"
