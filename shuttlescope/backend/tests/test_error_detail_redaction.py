"""例外文言がクライアント応答に漏れないこと (CodeQL py/stack-trace-exposure)。

背景: main.py の汎用例外ハンドラは本番姿勢でトレースバックを秘匿するが、
「例外を捕まえて 200 応答の一部として返す」経路はそのハンドラを通らないため
個別に塞ぐ必要があった。実際に以下 2 経路が生の例外文言を返していた:
  - services/comprehensive_report.py `_safe_call` の section error
  - yolo 推論エンジンの `_last_debug["error"]` (/api/yolo/frame-detect の debug)
加えて /api/yolo/status の status_message も同じ経路だった。

秘匿は環境で分岐させない (開発時も詳細を返さない)。実行時フラグで分岐すると
静的解析上「例外 → 応答」の経路が残り続け、かつ本番判定が将来 fail-open した
瞬間に漏れる構造になるため。調査に必要な情報はサーバログ側に残る。
"""
import logging

from backend.utils.error_detail import GENERIC_ERROR_JA, client_safe_error

_SECRET = r"C:\Users\kiyus\models\yolov8n.onnx: invalid graph node 'x'"


# ── ヘルパー本体 ─────────────────────────────────────────────────────────────

def test_returns_generic_message_by_default():
    assert client_safe_error() == GENERIC_ERROR_JA


def test_accepts_custom_generic_message():
    assert client_safe_error("推論に失敗しました") == "推論に失敗しました"


def test_helper_cannot_be_handed_an_exception():
    """例外を渡して文言化する余地を型の上で残さないこと。

    引数に例外を取れてしまうと、呼び出し側がうっかり str(exc) を応答へ
    流し込む経路が復活する。
    """
    import inspect
    params = list(inspect.signature(client_safe_error).parameters)
    assert params == ["generic"]


# ── 漏洩経路 1: 包括レポートの section error ─────────────────────────────────

def _boom():
    raise RuntimeError(r'psycopg: relation "secret_table" does not exist')


def test_report_section_error_is_generic(caplog):
    from backend.services.comprehensive_report import _safe_call

    with caplog.at_level(logging.WARNING):
        got = _safe_call("descriptive", _boom)

    assert got["ok"] is False
    assert got["error"] == GENERIC_ERROR_JA
    assert "secret_table" not in got["error"]
    # 調査用の情報はログ側に残っていること (握り潰しではない)
    assert "secret_table" in caplog.text


def test_report_section_success_is_unchanged():
    from backend.services.comprehensive_report import _safe_call
    assert _safe_call("descriptive", lambda: {"value": 1}) == {"ok": True, "data": {"value": 1}}


# ── 漏洩経路 2: YOLO 推論 debug ──────────────────────────────────────────────

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
        raise RuntimeError(_SECRET)

    engine._predict_onnx = _boom_onnx
    return engine


def _gray_frame():
    import numpy as np
    # frame_mean >= 3.0 にして「ほぼ黒」warning 分岐を避ける
    return np.full((32, 32, 3), 128, dtype=np.uint8)


def test_yolo_predict_frame_debug_error_is_generic(caplog):
    """predict_frame の例外が debug["error"] 経由で漏れないこと (実コード経路)。"""
    engine = _engine_forced_to_fail()

    with caplog.at_level(logging.ERROR):
        assert engine.predict_frame(_gray_frame()) == []

    err = engine.get_last_debug()["error"]
    assert err == "推論に失敗しました"
    for leaked in ("yolov8n", "kiyus", "invalid graph"):
        assert leaked not in err
    # 完全な情報はサーバログに残る
    assert "invalid graph" in caplog.text


# ── 漏洩経路 3: /api/yolo/status の status_message ───────────────────────────

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


def _status_body(monkeypatch, detail):
    from fastapi.testclient import TestClient

    from backend.main import app
    from backend.routers import yolo as yolo_router

    monkeypatch.setattr(yolo_router, "get_yolo_inference", lambda: _FakeEngine(detail))
    client = TestClient(app, base_url="http://localhost")
    return client.get("/api/yolo/status").json()["data"]


def test_yolo_status_redacts_load_failure(monkeypatch):
    # backend.routers.yolo の logger は root へ伝播しない設定なので caplog では
    # 拾えない。ログ出力の有無はハンドラを直接付けて確認する。
    from backend.routers import yolo as yolo_router

    captured: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            captured.append(record.getMessage())

    handler = _Capture(level=logging.WARNING)
    yolo_router.logger.addHandler(handler)
    try:
        body = _status_body(monkeypatch, {
            "status_code": "load_failed",
            "backend": None,
            "message": r"TRT/CUDA load failed: C:\models\engine.plan not found",
        })
    finally:
        yolo_router.logger.removeHandler(handler)

    assert body["status_code"] == "load_failed"
    assert body["status_message"] == "モデルの読み込みに失敗しました"
    for leaked in ("engine.plan", "TRT"):
        assert leaked not in body["status_message"]
        assert leaked not in (body["install_hint"] or "")
    # 調査用の情報はサーバログ側に残っていること (握り潰しではない)
    assert any("engine.plan" in m for m in captured), captured


def test_yolo_status_keeps_static_setup_guidance(monkeypatch):
    """静的な導入案内まで潰すと運用者が手掛かりを失うため、残すこと。"""
    static_hint = "pip install ultralytics を実行してモデルを導入してください"
    body = _status_body(monkeypatch, {
        "status_code": "package_missing",
        "backend": None,
        "message": static_hint,
    })
    assert body["status_message"] == static_hint
    assert body["install_hint"] == static_hint
