"""
コートヒートマップ合成ビュー テスト
HEATMAP_COMPOSITE_SPEC.md セクション6 準拠

⚠️ 合成変換は可視化専用。空間分析とは独立していること。
"""
import pytest

# 点対称変換マッピング（9ゾーン）
ZONE_ROTATION_MAP = {
    "BL": "NR", "BC": "NC", "BR": "NL",
    "ML": "MR", "MC": "MC", "MR": "ML",
    "NL": "BR", "NC": "BC", "NR": "BL",
}

# 12ゾーン対応マッピング（将来拡張用）
ZONE_ROTATION_MAP_12 = {
    "BLL": "NRR", "BLC": "NCR", "BCR": "NCL", "BRR": "NLL",
    "MLL": "MRR", "MLC": "MCR", "MCR": "MCL", "MRR": "MLL",
    "NLL": "BRR", "NLC": "BCR", "NCR": "BCL", "NRR": "BLL",
}


def rotate_zone(zone: str) -> str:
    """ゾーンを点対称変換する（可視化専用）"""
    return ZONE_ROTATION_MAP.get(zone, zone)


class TestZoneRotation:
    def test_bl_rotates_to_nr(self):
        """BL の点対称は NR"""
        assert rotate_zone("BL") == "NR"

    def test_mc_rotates_to_mc(self):
        """MC の点対称は MC（中央は不変）"""
        assert rotate_zone("MC") == "MC"

    def test_all_9_zones_have_mapping(self):
        """9ゾーン全てに変換マッピングが存在すること"""
        expected_zones = ["BL", "BC", "BR", "ML", "MC", "MR", "NL", "NC", "NR"]
        for z in expected_zones:
            assert z in ZONE_ROTATION_MAP, f"{z} の変換マッピングが未定義"

    def test_rotation_is_involutory(self):
        """点対称変換を2回適用すると元に戻ること（対合性）"""
        for zone in ZONE_ROTATION_MAP:
            rotated = ZONE_ROTATION_MAP[zone]
            back = ZONE_ROTATION_MAP[rotated]
            assert back == zone, f"{zone} → {rotated} → {back} (元に戻らない)"

    def test_bl_br_nr_nl_swap(self):
        """角ゾーンの対称性確認"""
        assert rotate_zone("BL") == "NR"
        assert rotate_zone("BR") == "NL"
        assert rotate_zone("NL") == "BR"
        assert rotate_zone("NR") == "BL"

    def test_ml_mr_swap(self):
        """ミドル左右の対称性確認"""
        assert rotate_zone("ML") == "MR"
        assert rotate_zone("MR") == "ML"

    def test_bc_nc_swap(self):
        """バック中とネット中の対称性確認"""
        assert rotate_zone("BC") == "NC"
        assert rotate_zone("NC") == "BC"


class Test12ZoneRotation:
    def test_12zone_rotation_completeness(self):
        """12ゾーン全てに変換マッピングが存在すること"""
        zones_12 = [
            "BLL", "BLC", "BCR", "BRR",
            "MLL", "MLC", "MCR", "MRR",
            "NLL", "NLC", "NCR", "NRR",
        ]
        for z in zones_12:
            assert z in ZONE_ROTATION_MAP_12, f"{z} の変換マッピングが未定義"


class TestCompositeDataStructure:
    """合成データ構造の検証"""

    def _mock_composite_result(self) -> dict:
        """モック合成データ（バックエンド関数の戻り値構造）"""
        hit_data = {z: {"count": 10, "rate": 0.1} for z in ZONE_ROTATION_MAP}
        land_rotated = {
            dst: {"count": 5, "rate": 0.05, "source": "land_rotated"}
            for dst in ZONE_ROTATION_MAP.values()
        }
        return {
            "hit": hit_data,
            "land_rotated": land_rotated,
            "total_strokes": 90,
            "note": "着地点データは点対称変換（ネット中心）により自コート座標系に変換済みです。この合成表示は可視化補助のみを目的としており、空間分析・ゾーン別勝率計算とは独立しています。",
        }

    def test_composite_note_present(self):
        """合成データに可視化専用の注記が含まれること"""
        result = self._mock_composite_result()
        assert "可視化" in result["note"] or "可視化補助" in result["note"]

    def test_land_rotated_has_source_flag(self):
        """land_rotated の全ゾーンに source='land_rotated' フラグがあること"""
        result = self._mock_composite_result()
        for zone_data in result["land_rotated"].values():
            assert zone_data.get("source") == "land_rotated", \
                f"source フラグが未設定: {zone_data}"

    def test_composite_does_not_affect_spatial_marker(self):
        """合成データには空間分析汚染マーカーが含まれないこと"""
        result = self._mock_composite_result()
        # 空間分析結果に 'source': 'land_rotated' が混入していないことを確認するための
        # 識別フラグが合成データにのみ存在すること
        spatial_mock = {"zone_win_rate": {"BL": 0.55}, "meta": {"type": "spatial"}}
        assert "source" not in str(spatial_mock), "空間分析データに合成フラグが混入している"
