"""コートキャリブレーション ユーティリティ関数のユニットテスト

テスト対象:
  - _compute_homography / apply_homography: 4コーナー対応からのホモグラフィ計算
  - pixel_to_court_zone: 画像正規化座標 → ゾーン名変換
  - is_inside_court: Ray casting によるコート内外判定
  - _invert_homography: 逆変換の往復精度

DB やルーターには依存しないピュア計算のテスト。
"""
import math
import pytest

from backend.routers.court_calibration import (
    _compute_homography,
    _invert_homography,
    apply_homography,
    is_inside_court,
    pixel_to_court_zone,
)


# ─── フィクスチャ: 正軸アライン済みキャリブレーション ─────────────────────────────
# 画像座標とコート座標が完全一致（スケール1:1の恒等写像に相当）の場合は
# ホモグラフィが [1,0,0; 0,1,0; 0,0,1] に収束するべき。
#
# ただし DLT 実装は H[2,2] 正規化するため、数値的に恒等ではなく
# 「各コーナーが正確に変換される」ことを検証する。

UNIT_SQUARE_SRC = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
UNIT_SQUARE_DST = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]


@pytest.fixture
def identity_H():
    return _compute_homography(UNIT_SQUARE_SRC, UNIT_SQUARE_DST)


# ─── _compute_homography ─────────────────────────────────────────────────────

class TestComputeHomography:
    def test_identity_maps_corners_exactly(self, identity_H):
        """同一4点の対応 → 各コーナーが [0,1]×[0,1] に変換される"""
        corners = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        for (x, y) in corners:
            cx, cy = apply_homography(identity_H, x, y)
            assert abs(cx - x) < 1e-6, f"corner ({x},{y}) x mismatch: {cx}"
            assert abs(cy - y) < 1e-6, f"corner ({x},{y}) y mismatch: {cy}"

    def test_midpoint_preserved(self, identity_H):
        """中点(0.5, 0.5)も正確に変換される"""
        cx, cy = apply_homography(identity_H, 0.5, 0.5)
        assert abs(cx - 0.5) < 1e-6
        assert abs(cy - 0.5) < 1e-6

    def test_perspective_transform(self):
        """台形 → 正方形の射影変換: コーナー 4点が正確に変換される"""
        # カメラ視点を模した台形（下辺が広い、上辺が狭い）
        src = [(0.2, 0.1), (0.8, 0.1), (1.0, 0.9), (0.0, 0.9)]
        dst = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        H = _compute_homography(src, dst)
        for (sx, sy), (dx, dy) in zip(src, dst):
            cx, cy = apply_homography(H, sx, sy)
            assert abs(cx - dx) < 1e-5, f"x mismatch at src=({sx},{sy}): {cx} != {dx}"
            assert abs(cy - dy) < 1e-5, f"y mismatch at src=({sx},{sy}): {cy} != {dy}"

    def test_result_is_3x3_matrix(self, identity_H):
        assert len(identity_H) == 3
        for row in identity_H:
            assert len(row) == 3


# ─── _invert_homography ────────────────────────────────────────────────────────

class TestInvertHomography:
    def test_roundtrip_court_to_pixel_and_back(self):
        """H → H_inv の往復変換が元座標に戻る"""
        src = [(0.15, 0.05), (0.85, 0.08), (0.90, 0.92), (0.10, 0.95)]
        dst = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        H = _compute_homography(src, dst)
        H_inv = _invert_homography(H)

        test_pt = (0.45, 0.55)
        # 画像 → コート
        cx, cy = apply_homography(H, *test_pt)
        # コート → 画像（逆変換）
        rx, ry = apply_homography(H_inv, cx, cy)
        assert abs(rx - test_pt[0]) < 1e-5, f"roundtrip x: {rx} != {test_pt[0]}"
        assert abs(ry - test_pt[1]) < 1e-5, f"roundtrip y: {ry} != {test_pt[1]}"

    def test_net_midpoint_maps_to_y05(self):
        """コートが正方形の場合、ネット中央(0.5,0.5)はコート中央(0.5,0.5)に"""
        H = _compute_homography(UNIT_SQUARE_SRC, UNIT_SQUARE_DST)
        cx, cy = apply_homography(H, 0.5, 0.5)
        assert abs(cy - 0.5) < 1e-5


# ─── pixel_to_court_zone ─────────────────────────────────────────────────────

