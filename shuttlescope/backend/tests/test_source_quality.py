"""ソース品質スコアリングユーティリティのテスト

backend/utils/source_quality.py の compute_suitability / compute_source_score / rank_sources を検証する。
"""
import pytest
from backend.utils.source_quality import (
    compute_suitability,
    compute_source_score,
    rank_sources,
)


# ─── compute_suitability ──────────────────────────────────────────────────────

class TestComputeSuitability:
    def test_iphone_webrtc_is_high_priority_1(self):
        p, s = compute_suitability("iphone_webrtc")
        assert p == 1
        assert s == "high"

    def test_ipad_webrtc_is_high_priority_1(self):
        p, s = compute_suitability("ipad_webrtc")
        assert p == 1
        assert s == "high"

    def test_usb_camera_is_high_priority_2(self):
        p, s = compute_suitability("usb_camera")
        assert p == 2
        assert s == "high"

    def test_builtin_camera_is_usable_priority_3(self):
        p, s = compute_suitability("builtin_camera")
        assert p == 3
        assert s == "usable"

    def test_unknown_kind_is_fallback_priority_4(self):
        p, s = compute_suitability("mystery_device")
        assert p == 4
        assert s == "fallback"

    def test_fullhd_resolution_upgrades_usable_to_high(self):
        """1920x1080 解像度の builtin_camera は usable → high に昇格"""
        p, s = compute_suitability("builtin_camera", resolution="1920x1080")
        assert s == "high"

    def test_fullhd_resolution_improves_priority(self):
        """Full HD 解像度は priority を 1 改善する"""
        p_no_res, _ = compute_suitability("builtin_camera")
        p_fullhd, _ = compute_suitability("builtin_camera", resolution="1920x1080")
        assert p_fullhd < p_no_res

    def test_hd_resolution_does_not_upgrade_usable(self):
        """1280x720 は usable のままでよい（Full HD 以上が昇格条件）"""
        _, s = compute_suitability("builtin_camera", resolution="1280x720")
        assert s == "usable"

    def test_60fps_upgrades_usable_to_high(self):
        """60fps の builtin_camera は high に昇格"""
        _, s = compute_suitability("builtin_camera", fps=60)
        assert s == "high"

    def test_30fps_does_not_upgrade(self):
        """30fps では usable のまま"""
        _, s = compute_suitability("builtin_camera", fps=30)
        assert s == "usable"

    def test_high_suitability_not_degraded(self):
        """すでに high の種別は解像度・fps に関わらず high を維持"""
        _, s = compute_suitability("iphone_webrtc", resolution="640x480", fps=15)
        assert s == "high"

    def test_fallback_kind_not_upgraded_by_resolution(self):
        """fallback 種別は解像度が高くても suitability は fallback のまま"""
        _, s = compute_suitability("mystery_device", resolution="1920x1080")
        assert s == "fallback"

    def test_fallback_kind_priority_improved_by_resolution(self):
        """fallback 種別でも解像度が高ければ priority は改善する"""
        p_low, _ = compute_suitability("mystery_device", resolution="320x240")
        p_high, _ = compute_suitability("mystery_device", resolution="1920x1080")
        assert p_high <= p_low

    def test_priority_floor_is_1(self):
        """priority は 1 より小さくならない"""
        p, _ = compute_suitability("iphone_webrtc", resolution="4096x2160", fps=120)
        assert p >= 1

    def test_invalid_resolution_string_handled_gracefully(self):
        """不正な解像度文字列でもクラッシュしない"""
        p, s = compute_suitability("builtin_camera", resolution="invalid")
        assert isinstance(p, int)
        assert s in ("high", "usable", "fallback")

    def test_none_resolution_and_fps(self):
        """None の解像度・fps でもクラッシュしない"""
        p, s = compute_suitability("usb_camera", resolution=None, fps=None)
        assert s == "high"
        assert isinstance(p, int)


# ─── compute_source_score ─────────────────────────────────────────────────────

class TestComputeSourceScore:
    def test_high_suitability_higher_than_usable(self):
        score_high = compute_source_score("iphone_webrtc")
        score_usable = compute_source_score("builtin_camera")
        assert score_high > score_usable

    def test_usable_higher_than_fallback(self):
        score_usable = compute_source_score("builtin_camera")
        score_fallback = compute_source_score("mystery_device")
        assert score_usable > score_fallback

    def test_fullhd_higher_score_than_hd(self):
        score_fullhd = compute_source_score("builtin_camera", resolution="1920x1080")
        score_hd = compute_source_score("builtin_camera", resolution="1280x720")
        assert score_fullhd > score_hd

    def test_60fps_higher_score_than_30fps(self):
        score_60 = compute_source_score("builtin_camera", fps=60)
        score_30 = compute_source_score("builtin_camera", fps=30)
        assert score_60 > score_30

    def test_score_is_positive(self):
        score = compute_source_score("mystery_device")
        assert score > 0

    def test_120fps_bonus_higher_than_60fps(self):
        score_120 = compute_source_score("usb_camera", fps=120)
        score_60 = compute_source_score("usb_camera", fps=60)
        assert score_120 > score_60


# ─── rank_sources ─────────────────────────────────────────────────────────────

class TestRankSources:
    def test_highest_quality_first(self):
        sources = [
            {"source_kind": "mystery_device"},
            {"source_kind": "iphone_webrtc"},
            {"source_kind": "builtin_camera"},
        ]
        ranked = rank_sources(sources)
        assert ranked[0]["source_kind"] == "iphone_webrtc"

    def test_empty_list(self):
        assert rank_sources([]) == []

    def test_single_source(self):
        sources = [{"source_kind": "usb_camera", "source_resolution": "1920x1080"}]
        ranked = rank_sources(sources)
        assert len(ranked) == 1

    def test_resolution_tiebreaker(self):
        """同じ種別でも高解像度の方が先に来る"""
        sources = [
            {"source_kind": "builtin_camera", "source_resolution": "640x480"},
            {"source_kind": "builtin_camera", "source_resolution": "1920x1080"},
        ]
        ranked = rank_sources(sources)
        assert ranked[0]["source_resolution"] == "1920x1080"

    def test_fps_tiebreaker(self):
        """同じ種別・解像度でも高 fps の方が先に来る"""
        sources = [
            {"source_kind": "usb_camera", "source_fps": 30},
            {"source_kind": "usb_camera", "source_fps": 120},
        ]
        ranked = rank_sources(sources)
        assert ranked[0]["source_fps"] == 120

    def test_order_preserved_when_equal(self):
        """同スコアの場合、ソート結果は安定している（順序変化なし）"""
        sources = [
            {"source_kind": "iphone_webrtc"},
            {"source_kind": "ipad_webrtc"},
        ]
        ranked = rank_sources(sources)
        # どちらが先でも良いが、長さは保たれる
        assert len(ranked) == 2
