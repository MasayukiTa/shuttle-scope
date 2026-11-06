from backend.routers import analysis_stable


def test_descriptive_exposes_total_strokes_from_rally_length_even_when_empty(monkeypatch):
    """監査 #187: descriptive の data に、ラリー長合計由来の
    総球数 total_strokes_from_rally_length を常に公開する。
    input_provenance.strokes.total（ストローク直接入力）とは別指標。
    matches が空のときは db を使わず短絡するため db=None で呼べる。
    """
    monkeypatch.setattr(analysis_stable, "_get_player_matches", lambda *a, **k: [])

    resp = analysis_stable.get_descriptive(player_id=1, db=None)

    data = resp["data"]
    assert "total_strokes_from_rally_length" in data
    assert data["total_strokes_from_rally_length"] == 0
    # 空ケースでは histogram も空、合計も 0。総球数は
    # 常に Σ(length*count) と一致する。
    hist = data["rally_length_histogram"]
    assert sum(row["length"] * row["count"] for row in hist) == data["total_strokes_from_rally_length"]


def test_descriptive_total_strokes_is_distinct_from_provenance_strokes(monkeypatch):
    """総球数フィールドと provenance.strokes.total が別キーであることを固定する。"""
    monkeypatch.setattr(analysis_stable, "_get_player_matches", lambda *a, **k: [])

    resp = analysis_stable.get_descriptive(player_id=1, db=None)

    prov = resp["meta"]["input_provenance"]
    # 別名・別箇所であること（混同しない）
    assert "total_strokes_from_rally_length" not in prov
    assert prov["strokes"]["total"] == 0
