"""native detector integration (SS_PERSON_USE_NATIVE) の unit test。

.pyd / GPU 無しでも回る:
- (a) env 未設定 (既定) では native を一切触らず Python core を使う。
- (b) SS_PERSON_USE_NATIVE=1 でも .pyd import が失敗したら Python core に
      graceful fallback し、app は crash しない。

native ext の import を monkeypatch で常に失敗させることで、GPU/.pyd の無い
CI でも fallback 経路を検証できる。
"""
from __future__ import annotations

import numpy as np
import pytest

import backend.cv.person_tracker as pt
from backend.cv.person_tracker import PersonTracker, TrackedPerson


COURT_CORNERS = [(100.0, 100.0), (500.0, 100.0), (500.0, 500.0), (100.0, 500.0)]


def _reset_native_cache():
    """module 級 native import cache を毎テストでリセット。"""
    pt._native_ext = None
    pt._native_import_tried = False


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    _reset_native_cache()
    # env を既定 (OFF) に戻す。各テストで上書きする。
    monkeypatch.delenv("SS_PERSON_USE_NATIVE", raising=False)
    # PERSON_USE_NATIVE は import 時に読まれる module 定数なので、各テストで
    # 明示的に pt.PERSON_USE_NATIVE を差し替える。
    monkeypatch.setattr(pt, "PERSON_USE_NATIVE", False, raising=False)
    yield
    _reset_native_cache()


def _make_tracker():
    return PersonTracker(match_type="doubles", court_corners=COURT_CORNERS)


def test_default_uses_python_path(monkeypatch):
    """(a) env 未設定なら update_batch は _update_batch_python だけを呼び、
    native ext / _ensure_native_detector を一切触らない。"""
    assert pt.PERSON_USE_NATIVE is False
    tracker = _make_tracker()

    called = {"python": 0, "native": 0}

    def fake_python(frames, idxs):
        called["python"] += 1
        return [[] for _ in frames]

    def fake_native(frames, idxs):
        called["native"] += 1
        return [[] for _ in frames]

    monkeypatch.setattr(tracker, "_update_batch_python", fake_python)
    monkeypatch.setattr(tracker, "update_batch_native", fake_native)

    frames = [np.zeros((1080, 1920, 3), dtype=np.uint8)]
    out = tracker.update_batch(frames, [0])

    assert called["python"] == 1
    assert called["native"] == 0
    assert out == [[]]


def test_native_import_failure_falls_back(monkeypatch):
    """(b) SS_PERSON_USE_NATIVE=1 でも _load_native_ext が None (import 失敗) を
    返したら、native detector は init されず Python core に fallback。crash しない。"""
    monkeypatch.setattr(pt, "PERSON_USE_NATIVE", True, raising=False)
    # _load_native_ext を「常に失敗 → None」に。
    monkeypatch.setattr(pt, "_load_native_ext", lambda: None)

    tracker = _make_tracker()

    fallback_called = {"n": 0}

    def fake_python(frames, idxs):
        fallback_called["n"] += 1
        return [[TrackedPerson(bbox=(0, 0, 1, 1), track_id=1, court_id=None,
                               player_uuid=None, confidence=0.9)] for _ in frames]

    monkeypatch.setattr(tracker, "_update_batch_python", fake_python)

    frames = [np.zeros((1080, 1920, 3), dtype=np.uint8)]
    # crash しないこと + python fallback が呼ばれること
    out = tracker.update_batch(frames, [0])

    assert fallback_called["n"] == 1
    assert tracker._native_detector is None
    assert len(out) == 1 and out[0][0].track_id == 1


def test_loader_swallows_import_error(monkeypatch):
    """_load_native_ext は import が例外を投げても None を返し、例外を伝播しない。"""
    _reset_native_cache()

    import builtins
    real_import = builtins.__import__

    def boom(name, *a, **k):
        if name == "person_tracker_native_ext":
            raise ImportError("simulated: no .pyd / DLLs on this machine")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", boom)
    ext = pt._load_native_ext()
    assert ext is None
    # 二度目は cache されて再 import しない (None のまま)
    assert pt._load_native_ext() is None