class TestPixelToCourtZone:
    @pytest.fixture
    def flat_H(self):
        """恒等写像ホモグラフィ（画像座標=コート座標）"""
        return _compute_homography(UNIT_SQUARE_SRC, UNIT_SQUARE_DST)

    def test_top_left_is_A_front_left(self, flat_H):
        result = pixel_to_court_zone(0.05, 0.05, flat_H)
        assert result["zone_name"] == "A_front_left"
        assert result["side"] == "A"
        assert result["depth"] == "front"
        assert result["col"] == "left"

    def test_bottom_right_is_B_back_right(self, flat_H):
        result = pixel_to_court_zone(0.95, 0.95, flat_H)
        assert result["zone_name"] == "B_back_right"
        assert result["side"] == "B"
        assert result["depth"] == "back"
        assert result["col"] == "right"

    def test_net_center_is_B_front_center(self, flat_H):
        """Y=0.5 はB側 front（row_i=3: side='B', depth='front'）"""
        result = pixel_to_court_zone(0.5, 0.5 + 0.01, flat_H)  # ネット直下のB側
        assert result["side"] == "B"
        assert result["depth"] == "front"
        assert result["col"] == "center"

    def test_zone_id_range(self, flat_H):
        """zone_id は 0-17 の範囲に収まる"""
        for x in [0.1, 0.5, 0.9]:
            for y in [0.1, 0.3, 0.5, 0.7, 0.9]:
                result = pixel_to_court_zone(x, y, flat_H)
                assert 0 <= result["zone_id"] <= 17

    def test_court_xy_clamped(self, flat_H):
        """コート外の点は [0,1] にクランプされる"""
        result = pixel_to_court_zone(2.0, -1.0, flat_H)
        assert 0.0 <= result["court_x"] <= 1.0
        assert 0.0 <= result["court_y"] <= 1.0

    def test_zone_id_formula(self, flat_H):
        """zone_id = row_i * 3 + col_i が成立する"""
        result = pixel_to_court_zone(0.7, 0.8, flat_H)  # col=right(2), row=B_mid(4)
        col_i = 2   # x=0.7 → floor(0.7*3)=2
        row_i = 4   # y=0.8 → floor(0.8*6)=4
        expected_id = row_i * 3 + col_i
        assert result["zone_id"] == expected_id

    def test_all_18_zones_reachable(self, flat_H):
        """全18ゾーンを区別できること"""
        seen = set()
        # 各ゾーン中心を計算
        for row in range(6):
            for col in range(3):
                x = (col + 0.5) / 3.0
                y = (row + 0.5) / 6.0
                r = pixel_to_court_zone(x, y, flat_H)
                seen.add(r["zone_id"])
        assert len(seen) == 18, f"18ゾーン中 {len(seen)} しか到達できない"


# ─── is_inside_court ──────────────────────────────────────────────────────────

class TestIsInsideCourt:
    # 単位正方形コート
    SQUARE = [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]]

    def test_center_inside(self):
        assert is_inside_court(0.5, 0.5, self.SQUARE) is True

    def test_outside_right(self):
        assert is_inside_court(1.5, 0.5, self.SQUARE) is False

    def test_outside_top(self):
        assert is_inside_court(0.5, -0.1, self.SQUARE) is False

    def test_outside_bottom(self):
        assert is_inside_court(0.5, 1.1, self.SQUARE) is False

    def test_outside_left(self):
        assert is_inside_court(-0.1, 0.5, self.SQUARE) is False

    def test_near_corners_inside(self):
        """コーナー近くの内側の点"""
        assert is_inside_court(0.01, 0.01, self.SQUARE) is True
        assert is_inside_court(0.99, 0.99, self.SQUARE) is True

    def test_trapezoid_polygon(self):
        """非矩形（台形）コート内外判定"""
        # 画面上の典型的な台形コート
        trap = [[0.2, 0.1], [0.8, 0.1], [1.0, 0.9], [0.0, 0.9]]
        # 中央は内側
        assert is_inside_court(0.5, 0.5, trap) is True
        # 左外（台形の外）
        assert is_inside_court(0.05, 0.5, trap) is False
        # 右外
        assert is_inside_court(0.95, 0.5, trap) is False

    def test_empty_polygon_returns_false(self):
        assert is_inside_court(0.5, 0.5, []) is False

    def test_triangle_polygon(self):
        """三角形内外（アルゴリズムが多角形形状に依存しないことを確認）"""
        tri = [[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]]
        assert is_inside_court(0.5, 0.4, tri) is True
        assert is_inside_court(0.1, 0.9, tri) is False
