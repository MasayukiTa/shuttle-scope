"""
response_meta.py — API レスポンス共通 meta フィールドビルダー

使い方:
    from backend.analysis.response_meta import build_response_meta

    @router.get("/analysis/foo")
    def get_foo(player_id: int, ...):
        data = compute_foo(...)
        sample_size = len(data)
        meta = build_response_meta("epv", sample_size)
        return {"success": True, "data": data, "meta": meta}
"""
from __future__ import annotations

from collections.abc import Mapping

from backend.analysis.analysis_registry import (
    get_analysis_meta,
    TIER_OUTPUT_POLICY,
)


def _bucket(value: object, known: tuple[str, ...]) -> str:
    raw = str(value or "").strip().lower()
    return raw if raw in known else "unknown"


def build_input_provenance(
    rallies: list | tuple | None = None,
    strokes_by_rally: Mapping | None = None,
    *,
    strokes: list | tuple | None = None,
    uses_hit_zone: bool = False,
) -> dict:
    """解析入力に実際に含まれた annotation / CV 由来の内訳を要約する。

    ID や生データは返さず count のみを返す。legacy 行の NULL や未知値は
    unknown に畳み、来歴が分からないデータを manual と誤認しない。

    source_method == "assisted" は C-5 と同じ定義で「CV 候補を適用した打球」。
    hit_zone の来歴は、その解析が hit_zone を実際に使う場合だけ載せる。
    """
    rally_rows = list(rallies or [])
    if strokes is not None:
        stroke_rows = list(strokes)
    else:
        stroke_rows = [
            stroke
            for rows in (strokes_by_rally or {}).values()
            for stroke in rows
        ]

    rally_modes = {"manual_record": 0, "assisted_record": 0, "unknown": 0}
    for rally in rally_rows:
        mode = _bucket(
            getattr(rally, "annotation_mode", None),
            ("manual_record", "assisted_record"),
        )
        rally_modes[mode] += 1

    stroke_methods = {"manual": 0, "assisted": 0, "corrected": 0, "unknown": 0}
    hit_zone_sources = {"manual": 0, "carried_over": 0, "cv": 0, "unknown": 0}
    hit_zone_total = 0

    for stroke in stroke_rows:
        method = _bucket(
            getattr(stroke, "source_method", None),
            ("manual", "assisted", "corrected"),
        )
        stroke_methods[method] += 1

        if uses_hit_zone and getattr(stroke, "hit_zone", None) is not None:
            hit_zone_total += 1
            zone_source = _bucket(
                getattr(stroke, "hit_zone_source", None),
                ("manual", "carried_over", "cv"),
            )
            hit_zone_sources[zone_source] += 1

    provenance = {
        "schema_version": 1,
        "rallies": {
            "total": len(rally_rows),
            "annotation_mode": rally_modes,
        },
        "strokes": {
            "total": len(stroke_rows),
            "source_method": stroke_methods,
        },
        "has_cv_derived_strokes": stroke_methods["assisted"] > 0,
        "has_assisted_annotations": (
            rally_modes["assisted_record"] > 0 or stroke_methods["assisted"] > 0
        ),
        "has_corrected_annotations": stroke_methods["corrected"] > 0,
    }

    if uses_hit_zone:
        provenance["hit_zones"] = {
            "total_with_value": hit_zone_total,
            "source": hit_zone_sources,
        }
        provenance["has_cv_hit_zones"] = hit_zone_sources["cv"] > 0

    return provenance


def build_response_meta(
    analysis_type: str,
    sample_size: int,
    *,
    input_provenance: dict | None = None,
) -> dict:
    """analysis_type と実際のサンプルサイズから meta dict を構築する。"""
    entry = get_analysis_meta(analysis_type)
    tier = entry["tier"]
    min_samples = entry["min_recommended_sample"]
    policy = TIER_OUTPUT_POLICY.get(tier, TIER_OUTPUT_POLICY["research"])

    if min_samples > 0:
        confidence_level = round(min(1.0, sample_size / min_samples), 3)
    else:
        confidence_level = 1.0

    sufficient = sample_size >= min_samples

    meta = {
        "tier": tier,
        "evidence_level": entry["evidence_level"],
        "sample_size": sample_size,
        "sample_unit": entry.get("sample_unit"),
        "min_recommended_sample": min_samples,
        "confidence_level": confidence_level,
        "conclusion_allowed": policy["show_conclusion"] and sufficient,
        "recommendation_allowed": policy["show_suggestion"] and sufficient,
        "caution": entry["caution"],
        "assumptions": entry["assumptions"],
        "promotion_criteria": entry["promotion_criteria"],
    }
    if input_provenance is not None:
        meta["input_provenance"] = input_provenance
    return meta


def build_empty_meta(analysis_type: str) -> dict:
    """サンプルサイズ 0 での meta を返す（データなし状態）。"""
    return build_response_meta(analysis_type, 0)
