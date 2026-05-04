"""TrackNet setup script.

Usage:
  python -m backend.tracknet.setup download
  python -m backend.tracknet.setup export
  python -m backend.tracknet.setup convert
  python -m backend.tracknet.setup all

`download` fetches the real public badminton checkpoint from:
  https://github.com/Chang-Chia-Chi/TrackNet-Badminton-Tracking-tensorflow2

`export` converts that TensorFlow checkpoint into ONNX so ShuttleScope can run
it through onnxruntime and, optionally, OpenVINO.
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

WEIGHTS_DIR = Path(__file__).parent / "weights"
WEIGHTS_DIR.mkdir(exist_ok=True)

TF_INDEX_PATH = WEIGHTS_DIR / "TrackNet.index"
TF_DATA_PATH = WEIGHTS_DIR / "TrackNet.data-00000-of-00001"
ONNX_PATH = WEIGHTS_DIR / "tracknet.onnx"
OV_XML = WEIGHTS_DIR / "tracknet.xml"

BASE_URL = "https://raw.githubusercontent.com/Chang-Chia-Chi/TrackNet-Badminton-Tracking-tensorflow2/main/weights"
WEIGHT_URLS = {
    TF_INDEX_PATH: f"{BASE_URL}/TrackNet.index",
    TF_DATA_PATH: f"{BASE_URL}/TrackNet.data-00000-of-00001",
}


def cmd_download():
    for target, url in WEIGHT_URLS.items():
        if target.exists():
            print(f"[skip] {target.name} already exists")
            continue
        print(f"Downloading {target.name} ...")
        urllib.request.urlretrieve(url, target)
        print(f"[ok] Saved to {target}")


def cmd_export():
    if not TF_INDEX_PATH.exists() or not TF_DATA_PATH.exists():
        print("[info] TensorFlow checkpoint missing — auto-downloading first")
        cmd_download()
    if not TF_INDEX_PATH.exists() or not TF_DATA_PATH.exists():
        print("[error] TensorFlow checkpoint still not found after download")
        print("Run: python -m backend.tracknet.setup download")
        sys.exit(1)

    try:
        import tensorflow as tf
        import tf2onnx
        from backend.tracknet.model import build_tracknet_model
    except ImportError as exc:
        print(f"[error] Missing dependency: {exc}")
        print("Install optional deps, for example:")
        print("  pip install tensorflow tf2onnx onnxruntime opencv-python")
        sys.exit(1)

    model = build_tracknet_model()
    model.load_weights(str(TF_INDEX_PATH.with_suffix(""))).expect_partial()
    signature = (tf.TensorSpec((None, 3, 288, 512), tf.float32, name="input"),)

    print(f"Exporting ONNX to {ONNX_PATH} ...")
    tf2onnx.convert.from_keras(model, input_signature=signature, opset=13, output_path=str(ONNX_PATH))
    print(f"[ok] ONNX saved to {ONNX_PATH}")


def cmd_convert():
    if not ONNX_PATH.exists():
        print(f"[error] ONNX model not found: {ONNX_PATH}")
        print("Run: python -m backend.tracknet.setup export")
        sys.exit(1)

    try:
        from openvino.tools.mo import convert_model
        from openvino.runtime import serialize
    except ImportError:
        try:
            import subprocess

            result = subprocess.run(
                ["mo", "--input_model", str(ONNX_PATH), "--output_dir", str(WEIGHTS_DIR), "--model_name", "tracknet"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                print(f"[ok] OpenVINO IR saved to {WEIGHTS_DIR}")
                return
            print(f"[error] mo failed:\n{result.stderr}")
            sys.exit(result.returncode)
        except FileNotFoundError:
            print("[error] OpenVINO not found. Install: pip install openvino")
            sys.exit(1)

    print("Converting ONNX to OpenVINO IR ...")
    ov_model = convert_model(str(ONNX_PATH))
    serialize(ov_model, str(OV_XML))
    print(f"[ok] OpenVINO IR saved to {OV_XML}")


def cmd_all():
    cmd_download()
    cmd_export()
    try:
        cmd_convert()
    except SystemExit:
        print("[warn] OpenVINO conversion was skipped")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]
    commands = {
        "download": cmd_download,
        "export": cmd_export,
        "convert": cmd_convert,
        "all": cmd_all,
    }
    if cmd not in commands:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
    commands[cmd]()


if __name__ == "__main__":
    main()
