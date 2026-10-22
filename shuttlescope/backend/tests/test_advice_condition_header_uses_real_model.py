"""advice_condition_header は実在する Condition モデルを読む (監査 #73)。

以前は存在しない DailyCondition を import して ImportError になり、
常に「体調モデルが利用できません」を返していた。
"""
from datetime import date, timedelta
from types import SimpleNamespace

from backend.services import advice
from backend.utils.auth import AuthCtx


def _ctx() -> AuthCtx:
    return AuthCtx(role="coach", user_id=1, player_id=1, team_id=1, team_name="T")


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_a, **_k):
        return self

    def order_by(self, *_a, **_k):
        return self

    def all(self):
        return list(self._rows)


class _Db:
    def __init__(self, rows):
        self._rows = rows

    def query(self, _model):
        return _Query(self._rows)


def _row(days_ago: int, sleep=None, fatigue=None):
    return SimpleNamespace(
        measured_at=date.today() - timedelta(days=days_ago),
        hooper_sleep=sleep,
        hooper_fatigue=fatigue,
    )


def test_enough_records_give_an_ok_card_not_model_unavailable():
    rows = [_row(1, sleep=3, fatigue=4), _row(3), _row(5)]
    out = advice.advice_condition_header(_Db(rows), 1, _ctx())
    assert out["status"] == "ok"
    text = out["advice"]["text"]
    assert "体調モデルが利用できません" not in text
    assert "3 件" in text
    assert "Hooper 睡眠 3" in text
    assert "Hooper 疲労 4" in text
    assert out["advice"]["basis"]["sample_size"] == {"entries": 3}


def test_too_few_records_say_how_many_there_are():
    out = advice.advice_condition_header(_Db([_row(1)]), 1, _ctx())
    assert out["status"] == "insufficient_data"
    assert "1 件" in out["reason"]
    assert "体調モデルが利用できません" not in out["reason"]
