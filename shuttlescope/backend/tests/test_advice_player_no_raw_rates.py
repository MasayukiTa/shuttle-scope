"""選手ロールの助言カードに、生のラリー勝率・差・優劣を示す severity を出さない。

製品ルール: 選手向け画面には生の勝率を見せない。管理者向けには従来どおり出す。
"""
import json
from dataclasses import asdict, is_dataclass

import pytest

from backend.db.models import Match
from backend.services import advice
from backend.tests.test_analysis_doubles_perspective_symmetry import _build, _plan
from backend.utils.auth import AuthCtx


def _ctx(role):
    return AuthCtx(role=role, player_id=None, user_id=1, team_name=None, team_id=None)


def _text_of(card):
    def default(o):
        if is_dataclass(o):
            return asdict(o)
        return str(o)
    return json.dumps(card, default=default, ensure_ascii=False)


@pytest.fixture()
def world(db_session):
    plan = _plan(seed=5, n_sets=3, n_rallies=30)
    tx = _build(db_session, plan)
    db_session.commit()
    m = db_session.query(Match).filter(Match.player_a_id == tx.id).one()
    return db_session, tx, m


def test_post_match_card_hides_rates_from_player(world):
    db, tx, m = world
    admin = _text_of(advice.advice_post_match_save(db, tx.id, m.id, _ctx("admin")))
    player = _text_of(advice.advice_post_match_save(db, tx.id, m.id, _ctx("player")))
    assert "ラリー勝率" in admin  # 管理者は従来どおり
    assert "勝率" not in player
    assert "pp" not in player
    assert "positive" not in player


def test_growth_card_hides_rates_from_player(world):
    db, tx, _ = world
    player = _text_of(advice.advice_growth_timeline(db, tx.id, _ctx("player")))
    assert "勝率" not in player
    assert "pp" not in player
