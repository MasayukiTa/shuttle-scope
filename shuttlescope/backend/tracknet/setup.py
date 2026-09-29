"""TrackNet setup script.

Usage:
  python -m backend.tracknet.setup download
  python -m backend.tracknet.setup export
  python -m backend.tracknet.setup convert
  python -m backend.tracknet.setup all

`download` fetches the real public badminton checkpoint from a pinned upstream
commit of:
  https://github.com/Chang-Chia-Chi/TrackNet-Badminton-Tracking-tensorflow2
and verifies SHA256 before Keras is allowed to read the checkpoint bytes.

`export` converts that TensorFlow checkpoint into ONNX so ShuttleScope can run
it through onnxruntime and, optionally, OpenVINO.
"""

from __future__ import annotations

import hashlib
import http.client
import sys
import urllib.parse
from pathlib import Path

WEIGHTS_DIR = Path(__file__).parent / "weights"
WEIGHTS_DIR.mkdir(exist_ok=True)

TF_INDEX_PATH = WEIGHTS_DIR / "TrackNet.index"
TF_DATA_PATH = WEIGHTS_DIR / "TrackNet.data-00000-of-00001"
ONNX_PATH = WEIGHTS_DIR / "tracknet.onnx"
OV_XML = WEIGHTS_DIR / "tracknet.xml"

UPSTREAM_COMMIT = "d13eb075c7efcca25ede62ac4a21e18891c2f49b"  # DevSkim: ignore DS173237 -- public git commit, not a credential
TRUSTED_WEIGHT_SCHEME = "https"
TRUSTED_WEIGHT_HOST = "raw.githubusercontent.com"
TRUSTED_WEIGHT_PATH_PREFIX = (
    "/Chang-Chia-Chi/TrackNet-Badminton-Tracking-tensorflow2/"
    f"{UPSTREAM_COMMIT}/weights/"
)
BASE_URL = (
    f"{TRUSTED_WEIGHT_SCHEME}://{TRUSTED_WEIGHT_HOST}"
    f"{TRUSTED_WEIGHT_PATH_PREFIX.rstrip('/')}"
)
TRUSTED_WEIGHT_PATHS = {
    f"{TRUSTED_WEIGHT_PATH_PREFIX}TrackNet.index",
    f"{TRUSTED_WEIGHT_PATH_PREFIX}TrackNet.data-00000-of-00001",
}
WEIGHT_SOURCES = {
    TF_INDEX_PATH: {
        "url": f"{BASE_URL}/TrackNet.index",
        "sha256": "6291bee8498978e171ef7dc5464930b1a10f5d24236b2b763693a6c911818d6c",  # DevSkim: ignore DS173237 -- public SHA256 checksum
    },
    TF_DATA_PATH: {
        "url": f"{BASE_URL}/TrackNet.data-00000-of-00001",
        "sha256": "57abcbe67daadcc8dca63418afd7200ab105f226c4fd55f9713d92fe72e80025",  # DevSkim: ignore DS173237 -- public SHA256 checksum
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _matches_expected_hash(path: Path, expected_sha256: str) -> bool:
    return path.exists() and _sha256(path) == expected_sha256


def _validated_weight_url(url: str) -> str:
    """Return only the exact HTTPS upstream checkpoint URLs we permit."""
    parsed = urllib.parse.urlsplit(url)
    if (
        parsed.scheme != TRUSTED_WEIGHT_SCHEME
        or parsed.hostname != TRUSTED_WEIGHT_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.query
        or parsed.fragment
        or parsed.path not in TRUSTED_WEIGHT_PATHS
    ):
        raise ValueError(f"Untrusted TrackNet checkpoint URL: {url!r}")
    return url


def _download_weight(url: str, destination: Path) -> None:
    """Download one allowlisted checkpoint object over verified HTTPS."""
    parsed = urllib.parse.urlsplit(_validated_weight_url(url))
    connection = http.client.HTTPSConnection(TRUSTED_WEIGHT_HOST, 443, timeout=30)
    try:
        connection.request(
            "GET",
            parsed.path,
            headers={"User-Agent": "ShuttleScope-TrackNet-Setup/1"},
        )
        response = connection.getresponse()
        if response.status != 200:
            raise RuntimeError(
                f"TrackNet checkpoint download failed: HTTP {response.status} "
                f"{response.reason}"
            )
        with destination.open("wb") as fh:
            while chunk := response.read(1024 * 1024):
                fh.write(chunk)
    finally:
        connection.close()


def cmd_download():
    for target, source in WEIGHT_SOURCES.items():
        url = _validated_weight_url(source["url"])
        expected_sha256 = source["sha256"]

        if _matches_expected_hash(target, expected_sha256):
            print(f"[skip] {target.name} already verified")
            continue

        if target.exists():
            print(f"[warn] {target.name} hash mismatch; replacing cached file")
            target.unlink()

        tmp = target.with_name(target.name + ".part")
        tmp.unlink(missing_ok=True)
        print(f"Downloading {target.name} from pinned upstream commit ...")
        try:
            _download_weight(url, tmp)
            actual_sha256 = _sha256(tmp)
            if actual_sha256 != expected_sha256:
                raise RuntimeError(
                    f"SHA256 mismatch for {target.name}: "
                    f"expected {expected_sha256}, got {actual_sha256}"
                )
            tmp.replace(target)
        except Exception:
            tmp.unlink(missing_ok=True)
            raise
        print(f"[ok] Verified and saved to {target}")


def cmd_export():
    # Always verify cached checkpoint bytes before Keras reads them. Matching
    # files are a cheap hash-only no-op; missing/corrupt files are re-fetched.
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
    restore_status = model.load_weights(str(TF_INDEX_PATH.with_suffix("")))
    restore_status.assert_existing_objects_matched()
    restore_status.expect_partial()
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
