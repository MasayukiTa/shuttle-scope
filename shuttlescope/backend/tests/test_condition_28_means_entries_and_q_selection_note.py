"""S-15 / S-13 の正直さの回帰テスト。

S-15: 質問票の「28日平均」(delta_28ma / mean_28 / sd_28) は**日数ではなく直近28件の記録**の平均。
      計算は変えず、実際に平均した件数 n_28 を返す。算出なし (件数 0) は 0.0 でなく null。
S-13: Q値モデルの「最善手」は信頼できるセルの最大値で、多重比較の補正は無い。
      計算は変えず、選択バイアスの注意書き (selection_note) を返す。
"""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.analysis.condition_questions import REVERSED_ITEMS, WEEKLY_REQUIRED_IDS
from backend.analysis.condition_scoring import calc_deviation
from backend.analysis.q_value_model import (
    SELECTION_NOTE_EN,
    SELECTION_NOTE_JA,
    compute_q_values,
    summarize_best_actions,
)
from backend.db.database import get_db
from backend.db.models import Condition, Player
from backend.main import app



# ── S-15: calc_deviation ────────────────────────────────────────────────────

class TestDeviationCountsEntriesNotDays:
    def test_fewer_than_7_entries_is_null_not_zero(self):
        r = calc_deviation(10.0, [9.0, 11.0, 10.0])
        assert r["n_28"] is None
        assert r["delta_28ma"] is None
        assert r["mean_28"] is None

    def test_no_history_is_null_not_zero(self):
        r = calc_deviation(10.0, [])
        assert r["n_28"] is None and r["delta_28ma"] is None

    def test_n_is_the_number_of_entries_actually_averaged(self):
        hist = [float(i) for i in range(1, 10)]  # 9 件
        r = calc_deviation(20.0, hist)
        assert r["n_28"] == 9
        assert r["mean_28"] == sum(hist) / 9
        assert r["delta_28ma"] == 20.0 - sum(hist) / 9

    def test_window_is_the_last_28_entries_regardless_of_dates(self):
        # 40 件あっても使うのは末尾 28 件 (日数は見ていない)
        hist = [0.0] * 12 + [10.0] * 28
        r = calc_deviation(10.0, hist)
        assert r["n_28"] == 28
        assert r["mean_28"] == 10.0
        assert r["delta_28ma"] == 0.0

    def test_docstring_does_not_claim_days(self):
        doc = calc_deviation.__doc__
        assert "28日平均" not in doc
        assert "記録の件数" in doc


# ── S-15: API ───────────────────────────────────────────────────────────────

@pytest.fixture()
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture()
def player(db_session):
    p = Player(name="28回テスト選手", dominant_hand="R")
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


def _submit(client, pid, v, when):
    r = client.post(
        "/api/conditions/questionnaire",
        json={"player_id": pid, "measured_at": when, "condition_type": "weekly",
              "responses": _responses(v)},
        headers={"X-Role": "admin"},
    )
    r.raise_for_status()
    return r.json()["data"]


def test_submit_reports_how_many_entries_were_averaged(client, player):
    base = date(2026, 1, 5)
    got = []
    for i in range(9):
        got.append(_submit(client, player.id, 3 if i % 2 == 0 else 5, (base + timedelta(days=7 * i)).isoformat()))
    # 先頭 7 件は履歴が 0..6 件 → 算出なし。null であり 0 ではない
    for d in got[:7]:
        assert d["delta_28ma"] is None
        assert d["n_28"] is None
    # 8 件目は履歴 7 件、9 件目は 8 件
    assert got[7]["delta_28ma"] is not None and got[7]["n_28"] == 7
    assert got[8]["n_28"] == 8


def test_get_reports_n_and_caps_at_28(client, player, db_session):
    base = date(2025, 1, 1)
    for i in range(31):
        c = Condition(
            player_id=player.id,
            measured_at=base + timedelta(days=7 * i),
            condition_type="weekly",
            ccs_score=80.0 + (i % 5),
            delta_28ma=1.0 if i >= 7 else None,
        )
        db_session.add(c)
        db_session.flush()
    db_session.commit()
    rows = (db_session.query(Condition).filter(Condition.player_id == player.id)
            .order_by(Condition.measured_at).all())
    by_idx = {i: r for i, r in enumerate(rows)}

    r30 = client.get(f"/api/conditions/{by_idx[30].id}", headers={"X-Role": "admin"})
    assert r30.status_code == 200
    assert r30.json()["data"]["n_28"] == 28  # 履歴 30 件でも 28 で頭打ち

    r7 = client.get(f"/api/conditions/{by_idx[7].id}", headers={"X-Role": "admin"})
    assert r7.json()["data"]["n_28"] == 7

    r3 = client.get(f"/api/conditions/{by_idx[3].id}", headers={"X-Role": "admin"})
    assert r3.json()["data"]["delta_28ma"] is None
    assert r3.json()["data"]["n_28"] is None


# ── S-13: selection note ────────────────────────────────────────────────────

def _fake_rallies(n_per_shot=40):
    """同じ state に 2 種類のショット (n_per_shot 回ずつ) を作る。"""
    rallies, strokes = [], {}
    rid = 0
    for shot, wins in (("smash", 25), ("clear", 20)):
        for k in range(n_per_shot):
            rid += 1
            rallies.append(SimpleNamespace(
                id=rid, set_id=1, score_a_before=3, score_b_before=3,
                rally_length=4, server="player_a", winner="player_a" if k < wins else "player_b",
            ))
            strokes[rid] = [SimpleNamespace(stroke_num=1, player="player_a", shot_type=shot)]
    return rallies, strokes


def _q():
    rallies, strokes = _fake_rallies()
    return compute_q_values(
        rallies=rallies, strokes_by_rally=strokes,
        role_by_match={1: "player_a"}, set_to_match={1: 1}, set_num_by_set={1: 1},
    )


def test_q_value_result_carries_the_selection_caveat():
    res = _q()
    assert res["best_actions"], "テストデータで最善手が出ること"
    assert res["selection_note"] == SELECTION_NOTE_JA
    assert res["selection_note_en"] == SELECTION_NOTE_EN
    assert "最大値" in SELECTION_NOTE_JA and "実際より良く見える" in SELECTION_NOTE_JA
    for b in res["best_actions"].values():
        assert b["selection_note"] == SELECTION_NOTE_JA
    for row in summarize_best_actions(res["best_actions"]):
        assert row["selection_note"] == SELECTION_NOTE_JA


def test_the_selection_note_does_not_change_the_math():
    res = _q()
    best = next(iter(res["best_actions"].values()))
    assert best["best_action"] == "smash"  # 勝率 25/40 > 20/40 (従来どおり最大値)
    assert best["n_reliable_actions"] == 2


def test_best_actions_endpoint_returns_the_note(client, player):
    r = client.get(f"/api/analysis/state_best_actions?player_id={player.id}", headers={"X-Role": "admin"})
    assert r.status_code == 200
    body = r.json()
    assert body["selection_note"] == SELECTION_NOTE_JA
    assert body["selection_note_en"] == SELECTION_NOTE_EN
