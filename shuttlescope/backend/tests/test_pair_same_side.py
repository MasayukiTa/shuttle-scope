"""ペア解析 3 系統 (pair_combined / partner_timeline / pair_playstyle) の回帰テスト (監査 #740 / #741)。

防ぐ事象:
  - 対戦相手同士 (A1 と B1) を「同一ペア」として取り込み、相手側の勝敗・打球をペアの値に混ぜる。
  - 真のペア (A1 + A2) でも、分担値が相方ではなく相手側主選手の打球で計算される。
  - 同じカード内で pair_combined は絞り込みに従い、partner_timeline は全期間のままになる。
"""
from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.db.database import get_db
from backend.db.models import GameSet, Match, Player, Rally, Stroke
from backend.main import app
from backend.utils.jwt_utils import create_access_token


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


def _headers():
    tok = create_access_token(user_id=99, role="admin", player_id=None, team_name="T", team_id=9101)
    return {"Authorization": f"Bearer {tok}"}


def _player(db, name):
    p = Player(name=name, dominant_hand="R")
    db.add(p)
    db.flush()
    return p


def _doubles_match(db, a1, a2, b1, b2, d, level="IC", result="win"):
    """A1+A2 (A 側) 対 B1+B2 (B 側)。1 セット 2 ラリー。

    ラリー 1 (A 側勝ち): A1 smash(NL) / B1 clear(BC) / A2 smash(NC)
    ラリー 2 (B 側勝ち): A1 lift(BL)   / B1 drop(BC)  / B2 drop(BC)
    """
    m = Match(
        tournament="t", tournament_level=level, round="r", date=d, format="womens_doubles",
        player_a_id=a1.id, partner_a_id=a2.id, player_b_id=b1.id, partner_b_id=b2.id,
        result=result, annotation_status="complete", annotation_progress=1.0,
    )
    db.add(m)
    db.flush()
    gs = GameSet(match_id=m.id, set_num=1, winner="player_a", score_a=21, score_b=15)
    db.add(gs)
    db.flush()
    plan = [
        ("player_a", [("player_a", "smash", "NL"), ("player_b", "clear", "BC"), ("partner_a", "smash", "NC")]),
        ("player_b", [("player_a", "lift", "BL"), ("player_b", "drop", "BC"), ("partner_b", "drop", "BC")]),
    ]
    for i, (winner, strokes) in enumerate(plan, start=1):
        r = Rally(
            set_id=gs.id, rally_num=i, server="player_a", winner=winner,
            end_type="forced_error", rally_length=len(strokes),
            score_a_after=0, score_b_after=0, annotation_mode="manual_record",
        )
        db.add(r)
        db.flush()
        for n, (who, shot, zone) in enumerate(strokes, start=1):
            db.add(Stroke(rally_id=r.id, stroke_num=n, player=who, shot_type=shot, land_zone=zone))
    db.flush()
    return m


@pytest.fixture
def four(db_session):
    a1 = _player(db_session, "A1")
    a2 = _player(db_session, "A2")
    b1 = _player(db_session, "B1")
    b2 = _player(db_session, "B2")
    _doubles_match(db_session, a1, a2, b1, b2, date(2026, 1, 10))
    db_session.commit()
    return a1, a2, b1, b2


def _get(client, path, **params):
    resp = client.get(f"/api{path}", params=params, headers=_headers())
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestOpponentsAreNotAPair:
    def test_pair_combined_has_no_shared_match_for_opponents(self, client, four):
        a1, _a2, b1, _b2 = four
        body = _get(client, "/analysis/pair_combined", player_a_id=a1.id, player_b_id=b1.id)
        d = body["data"]
        assert d["pair_match_count"] == 0 and d["shared_matches"] == []
        assert d["pair_win_rate"] is None
        assert d["stroke_share"] == {"player_a": None, "player_b": None}
        assert body["meta"]["sample_size"] == 0

    def test_partner_timeline_has_no_point_for_opponents(self, client, four):
        a1, _a2, b1, _b2 = four
        body = _get(client, "/analysis/partner_timeline", player_id=a1.id, partner_id=b1.id)
        assert body["data"]["points"] == [] and body["data"]["overall_win_rate"] is None
        assert body["meta"]["sample_size"] == 0

    def test_pair_playstyle_is_unknown_for_opponents(self, client, four):
        a1, _a2, b1, _b2 = four
        body = _get(client, "/analysis/pair_playstyle", player_a_id=a1.id, player_b_id=b1.id)
        assert body["data"]["playstyle_en"] == "unknown"
        assert body["meta"]["sample_size"] == 0


