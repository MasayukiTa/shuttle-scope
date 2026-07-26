"""例外文言がクライアント応答に漏れないこと (CodeQL py/stack-trace-exposure)。

背景: main.py の汎用例外ハンドラは本番姿勢でトレースバックを秘匿するが、
「例外を捕まえて 200 応答の一部として返す」経路はそのハンドラを通らないため
個別に秘匿する必要があった。実際に以下 2 経路が生の例外文言を返していた:
  - services/comprehensive_report.py `_safe_call` の section error
  - yolo 推論エンジンの `_last_debug["error"]` (/api/yolo/frame-detect の debug)
"""
import pytest

from backend.config import settings
from backend.utils.error_detail import GENERIC_ERROR_JA, client_safe_error


@pytest.fixture()
def prod_posture(monkeypatch):
    """本番姿勢を強制する。"""
    monkeypatch.setattr(settings, "HIDE_STACK_TRACES", True, raising=False)
    yield


@pytest.fixture()
def dev_posture(monkeypatch):
    """本番姿勢でない状態を強制する (env 由来の判定も潰す)。"""
    monkeypatch.setattr(settings, "PUBLIC_MODE", False, raising=False)
    monkeypatch.setattr(settings, "HIDE_API_DOCS", False, raising=False)
    monkeypatch.setattr(settings, "HIDE_STACK_TRACES", False, raising=False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "development", raising=False)
    monkeypatch.delenv("ENVIRONMENT", raising=False)
    monkeypatch.delenv("SS_PUBLIC_HOSTNAME", raising=False)
    yield


# ── ヘルパー本体 ─────────────────────────────────────────────────────────────

def test_production_hides_exception_text(prod_posture):
    exc = RuntimeError(r"C:\models\yolov8n.onnx を開けません (CUDA driver 596.21)")
    out = client_safe_error(exc)
    assert out == GENERIC_ERROR_JA
    # 内部情報が 1 つも残っていないこと
    for leaked in ("models", "yolov8n", "CUDA", "596.21", r"C:\\"):
        assert leaked not in out


def test_production_allows_custom_generic(prod_posture):
    assert client_safe_error(RuntimeError("secret path"), generic="推論に失敗しました") \
        == "推論に失敗しました"


def test_development_keeps_detail_for_debugging(dev_posture):
    exc = RuntimeError("ONNX load failed: bad graph")
    assert client_safe_error(exc) == "ONNX load failed: bad graph"


def test_development_truncates_long_detail(dev_posture):
    out = client_safe_error(RuntimeError("x" * 5000), limit=200)
    assert len(out) == 200


# ── 実際の漏洩経路 1: 包括レポートの section error ───────────────────────────

def _boom():
    raise RuntimeError(r"psycopg: relation \"secret_table\" does not exist")


def test_report_section_error_is_redacted_in_production(prod_posture):
    from backend.services.comprehensive_report import _safe_call
    got = _safe_call("descriptive", _boom)
    assert got["ok"] is False
    assert got["error"] == GENERIC_ERROR_JA
    assert "secret_table" not in got["error"]


def test_report_section_error_keeps_detail_in_development(dev_posture):
    from backend.services.comprehensive_report import _safe_call
    got = _safe_call("descriptive", _boom)
    assert got["ok"] is False
    assert "secret_table" in got["error"]


def test_report_section_success_is_unchanged(prod_posture):
    from backend.services.comprehensive_report import _safe_call
    got = _safe_call("descriptive", lambda: {"value": 1})
    assert got == {"ok": True, "data": {"value": 1}}


# ── 実際の漏洩経路 2: YOLO 推論 debug ────────────────────────────────────────

_SECRET_PATH = r"C:\Users\kiyus\models\yolov8n.onnx: invalid graph node 'x'"


def _engine_forced_to_fail():
    """推論本体が例外を投げる状態にした実 engine を返す。

    predict_frame の except 分岐 (= 実際に漏洩していた箇所) を通すため、
    ロード済みに見せかけてバックエンド呼び出しだけを失敗させる。
    """
    import threading

    from backend.yolo import inference as inf_mod

    engine = inf_mod.YOLOInference.__new__(inf_mod.YOLOInference)
    engine._loaded = True
    engine._backend = "onnx"
    engine._lock = threading.Lock()
    engine._last_debug = {}
    engine._court_polygon_expanded = None

    def _boom_onnx(_frame):
        raise RuntimeError(_SECRET_PATH)

    engine._predict_onnx = _boom_onnx
    return engine


def _gray_frame():
    import numpy as np
    # frame_mean >= 3.0 にして「ほぼ黒」warning 分岐を避ける
    return np.full((32, 32, 3), 128, dtype=np.uint8)


def test_yolo_predict_frame_debug_error_is_redacted_in_production(prod_posture):
    """predict_frame の例外が debug["error"] 経由で漏れないこと (実コード経路)。"""
    engine = _engine_forced_to_fail()
    assert engine.predict_frame(_gray_frame()) == []

    err = engine.get_last_debug()["error"]
    assert err == "推論に失敗しました"
    for leaked in ("yolov8n", "kiyus", "invalid graph", r"C:\\"):
        assert leaked not in err


def test_yolo_predict_frame_keeps_detail_in_development(dev_posture):
    """開発時は原因調査のため詳細を残すこと。"""
    engine = _engine_forced_to_fail()
    engine.predict_frame(_gray_frame())
    assert "invalid graph" in engine.get_last_debug()["error"]


def test_yolo_status_endpoint_redacts_only_load_failure(prod_posture, monkeypatch):
    """/api/yolo/status: load_failed の message だけ秘匿し静的案内は残す。

    静的案内まで潰すと運用者が「何をすればよいか」を失うため、
    status_code による分岐を実エンドポイントで固定する。
    """
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.routers import yolo as yolo_router

    class _FakeEngine:
        def __init__(self, detail):
            self._detail = detail
            self._loaded = False

        def get_status_detail(self):
            return self._detail

        def is_available(self):
            return False

        def backend_name(self):
            return None

    client = TestClient(app, base_url="http://localhost")

    # 1) load_failed → 例外文言は秘匿される
    monkeypatch.setattr(
        yolo_router, "get_yolo_inference",
        lambda: _FakeEngine({
            "status_code": "load_failed",
            "backend": None,
            "message": r"TRT/CUDA load failed: C:\models\engine.plan not found",
        }),
    )
    body = client.get("/api/yolo/status").json()["data"]
    assert body["status_code"] == "load_failed"
    assert body["status_message"] == "モデルの読み込みに失敗しました"
    for leaked in ("engine.plan", r"C:\\", "TRT"):
        assert leaked not in body["status_message"]
        assert leaked not in (body["install_hint"] or "")

    # 2) package_missing → 静的な導入案内はそのまま届く
    static_hint = "pip install ultralytics を実行してモデルを導入してください"
    monkeypatch.setattr(
        yolo_router, "get_yolo_inference",
        lambda: _FakeEngine({
            "status_code": "package_missing",
            "backend": None,
            "message": static_hint,
        }),
    )
    body = client.get("/api/yolo/status").json()["data"]
    assert body["status_message"] == static_hint
    assert body["install_hint"] == static_hint
