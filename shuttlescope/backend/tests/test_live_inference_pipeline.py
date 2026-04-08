"""ライブ推論パイプライン テスト（単一 PC 合成フレーム）

POST /api/tracknet/live_frame_hint のエンドポイントをモデルなし環境で検証する:
  - モデル未導入時の safe fallback
  - フレームバッファリング（1/2 フレームは buffering=True）
  - 3 フレーム蓄積後に推論試行
  - 不正な base64 でのエラー処理
  - セッションコードによるバッファ分離
"""
import base64
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)

# ─── 合成 1×1 JPEG（最小有効 JPEG バイト列） ──────────────────────────────────
# Python Imaging Library なしで生成できる最小 JPEG（白 1×1 px）
_MINIMAL_JPEG_BYTES = bytes([
    0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
    0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
    0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
    0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
    0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
    0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
    0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
    0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
    0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
    0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
    0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
    0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D,
    0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
    0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
    0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
    0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
    0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
    0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
    0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75,
    0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
    0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3,
    0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6,
    0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9,
    0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
    0xE3, 0xE4, 0xE5, 0xE6, 0xE7, 0xE8, 0xE9, 0xEA, 0xF1, 0xF2, 0xF3, 0xF4,
    0xF5, 0xF6, 0xF7, 0xF8, 0xF9, 0xFA, 0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01,
    0x00, 0x00, 0x3F, 0x00, 0xFB, 0x26, 0xA2, 0x8A, 0xFF, 0xD9,
])
_FRAME_B64 = "data:image/jpeg;base64," + base64.b64encode(_MINIMAL_JPEG_BYTES).decode()

# テスト間でフレームバッファが汚染しないよう、都度ユニークなセッションコードを使う
_counter = 0


def _fresh_code() -> str:
    global _counter
    _counter += 1
    return f"LIVE_INF_{_counter:04d}"


# ─── モデル未導入時の safe fallback ───────────────────────────────────────────

