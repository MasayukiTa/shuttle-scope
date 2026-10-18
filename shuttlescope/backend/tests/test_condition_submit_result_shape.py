"""POST /api/conditions/questionnaire の応答の実形を固定する。

結果カード (src/components/condition/ConditionResult.tsx) はこの応答のキーを読む。
フロントが存在しないキー (ccs / personal_range_low / factors) を読んでいたため、
CCS が「—」のままで平常レンジも因子表示も出なかった。ここでキー名と Tier 別の可視性を固定する。
フロント側のテストはこのテストが出力する実ペイロードを fixture として使う。
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.analysis.condition_questions import REVERSED_ITEMS, WEEKLY_REQUIRED_IDS
from backend.db.database import get_db
from backend.db.models import Player
from backend.main import app


@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def player(db_session):
    p = Player(name="応答形テスト選手", dominant_hand="R")
    db_session.add(p)
    db_session.commit()
    return p


def _responses(v: int) -> dict:
    out = {}
    for qid in WEEKLY_REQUIRED_IDS:
        if qid.startswith("V"):
            out[qid] = 1
        elif v == 3:
            out[qid] = 3
        else:
            out[qid] = 5 if qid in REVERSED_ITEMS else 1
    return out


def _post(client, pid, v, when, headers):
    return client.post(
        "/api/conditions/questionnaire",
        json={"player_id": pid, "measured_at": when, "condition_type": "weekly",
              "responses": _responses(v)},
        headers=headers,
    )


def _seed_history(client, pid, n):
    """交互に 3 / 最良を n 件入れる (SD > 0 の履歴)。"""
    base = date(2026, 1, 5)
    for i in range(n):
        r = _post(client, pid, 3 if i % 2 == 0 else 5,
                  (base + timedelta(days=7 * i)).isoformat(), {"X-Role": "admin"})
        assert r.status_code == 201, r.text


NEXT_DAY = (date(2026, 1, 5) + timedelta(days=7 * 20)).isoformat()


def test_admin_submit_has_the_keys_the_result_card_reads(client, player):
    _seed_history(client, player.id, 8)
    r = _post(client, player.id, 3, NEXT_DAY, {"X-Role": "admin"})
    assert r.status_code == 201, r.text
    d = r.json()["data"]
    # フロントが読む実キー
    assert d["ccs_score"] == 80
    assert d["n_28"] == 8
    assert d["delta_28ma"] is not None
    assert set(d["factor_labels"]) == {
        "f1_physical", "f2_stress", "f3_mood", "f4_motivation", "f5_sleep_life",
    }
    pr = d["personal_range"]
    assert pr["low"] < pr["high"]
    # 範囲は直近28回の平均 ± SD。現在値 - delta = 平均 なので中心が一致する
    mean_28 = d["ccs_score"] - d["delta_28ma"]
    assert (pr["low"] + pr["high"]) / 2 == pytest.approx(mean_28)
    # 発明されていた名前は返らない
    for ghost in ("ccs", "personal_range_low", "personal_range_high", "factors", "flags_list"):
        assert ghost not in d


def test_personal_range_matches_what_get_returns_for_the_player(client, player):
    _seed_history(client, player.id, 8)
    r = _post(client, player.id, 3, NEXT_DAY, {"X-Role": "admin"})
    posted = r.json()["data"]
    got = client.get(
        f"/api/conditions/{posted['id']}",
        headers={"X-Role": "player", "X-Player-Id": str(player.id)},
    ).json()["data"]
    assert got["personal_range"]["low"] == pytest.approx(posted["personal_range"]["low"])
    assert got["personal_range"]["high"] == pytest.approx(posted["personal_range"]["high"])
    assert got["factor_labels"] == posted["factor_labels"]


def test_fewer_than_7_history_gives_null_range_not_zero(client, player):
    _seed_history(client, player.id, 3)
    r = _post(client, player.id, 3, NEXT_DAY, {"X-Role": "admin"})
    d = r.json()["data"]
    assert d["personal_range"] is None
    assert d["n_28"] is None
    assert d["delta_28ma"] is None
    assert set(d["factor_labels"].values()) == {"insufficient_data"}


def test_flat_history_gives_no_range(client, player):
    """履歴が全て同値 (SD=0) では幅 0 の「平常レンジ」を作らない。"""
    base = date(2026, 1, 5)
    for i in range(8):
        r = _post(client, player.id, 3, (base + timedelta(days=7 * i)).isoformat(), {"X-Role": "admin"})
        assert r.status_code == 201
    d = _post(client, player.id, 3, NEXT_DAY, {"X-Role": "admin"}).json()["data"]
    assert d["personal_range"] is None


@pytest.mark.parametrize("role", ["coach", "analyst"])
def test_tier1_roles_do_not_get_ccs_derived_fields(client, player, role, monkeypatch):
    """personal_range / factor_labels は ccs_score・z_score 由来 = Tier 2。
    Tier 1 のロールには、他の Tier 2 項目と同様に出ない。"""
    _seed_history(client, player.id, 8)
    # チーム境界は本テストの対象外 (出力フィルタだけを見る)。
    monkeypatch.setattr("backend.utils.auth.can_access_player", lambda ctx, pid, db: True)
    r = _post(client, player.id, 3, NEXT_DAY, {"X-Role": role})
    assert r.status_code == 201, r.text
    d = r.json()["data"]
    for k in ("ccs_score", "delta_28ma", "n_28", "z_score", "personal_range", "factor_labels",
              "f1_physical", "total_score"):
        assert k not in d, k
    assert "validity_flag" in d


def test_player_submit_gets_range_and_labels(client, player):
    _seed_history(client, player.id, 8)
    r = _post(client, player.id, 3, NEXT_DAY, {"X-Role": "player", "X-Player-Id": str(player.id)})
    assert r.status_code == 201, r.text
    d = r.json()["data"]
    assert d["personal_range"]["low"] < d["personal_range"]["high"]
    assert "factor_labels" in d


def test_frontend_fixture_has_exactly_the_keys_of_a_real_response(client, player):
    """フロントの fixture (実応答の写し) が backend の実際のキー集合と一致すること。
    キーが増減したらここで落ちる = fixture を撮り直す合図。"""
    import json
    from pathlib import Path

    fx = json.loads(
        (Path(__file__).resolve().parents[2]
         / "src/components/condition/__tests__/fixtures/questionnaireSubmitResponse.json")
        .read_text(encoding="utf-8")
    )
    _seed_history(client, player.id, 8)
    admin = _post(client, player.id, 3, NEXT_DAY, {"X-Role": "admin"}).json()["data"]
    pl = _post(client, player.id, 3, (date(2026, 1, 5) + timedelta(days=7 * 21)).isoformat(),
               {"X-Role": "player", "X-Player-Id": str(player.id)}).json()["data"]
    assert set(fx["admin"]) == set(admin)
    assert set(fx["player"]) == set(pl)
    assert fx["admin"]["validity_flag"] in {"ok", "caution", "unreliable"}
