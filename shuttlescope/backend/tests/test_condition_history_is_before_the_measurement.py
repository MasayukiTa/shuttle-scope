"""体調質問票の「本人内変動」は、その測定より前の履歴だけを使う。

履歴を measured_at で絞っていなかったので、日付をさかのぼって入力すると、
「前回」がいちばん新しい (=未来の) 測定になり、前回差・3 回移動平均・急変判定が
未来の値と比べて計算されていた。
"""
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
    p = Player(name="履歴テスト選手", dominant_hand="R")
    db_session.add(p)
    db_session.commit()
    return p


def _mid():
    return {qid: 3 for qid in WEEKLY_REQUIRED_IDS}


def _best():
    """CCS が高くなる回答 (逆転項目は 5、それ以外は 1)。ccs=160。"""
    return {qid: (1 if qid.startswith("V") else 5 if qid in REVERSED_ITEMS else 1) for qid in WEEKLY_REQUIRED_IDS}


def _submit(client, pid, responses, when):
    r = client.post("/api/conditions/questionnaire",
                    json={"player_id": pid, "measured_at": when, "condition_type": "weekly", "responses": responses},
                    headers={"X-Role": "admin"})
    r.raise_for_status()
    return r.json()["data"]


def test_a_backdated_entry_is_compared_with_the_earlier_one_not_the_later(client, player):
    _submit(client, player.id, _mid(), "2026-04-01")      # ccs=80
    _submit(client, player.id, _best(), "2026-04-15")     # ccs=160 (後の測定)
    # 4/08 をさかのぼって入力 (ccs=80)。前回は 4/01 (80) なので差は 0。4/15 (160) と比べると -80 になる
    d = _submit(client, player.id, _mid(), "2026-04-08")
    assert d["delta_prev"] == 0.0
    assert "ccs_sudden_change" not in str(d["validity_flags_json"])


def test_the_chronological_case_is_unchanged(client, player):
    _submit(client, player.id, _mid(), "2026-04-10")
    d = _submit(client, player.id, _best(), "2026-04-14")
    assert d["delta_prev"] == 80.0
    assert "ccs_sudden_change" in str(d["validity_flags_json"])


def test_the_first_entry_has_no_history(client, player):
    _submit(client, player.id, _best(), "2026-04-15")     # 後の測定が先に入っている
    d = _submit(client, player.id, _mid(), "2026-04-01")  # それより前には何もない
    assert d["delta_prev"] is None
