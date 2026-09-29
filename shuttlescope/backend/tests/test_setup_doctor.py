from backend.tools.setup_doctor import build_recommendations, compute_exit_code, summarize_report


def _base_report():
    return {
        "commands": {
            "python": "python",
            "npm": "npm",
            "ngrok": None,
            "cloudflared": None,
        },
        "frontend": {"node_modules": False},
        "tracknet": {
            "loaded": False,
            "failure_class": "weight_missing",
            "weights_dir": "backend/tracknet/weights",
            "files": {"onnx": False},
            "error": None,
        },
        "yolo": {
            "loaded": False,
            "failure_class": "package_missing",
            "status_code": "weights_missing",
            "message": "weights missing",
        },
        "packages": {
            "ultralytics": None,
            "numpy": "1.26.4",
            "scipy": "1.15.3",
        },
    }


def test_build_recommendations_mentions_bootstrap_steps():
    report = _base_report()
    recs = build_recommendations(report)
    joined = "\n".join(recs)
    assert "npm install" in joined
    assert "TrackNet" in joined
    assert "IncludeYolo" in joined
    assert "ngrok" in joined


def test_compute_exit_code_warns_for_optional_gaps():
    report = _base_report()
    assert compute_exit_code(report, strict=False) == 1


def test_compute_exit_code_strict_blocks_optional_gaps():
    report = _base_report()
    assert compute_exit_code(report, strict=True) == 2


def test_compute_exit_code_blocks_missing_core_commands():
    report = _base_report()
    report["commands"]["python"] = None
    assert compute_exit_code(report, strict=False) == 2


def test_summarize_report_contains_recommendations_section():
    report = _base_report()
    text = summarize_report(report)
    assert "Recommended next steps" in text
    assert "TrackNet" in text
