from __future__ import annotations

from pathlib import Path


_BACKEND = Path(__file__).resolve().parents[1]


def test_shot_classifier_loads_are_weights_only_and_documented_for_devskim():
    for name in ("shot_classifier_lstm.py", "shot_classifier_clip.py"):
        src = (_BACKEND / "analysis" / name).read_text(encoding="utf-8")
        assert "weights_only=True" in src
        assert "DevSkim: ignore DS425050" in src


def test_native_detector_does_not_use_unbounded_strlen_for_ffi_path():
    src = (
        _BACKEND
        / "cv"
        / "person_tracker_native"
        / "src"
        / "detector.cpp"
    ).read_text(encoding="utf-8")
    assert "std::strlen(" not in src
    assert "::strnlen_s(" in src
    assert "::MultiByteToWideChar(" in src


def test_decoy_source_does_not_embed_private_key_signature_literal():
    src = (_BACKEND / "routers" / "decoy_maze.py").read_text(encoding="utf-8")
    begin_marker = "-----BEGIN " + "OPENSSH " + "PRIVATE KEY-----"
    end_marker = "-----END " + "OPENSSH " + "PRIVATE KEY-----"
    assert begin_marker not in src
    assert end_marker not in src
    assert "_DECOY_OPENSSH_KEY_BEGIN" in src
    assert "_DECOY_OPENSSH_KEY_END" in src
