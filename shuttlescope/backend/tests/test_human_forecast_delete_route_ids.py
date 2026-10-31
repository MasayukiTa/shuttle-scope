from __future__ import annotations

import pytest

from backend.db.database import get_db
from backend.main import app
from test_human_forecast_delete_authz import (
    _client, _headers, _is_deleted, _make_forecast, _seed,
)


@pytest.mark.parametrize("forecast_id", [9902, 9999])
def test_forecast_delete_uses_forecast_id_not_match_id(db_session, forecast_id):
    team_a, team_b, own_match, foreign_match = _seed(db_session)
    # 9902 is an unrelated team's match; 9999 is not a match at all.
    assert own_match.id != forecast_id
    assert foreign_match.id == 9902
    _make_forecast(db_session, fid=forecast_id, match_id=own_match.id,
                   player_id=9701, team_id=team_a.id, creator_user_id=9801)
    creator = _headers(user_id=9801, role="coach", team_id=team_a.id, team_name=team_a.name)
    other = _headers(user_id=9802, role="coach", team_id=team_a.id, team_name=team_a.name)
    foreign = _headers(user_id=9803, role="coach", team_id=team_b.id, team_name=team_b.name)
    app.dependency_overrides[get_db] = lambda: db_session
    try:
        client = _client()
        url = f"/api/prediction/human_forecast/{forecast_id}"
        listing = f"/api/prediction/human_forecast/{own_match.id}"
        response = client.get(listing, headers=creator)
        assert response.status_code == 200, response.text
        assert [item["id"] for item in response.json()["data"]] == [forecast_id]
        response = client.get(listing, headers=foreign)
        assert response.status_code == 404, response.text
        response = client.delete(url, headers=other)
        assert response.status_code == 403, response.text
        assert not _is_deleted(db_session, forecast_id)
        response = client.delete(url, headers=creator)
        assert response.status_code == 200, response.text
        assert _is_deleted(db_session, forecast_id)
    finally:
        app.dependency_overrides.clear()