class TestModelUnavailable:
    def test_returns_available_false_when_no_model(self):
        """TrackNet モデル未導入時は available=False を返しクラッシュしない"""
        code = _fresh_code()
        resp = client.post("/api/tracknet/live_frame_hint", json={
            "session_code": code,
            "frame_b64": _FRAME_B64,
            "frame_width": 1,
            "frame_height": 1,
            "confidence_threshold": 0.5,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        # モデルなし → available=False OR buffering=True のどちらかが返る
        d = data["data"]
        assert d.get("available") is False or d.get("buffering") is True

    def test_returns_success_true_not_http_error(self):
        """モデルなしでも 5xx エラーにならない"""
        code = _fresh_code()
        resp = client.post("/api/tracknet/live_frame_hint", json={
            "session_code": code,
            "frame_b64": _FRAME_B64,
        })
        assert resp.status_code == 200


# ─── フレームバッファリングのテスト ───────────────────────────────────────────

class TestFrameBuffering:
    def test_first_frame_returns_buffering(self):
        """1 フレーム目は buffering=True（またはモデルなし available=False）"""
        mock_inf = MagicMock()
        mock_inf.is_available.return_value = True
        mock_inf.load.return_value = True
        mock_inf.predict_frames.return_value = []

        code = _fresh_code()
        with patch("backend.routers.tracknet.get_inference", return_value=mock_inf):
            resp = client.post("/api/tracknet/live_frame_hint", json={
                "session_code": code,
                "frame_b64": _FRAME_B64,
            })
        assert resp.status_code == 200
        d = resp.json()["data"]
        assert d.get("buffering") is True

    def test_second_frame_still_buffering(self):
        """2 フレーム目もまだ buffering=True"""
        mock_inf = MagicMock()
        mock_inf.is_available.return_value = True
        mock_inf.load.return_value = True
        mock_inf.predict_frames.return_value = []

        code = _fresh_code()
        with patch("backend.routers.tracknet.get_inference", return_value=mock_inf):
            for _ in range(2):
                resp = client.post("/api/tracknet/live_frame_hint", json={
                    "session_code": code,
                    "frame_b64": _FRAME_B64,
                })
        assert resp.status_code == 200
        d = resp.json()["data"]
        assert d.get("buffering") is True

    def test_third_frame_triggers_inference(self):
        """3 フレーム目で predict_frames が呼ばれる"""
        mock_inf = MagicMock()
        mock_inf.is_available.return_value = True
        mock_inf.load.return_value = True
        mock_inf.predict_frames.return_value = []

        code = _fresh_code()
        with patch("backend.routers.tracknet.get_inference", return_value=mock_inf):
            for _ in range(3):
                client.post("/api/tracknet/live_frame_hint", json={
                    "session_code": code,
                    "frame_b64": _FRAME_B64,
                })

        assert mock_inf.predict_frames.call_count >= 1

    def test_third_frame_with_result_returns_zone(self):
        """3 フレームで推論結果が返ると zone / confidence が含まれる"""
        mock_inf = MagicMock()
        mock_inf.is_available.return_value = True
        mock_inf.load.return_value = True
        mock_inf.predict_frames.return_value = [{
            "zone": "FN",
            "confidence": 0.85,
            "x_norm": 0.5,
            "y_norm": 0.3,
        }]

        code = _fresh_code()
        resp = None
        with patch("backend.routers.tracknet.get_inference", return_value=mock_inf):
            for _ in range(3):
                resp = client.post("/api/tracknet/live_frame_hint", json={
                    "session_code": code,
                    "frame_b64": _FRAME_B64,
                    "confidence_threshold": 0.5,
                })

        assert resp is not None
        d = resp.json()["data"]
        assert d.get("zone") == "FN"
        assert d.get("confidence") == pytest.approx(0.85, rel=0.01)
        assert d.get("available") is True

    def test_low_confidence_result_returns_none_zone(self):
        """信頼度が閾値未満の場合は zone=None を返す"""
        mock_inf = MagicMock()
        mock_inf.is_available.return_value = True
        mock_inf.load.return_value = True
        mock_inf.predict_frames.return_value = [{
            "zone": "FN",
            "confidence": 0.3,   # 閾値 0.5 未満
            "x_norm": 0.5,
            "y_norm": 0.3,
        }]

        code = _fresh_code()
        with patch("backend.routers.tracknet.get_inference", return_value=mock_inf):
            for _ in range(3):
                resp = client.post("/api/tracknet/live_frame_hint", json={
                    "session_code": code,
                    "frame_b64": _FRAME_B64,
                    "confidence_threshold": 0.5,
                })

        d = resp.json()["data"]
        assert d.get("zone") is None


# ─── セッションコードによるバッファ分離 ──────────────────────────────────────

class TestSessionIsolation:
    def test_different_session_codes_have_independent_buffers(self):
        """異なるセッションコードのフレームバッファは独立している"""
        mock_inf = MagicMock()
        mock_inf.is_available.return_value = True
        mock_inf.load.return_value = True
        mock_inf.predict_frames.return_value = []

        code_a = _fresh_code()
        code_b = _fresh_code()

        with patch("backend.routers.tracknet.get_inference", return_value=mock_inf):
            # セッション A に 3 フレーム送信
            for _ in range(3):
                client.post("/api/tracknet/live_frame_hint", json={
                    "session_code": code_a,
                    "frame_b64": _FRAME_B64,
                })
            # セッション B には 1 フレームのみ → buffering のはず
            resp_b = client.post("/api/tracknet/live_frame_hint", json={
                "session_code": code_b,
                "frame_b64": _FRAME_B64,
            })

        d_b = resp_b.json()["data"]
        assert d_b.get("buffering") is True


# ─── エラーハンドリング ───────────────────────────────────────────────────────

class TestErrorHandling:
    def test_invalid_base64_returns_error(self):
        """不正な base64 データでも 5xx にならない"""
        mock_inf = MagicMock()
        mock_inf.is_available.return_value = True
        mock_inf.load.return_value = True

        code = _fresh_code()
        with patch("backend.routers.tracknet.get_inference", return_value=mock_inf):
            resp = client.post("/api/tracknet/live_frame_hint", json={
                "session_code": code,
                "frame_b64": "NOT_VALID_BASE64!!!@@##",
            })
        assert resp.status_code == 200
        body = resp.json()
        # success=False または data.available=False のどちらかで graceful に返る
        assert body.get("success") is False or body["data"].get("available") is False or body["data"].get("buffering") is True

    def test_missing_session_code_field_returns_422(self):
        """session_code が欠けていると 422 バリデーションエラー"""
        resp = client.post("/api/tracknet/live_frame_hint", json={
            "frame_b64": _FRAME_B64,
        })
        assert resp.status_code == 422

    def test_missing_frame_b64_field_returns_422(self):
        """frame_b64 が欠けていると 422 バリデーションエラー"""
        resp = client.post("/api/tracknet/live_frame_hint", json={
            "session_code": _fresh_code(),
        })
        assert resp.status_code == 422
