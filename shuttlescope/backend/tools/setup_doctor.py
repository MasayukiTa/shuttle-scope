"""Environment doctor for easier device bootstrap.

Usage:
  python -m backend.tools.setup_doctor
  python -m backend.tools.setup_doctor --format json
  python -m backend.tools.setup_doctor --strict
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any


def _package_version(name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return None


def _error_payload(stage: str, exc: Exception) -> dict[str, Any]:
    return {
        "available": False,
        "loaded": False,
        "backend": None,
        "error_stage": stage,
        "error": str(exc),
    }


def _tracknet_status() -> dict[str, Any]:
    try:
        from backend.tracknet.inference import WEIGHTS_DIR, TrackNetInference
    except Exception as exc:
        return {
            "weights_dir": None,
            "files": {},
            **_error_payload("import", exc),
        }

    files = {
        "tf_index": (WEIGHTS_DIR / "TrackNet.index").exists(),
        "tf_data": (WEIGHTS_DIR / "TrackNet.data-00000-of-00001").exists(),
        "onnx": (WEIGHTS_DIR / "tracknet.onnx").exists(),
        "openvino": (WEIGHTS_DIR / "tracknet.xml").exists(),
    }

    try:
        inf = TrackNetInference()
        available = inf.is_available()
        loaded = inf.load() if available else False
    except Exception as exc:
        return {
            "weights_dir": str(WEIGHTS_DIR),
            "files": files,
            **_error_payload("init", exc),
        }

    return {
        "weights_dir": str(WEIGHTS_DIR),
        "files": files,
        "available": available,
        "loaded": loaded,
        "backend": inf.backend_name() if loaded else None,
        "error": None if loaded else inf.get_load_error(),
    }


def _yolo_status() -> dict[str, Any]:
    try:
        from backend.yolo.inference import get_yolo_inference
    except Exception as exc:
        return {
            "status_code": "import_error",
            "backend": None,
            "message": str(exc),
            "loaded": False,
        }

    try:
        inf = get_yolo_inference()
        detail = inf.get_status_detail()
    except Exception as exc:
        return {
            "status_code": "init_error",
            "backend": None,
            "message": str(exc),
            "loaded": False,
        }

    return {
        "status_code": detail.get("status_code"),
        "backend": detail.get("backend"),
        "message": detail.get("message"),
        "loaded": inf.backend_name() is not None,
    }


def build_report() -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    frontend_root = root

    return {
        "paths": {
            "repo_root": str(root),
            "package_json": str(frontend_root / "package.json"),
            "requirements": str(root / "backend" / "requirements.txt"),
        },
        "commands": {
            "python": shutil.which("python"),
            "npm": shutil.which("npm"),
            "ngrok": shutil.which("ngrok"),
            "cloudflared": shutil.which("cloudflared"),
        },
        "packages": {
            "tensorflow": _package_version("tensorflow"),
            "tf2onnx": _package_version("tf2onnx"),
            "onnxruntime": _package_version("onnxruntime"),
            "opencv-python": _package_version("opencv-python"),
            "ultralytics": _package_version("ultralytics"),
            "numpy": _package_version("numpy"),
            "scipy": _package_version("scipy"),
        },
        "tracknet": _tracknet_status(),
        "yolo": _yolo_status(),
        "frontend": {
            "node_modules": (frontend_root / "node_modules").exists(),
        },
    }


def build_recommendations(report: dict[str, Any]) -> list[str]:
    recs: list[str] = []

    commands = report["commands"]
    frontend = report["frontend"]
    packages = report["packages"]
    tracknet = report["tracknet"]
    yolo = report["yolo"]

    if not commands.get("python"):
        recs.append("Python 3.10+ をインストールしてください。")
    if not commands.get("npm"):
        recs.append("Node.js 18+ をインストールしてください。")
    if not frontend.get("node_modules"):
        recs.append("`npm install` を実行してフロント依存を導入してください。")
    if not commands.get("ngrok"):
        recs.append("リモート共有を使うなら `ngrok` をインストールしてください。")

    if not tracknet.get("loaded"):
        if not tracknet.get("files", {}).get("onnx"):
            recs.append("TrackNet は `./bootstrap_windows.ps1 -SetupTrackNet` で準備してください。")
        elif tracknet.get("error"):
            recs.append(f"TrackNet 読み込み失敗: {tracknet['error']}")

    if not packages.get("ultralytics"):
        recs.append("YOLO を使うなら `./bootstrap_windows.ps1 -IncludeYolo` を実行してください。")
    elif yolo.get("status_code") == "weights_missing":
        recs.append("YOLO は初回バッチ実行で重みを取得するか、ローカル重みを配置してください。")
    elif yolo.get("status_code") in {"import_error", "init_error"}:
        recs.append(f"YOLO 初期化失敗: {yolo.get('message')}")

    if packages.get("numpy") and packages.get("scipy"):
        recs.append(
            f"NumPy/SciPy を固定したい場合は現在値を控えてください "
            f"(numpy={packages['numpy']}, scipy={packages['scipy']})。"
        )

    return recs


def compute_exit_code(report: dict[str, Any], strict: bool = False) -> int:
    hard_failures = []
    warnings = []

    commands = report["commands"]
    frontend = report["frontend"]
    tracknet = report["tracknet"]
    yolo = report["yolo"]

    if not commands.get("python"):
        hard_failures.append("python")
    if not commands.get("npm"):
        hard_failures.append("npm")
    if not frontend.get("node_modules"):
        warnings.append("node_modules")
    if not tracknet.get("loaded"):
        warnings.append("tracknet")
    if not yolo.get("loaded"):
        warnings.append("yolo")

    if hard_failures:
        return 2
    if strict and warnings:
        return 2
    if warnings:
        return 1
    return 0


def summarize_report(report: dict[str, Any]) -> str:
    tracknet = report["tracknet"]
    yolo = report["yolo"]
    frontend = report["frontend"]
    commands = report["commands"]

    lines = [
        "ShuttleScope Setup Doctor",
        "",
        f"Python:      {'OK' if commands.get('python') else 'MISSING'}",
        f"npm:         {'OK' if commands.get('npm') else 'MISSING'}",
        f"ngrok:       {'OK' if commands.get('ngrok') else 'MISSING'}",
        f"cloudflared: {'OK' if commands.get('cloudflared') else 'MISSING'}",
        f"Frontend:    {'READY' if frontend.get('node_modules') else 'npm install required'}",
        f"TrackNet:    {'READY' if tracknet.get('loaded') else 'NOT READY'}",
        f"YOLO:        {'READY' if yolo.get('loaded') else 'NOT READY'}",
    ]

    if tracknet.get("loaded"):
        lines.append(f"TrackNet backend: {tracknet.get('backend')}")
    elif tracknet.get("error"):
        lines.append(f"TrackNet error: {tracknet.get('error')}")

    if yolo.get("message"):
        lines.append(f"YOLO status: {yolo.get('message')}")

    recs = build_recommendations(report)
    if recs:
        lines.extend(["", "Recommended next steps:"])
        lines.extend([f"- {rec}" for rec in recs])

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ShuttleScope environment doctor")
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat missing optional runtime pieces as blocking",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = build_report()
    report["recommendations"] = build_recommendations(report)
    report["exit_code"] = compute_exit_code(report, strict=args.strict)

    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(summarize_report(report))

    raise SystemExit(report["exit_code"])


if __name__ == "__main__":
    main()
