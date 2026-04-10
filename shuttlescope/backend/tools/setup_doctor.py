"""Environment doctor for easier device bootstrap.

Usage:
  python -m backend.tools.setup_doctor
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path


def _package_version(name: str) -> str | None:
    try:
        from importlib.metadata import version

        return version(name)
    except Exception:
        return None


def _error_payload(stage: str, exc: Exception) -> dict:
    return {
        "available": False,
        "loaded": False,
        "backend": None,
        "error_stage": stage,
        "error": str(exc),
    }


def _tracknet_status() -> dict:
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


def _yolo_status() -> dict:
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


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    frontend_root = root

    report = {
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

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
