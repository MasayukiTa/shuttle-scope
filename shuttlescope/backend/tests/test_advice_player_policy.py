from backend.services import advice
from backend.utils.auth import AuthCtx


def _ctx(role: str) -> AuthCtx:
    return AuthCtx(role=role, user_id=1, player_id=1, team_id=1, team_name="T")


def _fake_window(_db, _player_id: int, days: int):
    if days == 30:
        return {
            "match_count": 5, "rally_count": 100, "wins": 60, "losses": 40,
            "win_rate": 0.60, "primary_shot": ("smash", 50, 0.50),
            "from_date": "2026-08-28", "to_date": "2026-09-27",
        }
    return {
        "match_count": 10, "rally_count": 200, "wins": 110, "losses": 90,
        "win_rate": 0.55, "primary_shot": ("smash", 100, 0.50),
        "from_date": "2026-07-29", "to_date": "2026-09-27",
    }


def test_player_dashboard_advice_hides_raw_win_rate_and_delta(monkeypatch):
    monkeypatch.setattr(advice, "_gather_window", _fake_window)
    out = advice.advice_dashboard_overview(object(), 1, _ctx("player"))
    text = out["advice"]["text"]
    assert "60.0%" not in text
    assert "10.0pp" not in text


def test_coach_dashboard_advice_keeps_raw_win_rate_and_delta(monkeypatch):
    monkeypatch.setattr(advice, "_gather_window", _fake_window)
    out = advice.advice_dashboard_overview(object(), 1, _ctx("coach"))
    text = out["advice"]["text"]
    assert "60.0%" in text
    assert "10.0pp" in text
