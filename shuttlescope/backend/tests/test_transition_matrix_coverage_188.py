from backend.routers import analysis_advanced


def test_transition_matrix_exposes_rally_coverage_fields_when_empty(monkeypatch):
    """監査 #188: 遷移行列の data にカバレッジ
    rallies_in_scope / rallies_total を常に含める。
    matches が空のときは db を使わず空ブロックを返すため db=None で呼べる。
    """
    monkeypatch.setattr(analysis_advanced, "_get_player_matches", lambda *a, **k: [])

    resp = analysis_advanced.get_shot_transition_matrix(player_id=1, db=None)

    data = resp["data"]
    assert "rallies_in_scope" in data
    assert "rallies_total" in data
    assert data["rallies_in_scope"] == 0
    assert data["rallies_total"] == 0
    # 空ケースでは対象が全体を超えないことだけは常に成立。
    assert data["rallies_in_scope"] <= data["rallies_total"] or data["rallies_total"] == 0
