"""first_return_analysis の player 向け勝率非表示 (監査 #949)。

プロダクト規則: player に生の勝率を見せない。画面 (Advanced を隠す) だけでなく、
直接 API と包括レポートの両方で、同じ単一定義 (PLAYER_RESPONSE_RULES) を通ること。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.db.models import GameSet, Rally, Stroke
from backend.main import app
from backend.tests.test_player_output_privacy import (  # noqa: F401  (fixtures)
    _OTHER_ROLES, _headers, _player_h, _walk_keys, world,
)
from backend.utils.player_response_sanitiser import (
    PLAYER_RESPONSE_RULES, keys_to_drop, sanitize_for_player,
)

_FR_PATH = "/api/analysis/first_return_analysis"


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def receiver_world(world):
    """本人 (player_a) がレシーバーになるラリーを足す。world は本人が常にサーバーなので、
    そのままでは first_return が空になり、漏えいを検出できない。"""
    db = world["db"]
    s2 = GameSet(match_id=world["match"].id, set_num=2, winner="player_a", score_a=21, score_b=15)
    db.add(s2)
    db.flush()
    for i in range(1, 5):
        r = Rally(
            set_id=s2.id, rally_num=i, server="player_b",
            winner="player_a" if i % 2 else "player_b",
            end_type="smash_winner", rally_length=2, score_a_after=i, score_b_after=0,
        )
        db.add(r)
        db.flush()
        db.add(Stroke(rally_id=r.id, stroke_num=1, player="player_b", shot_type="short_service",
                      hit_zone="BL", land_zone="BR"))
        db.add(Stroke(rally_id=r.id, stroke_num=2, player="player_a", shot_type="clear",
                      hit_zone="BR", land_zone="BL"))
    db.commit()
    return world


class TestFirstReturnDirectApi:
    def test_player_direct_call_has_no_win_rate(self, receiver_world, client):
        w = receiver_world
        r = client.get(f"{_FR_PATH}?player_id={w['own'].id}", headers=_player_h(w))
        assert r.status_code == 200, r.text
        body = r.json()
        zones = body["data"]["zones"]
        assert zones, "レシーバーのラリーがあるので zones は空でない"
        assert not (_walk_keys(body) & {"win_rate", "win_rate_basis"})
        # 件数・出現率・サンプル数 / 信頼度メタは残る (n を失わない)
        assert all("count" in z and "freq_rate" in z for z in zones)
        assert body["data"]["sample_size"] == 4
        assert body["meta"]["sample_size"] == 4 and "confidence" in body["meta"]

    @pytest.mark.parametrize("role", _OTHER_ROLES)
    def test_other_roles_still_get_win_rate(self, receiver_world, client, role):
        w = receiver_world
        r = client.get(f"{_FR_PATH}?player_id={w['own'].id}", headers=_headers(role))
        assert r.status_code == 200, r.text
        zones = r.json()["data"]["zones"]
        assert zones and all("win_rate" in z for z in zones)


class TestFirstReturnComprehensive:
    def test_player_report_has_no_win_rate_in_first_return(self, receiver_world, client):
        w = receiver_world
        r = client.get(f"/api/reports/comprehensive?player_id={w['own'].id}", headers=_player_h(w))
        assert r.status_code == 200, r.text
        sec = r.json()["sections"]["first_return"]
        inner = sec["data"]["data"]
        assert inner["zones"], "中身は残る (件数と出現率)"
        assert not (_walk_keys(sec) & {"win_rate", "win_rate_basis"})
        assert sec["data"]["meta"]["sample_size"] == 4

    @pytest.mark.parametrize("role", _OTHER_ROLES)
    def test_other_roles_report_unchanged(self, receiver_world, client, role):
        w = receiver_world
        r = client.get(f"/api/reports/comprehensive?player_id={w['own'].id}", headers=_headers(role))
        assert r.status_code == 200, r.text
        zones = r.json()["sections"]["first_return"]["data"]["data"]["zones"]
        assert zones and all("win_rate" in z for z in zones)


class TestSingleDefinition:
    def test_rule_is_declared_once_and_drops_win_rate(self):
        assert "analysis.first_return_analysis" in [r.name for r in PLAYER_RESPONSE_RULES]
        assert "win_rate" in keys_to_drop(_FR_PATH)

    def test_report_view_and_direct_view_are_the_same_transform(self):
        from backend.utils.player_privacy import PLAYER_COMPREHENSIVE_ALLOWED_SECTIONS
        inner = {"zones": [{"zone": "BL", "count": 3, "win_rate": 0.5, "freq_rate": 1.0}],
                 "top_zones": ["BL"], "sample_size": 3}
        assert PLAYER_COMPREHENSIVE_ALLOWED_SECTIONS["first_return"](inner) == \
            sanitize_for_player(_FR_PATH, inner)
        assert "win_rate" not in _walk_keys(sanitize_for_player(_FR_PATH, inner))