class TestTruePairUsesOnlyTheirOwnStrokes:
    def test_pair_combined_counts_only_the_two_slots(self, client, four):
        a1, a2, _b1, _b2 = four
        body = _get(client, "/analysis/pair_combined", player_a_id=a1.id, player_b_id=a2.id)
        d = body["data"]
        assert d["pair_match_count"] == 1
        assert d["pair_win_rate"] == 1.0
        # A1 は smash, lift の 2 打、A2 は smash の 1 打。相手側 (B1/B2) の 3 打は入らない
        assert d["stroke_share"] == {"player_a": 0.667, "player_b": 0.333}
        assert d["common_win_shot"] == "smash"
        # 失点ラリーのペアの打球は A1 の lift のみ (相手の drop は入らない)
        assert d["common_loss_pattern"] == "lift"

    def test_pair_combined_for_the_opposing_pair_is_seen_from_their_side(self, client, four):
        _a1, _a2, b1, b2 = four
        d = _get(client, "/analysis/pair_combined", player_a_id=b1.id, player_b_id=b2.id)["data"]
        assert d["pair_match_count"] == 1
        # Match.result は A 側視点。B 側のペアにとっては負け
        assert d["pair_win_rate"] == 0.0
        assert d["stroke_share"] == {"player_a": 0.667, "player_b": 0.333}

    def test_pair_playstyle_ignores_the_opponents_zones(self, client, four):
        a1, a2, _b1, _b2 = four
        d = _get(client, "/analysis/pair_playstyle", player_a_id=a1.id, player_b_id=a2.id)["data"]
        # ペアの着地点は NL / NC / BL。相手の BC 3 打が混ざると後衛主体になる
        assert d["playstyle_en"] == "net_dominant"
        assert d["metrics"]["net_zone_rate"] == pytest.approx(2 / 3, abs=0.01)
        assert d["metrics"]["back_zone_rate"] == pytest.approx(1 / 3, abs=0.01)


class TestTimelineFollowsTheSameFilter:
    def test_partner_timeline_applies_the_card_filter(self, client, db_session):
        a1 = _player(db_session, "A1")
        a2 = _player(db_session, "A2")
        b1 = _player(db_session, "B1")
        b2 = _player(db_session, "B2")
        _doubles_match(db_session, a1, a2, b1, b2, date(2025, 3, 1), level="IC", result="loss")
        _doubles_match(db_session, a1, a2, b1, b2, date(2026, 3, 1), level="IC", result="win")
        db_session.commit()
        q = {"date_from": "2026-01-01"}
        top = _get(client, "/analysis/pair_combined", player_a_id=a1.id, player_b_id=a2.id, **q)
        tl = _get(client, "/analysis/partner_timeline", player_id=a1.id, partner_id=a2.id, **q)
        # 同じ絞り込みで、上段と推移が同じ試合集合を数える
        assert top["data"]["pair_match_count"] == 1
        assert [p["match_id"] for p in tl["data"]["points"]] == top["data"]["shared_matches"]
        assert tl["data"]["overall_win_rate"] == top["data"]["pair_win_rate"] == 1.0
        assert tl["meta"]["population"] == {"n_matches": 1, "filter_applied": True}
        assert top["meta"]["population"] == {"n_matches": 1, "filter_applied": True}
        # 絞り込みなしは 2 試合
        all_tl = _get(client, "/analysis/partner_timeline", player_id=a1.id, partner_id=a2.id)
        assert len(all_tl["data"]["points"]) == 2
        assert all_tl["meta"]["population"] == {"n_matches": 2, "filter_applied": False}

    def test_result_filter_is_the_pairs_result_not_the_stored_a_side_result(self, client, four):
        _a1, _a2, b1, b2 = four
        # 保存された result は A 側の勝ち。B 側ペアの "win" は 0 試合、"loss" は 1 試合
        won = _get(client, "/analysis/pair_combined", player_a_id=b1.id, player_b_id=b2.id, result="win")
        lost = _get(client, "/analysis/pair_combined", player_a_id=b1.id, player_b_id=b2.id, result="loss")
        assert won["data"]["pair_match_count"] == 0
        assert lost["data"]["pair_match_count"] == 1
