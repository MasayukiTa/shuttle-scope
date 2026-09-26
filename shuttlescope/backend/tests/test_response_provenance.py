from types import SimpleNamespace

from backend.analysis.response_meta import (
    build_input_provenance,
    build_response_meta,
)
from backend.routers import analysis_spine


def _rally(mode):
    return SimpleNamespace(annotation_mode=mode)


def _stroke(method, *, hit_zone=None, hit_zone_source=None):
    return SimpleNamespace(
        source_method=method,
        hit_zone=hit_zone,
        hit_zone_source=hit_zone_source,
    )


def test_input_provenance_counts_manual_assisted_corrected_and_cv_sources():
    rallies = [
        _rally("manual_record"),
        _rally("assisted_record"),
        _rally(None),
    ]
    strokes_by_rally = {
        1: [
            _stroke("manual", hit_zone="BL", hit_zone_source="cv"),
            _stroke("assisted", hit_zone="MC", hit_zone_source="manual"),
            _stroke("manual", hit_zone="NC", hit_zone_source="carried_over"),
        ],
        2: [
            _stroke("corrected"),
            _stroke(None, hit_zone="NR", hit_zone_source=None),
        ],
    }

    provenance = build_input_provenance(
        rallies,
        strokes_by_rally,
        uses_hit_zone=True,
    )

    assert provenance["schema_version"] == 1
    assert provenance["rallies"] == {
        "total": 3,
        "annotation_mode": {
            "manual_record": 1,
            "assisted_record": 1,
            "unknown": 1,
        },
    }
    assert provenance["strokes"] == {
        "total": 5,
        "source_method": {
            "manual": 2,
            "assisted": 1,
            "corrected": 1,
            "unknown": 1,
        },
    }
    assert provenance["hit_zones"] == {
        "total_with_value": 4,
        "source": {
            "manual": 1,
            "carried_over": 1,
            "cv": 1,
            "unknown": 1,
        },
    }
    assert provenance["has_cv_derived_strokes"] is True
    assert provenance["has_assisted_annotations"] is True
    assert provenance["has_corrected_annotations"] is True
    assert provenance["has_cv_hit_zones"] is True


def test_unknown_provenance_is_not_silently_treated_as_manual():
    provenance = build_input_provenance(
        [_rally(None)],
        {1: [_stroke(None, hit_zone="BL", hit_zone_source=None)]},
        uses_hit_zone=True,
    )

    assert provenance["rallies"]["annotation_mode"]["unknown"] == 1
    assert provenance["rallies"]["annotation_mode"]["manual_record"] == 0
    assert provenance["strokes"]["source_method"]["unknown"] == 1
    assert provenance["strokes"]["source_method"]["manual"] == 0
    assert provenance["hit_zones"]["source"]["unknown"] == 1
    assert provenance["hit_zones"]["source"]["manual"] == 0
    assert provenance["has_cv_derived_strokes"] is False


def test_response_meta_only_includes_provenance_when_caller_supplies_source_rows():
    match_only = build_response_meta("bayes_matchup", 2)
    assert "input_provenance" not in match_only

    provenance = build_input_provenance([], {})
    stroke_based = build_response_meta(
        "epv_state",
        0,
        input_provenance=provenance,
    )
    assert stroke_based["input_provenance"] == provenance


def test_epv_empty_response_still_declares_zero_input_provenance(monkeypatch):
    monkeypatch.setattr(
        analysis_spine,
        "_load_ctx_or_query",
        lambda *_args, **_kwargs: ([], {}, {}, {}, [], {}),
    )

    result = analysis_spine._epv_state_table_impl(None, player_id=1)

    provenance = result["meta"]["input_provenance"]
    assert provenance["rallies"]["total"] == 0
    assert provenance["strokes"]["total"] == 0
    assert provenance["has_cv_derived_strokes"] is False
    assert provenance["has_assisted_annotations"] is False
    assert "hit_zones" not in provenance
    assert "has_cv_hit_zones" not in provenance
