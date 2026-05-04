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
            condition_type="weekly", match_id=None):
    body = {
        "player_id": player_id,
        "measured_at": measured_at,
        "condition_type": condition_type,
        "responses": responses,
    }
    if match_id is not None:
        body["match_id"] = match_id
    return client.post("/api/conditions/questionnaire", json=body)


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
    def test_player_view_hides_validity(self, client, player):
        resp = _submit(client, player.id, _all_threes())
        cid = resp.json()["data"]["id"]
        r = client.get(f"/api/conditions/{cid}", headers={"X-Role": "player", "X-Player-Id": str(player.id)})
        assert r.status_code == 200
        data = r.json()["data"]
        assert "validity_score" not in data
        assert "validity_flag" not in data
        assert "f1_physical" not in data
        assert "ccs_score" in data
        assert "factor_labels" in data
        assert "personal_range" in data

    def test_coach_view_shows_factors_hides_validity_score(self, client, player):
        resp = _submit(client, player.id, _all_threes())
        cid = resp.json()["data"]["id"]
        r = client.get(f"/api/conditions/{cid}", headers={"X-Role": "coach"})
        data = r.json()["data"]
        assert "f1_physical" in data
        assert "total_score" in data
        assert "validity_flag" in data
        assert "validity_score" not in data

    def test_analyst_view_has_everything(self, client, player):
        resp = _submit(client, player.id, _all_threes())
        cid = resp.json()["data"]["id"]
        r = client.get(f"/api/conditions/{cid}", headers={"X-Role": "analyst"})
        data = r.json()["data"]
        assert "validity_score" in data
        assert "questionnaire_json" in data
        assert "f1_physical" in data

    def test_role_via_query(self, client, player):
        resp = _submit(client, player.id, _all_threes())
        cid = resp.json()["data"]["id"]
        r = client.get(f"/api/conditions/{cid}?role=player")
        assert r.status_code == 200
        assert "validity_score" not in r.json()["data"]


class TestPreMatch:
    def test_pre_match_roundtrip(self, client, player):
        r = {qid: 4 for qid in PRE_MATCH_REQUIRED_IDS}
        body = {
            "player_id": player.id,
            "measured_at": "2026-04-15",
            "condition_type": "pre_match",
            "responses": r,
        }
        resp = client.post("/api/conditions/questionnaire", json=body)
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        # 10 項目 × 4 = 40 を total_score に格納
        assert data["total_score"] == 40
        assert data["condition_type"] == "pre_match"
