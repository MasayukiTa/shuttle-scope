"""fix/midrally-save-v3: /api/strokes/batch の途中保存 (replace_strokes) を検証する。

背景: 以前は同じ (set_id, rally_num) のラリーが既にあると打球を足さず already_saved を
返したため、ラリー途中に一部を送るとラリー終了時の全送信が捨てられ、途中以降の
ストロークが失われていた (PR 267 の欠陥)。replace_strokes=True では既存ラリーの
非削除ストロークを soft delete して送られたストロークを入れ直す。

ケース:
  - 途中 3 本 -> 最終 6 本で、サーバーの非削除ストロークが 6 本になる
  - 途中を同じ内容で 2 回送っても増えない (冪等)
  - 確定後に古い途中保存 (3 本) が遅れて着いても 6 本のまま (確定後に縮めない)
  - replace_strokes=False では従来どおり already_saved になる
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, Rally, Stroke, User
from backend.main import app
from backend.utils.jwt_utils import create_access_token


@pytest.fixture()
def game_set(db_session) -> GameSet:
    a = Player(name="midrally A", dominant_hand="R")
    b = Player(name="midrally B", dominant_hand="R")
    db_session.add_all([a, b])
    db_session.flush()
    m = Match(
        tournament="midrally test", tournament_level="practice", round="R1",
        date=date(2026, 11, 1), format="singles",
        player_a_id=a.id, player_b_id=b.id, result="unknown",
    )
    db_session.add(m)
    db_session.flush()
    gs = GameSet(match_id=m.id, set_num=1)
    db_session.add(gs)
    db_session.flush()
    db_session.commit()
    return gs


@pytest.fixture()
def client(db_session, game_set):
    app.dependency_overrides[get_db] = lambda: db_session
    match = db_session.get(Match, game_set.match_id)
    assert match is not None
    user = User(
        username=f"midrally-player-{match.player_a_id}",
        role="player",
        player_id=match.player_a_id,
        awaiting_admin_approval=False,
        consent_required=False,
        is_test=True,
    )
    db_session.add(user)
    db_session.commit()
    token = create_access_token(
        user_id=user.id,
        role="player",
        player_id=match.player_a_id,
        minutes=10,
    )
    c = TestClient(
        app,
        base_url="http://localhost",
        headers={"Authorization": f"Bearer {token}"},
    )
    yield c
    app.dependency_overrides.clear()


def _stroke(n: int) -> dict:
    return {
        "stroke_num": n,
        "player": "player_a" if n % 2 == 1 else "player_b",
        "shot_type": "clear",
        "source_method": "manual",
    }


def _body(set_id: int, count: int, *, replace: bool, final: bool,
          rally_num: int = 1, device: str | None = None) -> dict:
    rally = {
        "set_id": set_id,
        "rally_num": rally_num,
        "server": "player_a",
        "winner": "player_a",
        "end_type": "winner",
        "rally_length": count,
        "score_a_after": 1,
        "score_b_after": 0,
        "is_deuce": False,
        "annotation_mode": "manual_record",
    }
    if device is not None:
        rally["source_device_id"] = device
    return {
        "rally": rally,
        "strokes": [_stroke(i) for i in range(1, count + 1)],
        "replace_strokes": replace,
        "final": final,
    }


def _active_strokes(db_session, rally_id: int):
    return (
        db_session.query(Stroke)
        .filter(Stroke.rally_id == rally_id, Stroke.deleted_at.is_(None))
        .all()
    )


def test_midrally_3_then_final_6_results_in_6(client, db_session, game_set):
    # 途中保存 3 本
    r1 = client.post(
        "/api/strokes/batch", json=_body(game_set.id, 3, replace=True, final=False)
    )
    assert r1.status_code in (200, 201), r1.text
    rally_id = r1.json()["data"]["rally_id"]
    assert len(_active_strokes(db_session, rally_id)) == 3

    # 最終保存 6 本 (置き換え)
    r2 = client.post(
        "/api/strokes/batch", json=_body(game_set.id, 6, replace=True, final=True)
    )
    assert r2.status_code in (200, 201), r2.text
    assert r2.json()["data"]["rally_id"] == rally_id
    assert r2.json()["data"]["stroke_count"] == 6
    assert len(_active_strokes(db_session, rally_id)) == 6


def test_midrally_same_content_twice_does_not_grow(client, db_session, game_set):
    r1 = client.post(
        "/api/strokes/batch", json=_body(game_set.id, 3, replace=True, final=False)
    )
    assert r1.status_code in (200, 201), r1.text
    rally_id = r1.json()["data"]["rally_id"]

    r2 = client.post(
        "/api/strokes/batch", json=_body(game_set.id, 3, replace=True, final=False)
    )
    assert r2.status_code in (200, 201), r2.text
    # 同じ 3 本を置き換えても 3 本のまま (増えない)
    assert len(_active_strokes(db_session, rally_id)) == 3


def test_late_midrally_after_final_does_not_shrink(client, db_session, game_set):
    # 最終 6 本
    rf = client.post(
        "/api/strokes/batch", json=_body(game_set.id, 6, replace=True, final=True)
    )
    assert rf.status_code in (200, 201), rf.text
    rally_id = rf.json()["data"]["rally_id"]
    assert len(_active_strokes(db_session, rally_id)) == 6

    # 確定後に古い途中保存 (3 本, final=False) が遅れて着く -> 縮めない
    rlate = client.post(
        "/api/strokes/batch", json=_body(game_set.id, 3, replace=True, final=False)
    )
    assert rlate.status_code in (200, 201), rlate.text
    assert len(_active_strokes(db_session, rally_id)) == 6


def test_replace_false_keeps_already_saved(client, db_session, game_set):
    r1 = client.post(
        "/api/strokes/batch", json=_body(game_set.id, 3, replace=False, final=True)
    )
    assert r1.status_code in (200, 201), r1.text
    rally_id = r1.json()["data"]["rally_id"]

    # replace_strokes=False では従来どおり already_saved で打球を足し直さない
    r2 = client.post(
        "/api/strokes/batch", json=_body(game_set.id, 6, replace=False, final=True)
    )
    assert r2.status_code in (200, 201), r2.text
    assert r2.json()["data"]["rally_id"] == rally_id
    assert r2.json()["data"].get("already_saved") is True
    assert len(_active_strokes(db_session, rally_id)) == 3


def test_replace_rejected_from_different_device(client, db_session, game_set):
    # 端末 dev-A が最終 6 本で確定
    r1 = client.post(
        "/api/strokes/batch",
        json=_body(game_set.id, 6, replace=True, final=True, device="dev-A"),
    )
    assert r1.status_code in (200, 201), r1.text
    rally_id = r1.json()["data"]["rally_id"]
    assert len(_active_strokes(db_session, rally_id)) == 6

    # 別端末 dev-B が同じ (set_id, rally_num) を 3 本で置き換えようとする -> 拒否。
    # 既存ラリーを already_saved として返し、打球は 6 本のまま上書きしない。
    r2 = client.post(
        "/api/strokes/batch",
        json=_body(game_set.id, 3, replace=True, final=True, device="dev-B"),
    )
    assert r2.status_code in (200, 201), r2.text
    assert r2.json()["data"]["rally_id"] == rally_id
    assert r2.json()["data"].get("already_saved") is True
    assert len(_active_strokes(db_session, rally_id)) == 6
    db_session.expire_all()
    assert db_session.get(Rally, rally_id).source_device_id == "dev-A"


def test_replace_allowed_from_same_device(client, db_session, game_set):
    # 同じ端末 dev-A なら途中 3 本 -> 最終 6 本の置き換えが通る
    r1 = client.post(
        "/api/strokes/batch",
        json=_body(game_set.id, 3, replace=True, final=False, device="dev-A"),
    )
    assert r1.status_code in (200, 201), r1.text
    rally_id = r1.json()["data"]["rally_id"]

    r2 = client.post(
        "/api/strokes/batch",
        json=_body(game_set.id, 6, replace=True, final=True, device="dev-A"),
    )
    assert r2.status_code in (200, 201), r2.text
    assert r2.json()["data"]["rally_id"] == rally_id
    assert len(_active_strokes(db_session, rally_id)) == 6


def test_replace_allowed_when_existing_device_unknown(client, db_session, game_set):
    # 既存ラリーに device が無い (従来データ) 場合、今回の device 付き送信で置き換えを
    # 許可し、所有端末を刻む (以後その端末が所有者)。
    r1 = client.post(
        "/api/strokes/batch",
        json=_body(game_set.id, 3, replace=True, final=False),  # device 無し
    )
    assert r1.status_code in (200, 201), r1.text
    rally_id = r1.json()["data"]["rally_id"]
    db_session.expire_all()
    assert db_session.get(Rally, rally_id).source_device_id is None

    r2 = client.post(
        "/api/strokes/batch",
        json=_body(game_set.id, 6, replace=True, final=True, device="dev-A"),
    )
    assert r2.status_code in (200, 201), r2.text
    assert len(_active_strokes(db_session, rally_id)) == 6
    db_session.expire_all()
    assert db_session.get(Rally, rally_id).source_device_id == "dev-A"
