"""TrackNet V2 ウェイト取得・変換スクリプト

使い方:
  # 1. ウェイトをダウンロード（要インターネット）
  python -m backend.tracknet.setup download

  # 2. PyTorch → ONNX に変換（要 torch）
  python -m backend.tracknet.setup export

  # 3. ONNX → OpenVINO IR に変換（要 openvino）
  python -m backend.tracknet.setup convert

  # 全工程一括
  python -m backend.tracknet.setup all

ウェイトについて:
  TrackNetV2 の事前学習済みウェイトは Chang-Chia-Chi/TrackNet (MIT) の
  GitHub Releases で公開されています。
  商用配布を行う場合は自前でデータセットから再学習することを推奨します。

  手動配置の場合:
    backend/tracknet/weights/tracknet_v2.pt  を置いてから
    python -m backend.tracknet.setup export
    を実行してください。
"""
import sys
import urllib.request
from pathlib import Path

WEIGHTS_DIR = Path(__file__).parent / "weights"
WEIGHTS_DIR.mkdir(exist_ok=True)

PT_PATH   = WEIGHTS_DIR / "tracknet_v2.pt"
ONNX_PATH = WEIGHTS_DIR / "tracknet_v2.onnx"
OV_XML    = WEIGHTS_DIR / "tracknet_v2.xml"

# Chang-Chia-Chi/TrackNet Releases からダウンロード
# ※ URL は最新リリースに合わせて更新してください
WEIGHT_URL = (
    "https://github.com/Chang-Chia-Chi/TrackNet/releases/download/"
    "v1.0/TrackNet_best.pt"
)


def cmd_download():
    if PT_PATH.exists():
        print(f"[skip] {PT_PATH} already exists")
        return
    print(f"Downloading weights from {WEIGHT_URL} ...")
    try:
        urllib.request.urlretrieve(WEIGHT_URL, PT_PATH)
        print(f"[ok] Saved to {PT_PATH}")
    except Exception as e:
        print(f"[error] Download failed: {e}")
        print("Please manually place the weights at:")
        print(f"  {PT_PATH}")
        sys.exit(1)


def cmd_export():
    """PyTorch → ONNX"""
    if not PT_PATH.exists():
        print(f"[error] Weights not found: {PT_PATH}")
        print("Run: python -m backend.tracknet.setup download")
        sys.exit(1)

    try:
        import torch
        from backend.tracknet.model import TrackNetV2
    except ImportError as e:
        print(f"[error] {e}")
        print("torch が必要です: pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu")
        sys.exit(1)

    print("Loading PyTorch model ...")
    model = TrackNetV2()
    state = torch.load(PT_PATH, map_location="cpu")
    # state_dict のキーが異なる可能性があるため、柔軟に対応
    if "model_state_dict" in state:
        state = state["model_state_dict"]
    elif "state_dict" in state:
        state = state["state_dict"]
    model.load_state_dict(state, strict=False)
    model.eval()

    dummy = torch.zeros(1, 9, 288, 512)
    print(f"Exporting to ONNX: {ONNX_PATH}")
    torch.onnx.export(
        model, dummy, str(ONNX_PATH),
        input_names=["input"], output_names=["output"],
        opset_version=12,
        dynamic_axes={"input": {0: "batch"}, "output": {0: "batch"}},
    )
    print(f"[ok] ONNX saved to {ONNX_PATH}")


def cmd_convert():
    """ONNX → OpenVINO IR"""
    if not ONNX_PATH.exists():
        print(f"[error] ONNX model not found: {ONNX_PATH}")
        print("Run: python -m backend.tracknet.setup export")
        sys.exit(1)

    try:
        from openvino.tools.mo import convert_model
        from openvino.runtime import serialize
    except ImportError:
        try:
            # 新 API (openvino >= 2024)
            import subprocess
            result = subprocess.run(
                ["mo", "--input_model", str(ONNX_PATH),
                 "--output_dir", str(WEIGHTS_DIR),
                 "--model_name", "tracknet_v2"],
                capture_output=True, text=True,
            )
            if result.returncode == 0:
                print(f"[ok] OpenVINO IR saved to {WEIGHTS_DIR}")
            else:
                print(f"[error] mo failed:\n{result.stderr}")
            return
        except FileNotFoundError:
            print("[error] OpenVINO not found. Install: pip install openvino")
            return

    print(f"Converting ONNX → OpenVINO IR ...")
    ov_model = convert_model(str(ONNX_PATH))
    serialize(ov_model, str(OV_XML))
    print(f"[ok] OpenVINO IR saved to {OV_XML}")


def cmd_all():
    cmd_download()
    cmd_export()
    cmd_convert()


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    cmd = sys.argv[1]
    {"download": cmd_download, "export": cmd_export,
     "convert": cmd_convert, "all": cmd_all}.get(cmd, lambda: print(f"Unknown command: {cmd}"))()


if __name__ == "__main__":
    main()
