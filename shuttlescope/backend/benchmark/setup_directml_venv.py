"""Radeon / Intel iGPU 向け DirectML 専用 venv セットアップスクリプト。

onnxruntime-directml は onnxruntime-gpu と同一 venv に共存できないため
専用の Python 環境を作成する。

使い方:
    python backend/benchmark/setup_directml_venv.py

作成先: backend/.venv-directml/
"""
import subprocess
import sys
from pathlib import Path

VENV_DIR = Path(__file__).parent.parent / ".venv-directml"
PACKAGES = [
    "onnxruntime-directml>=1.17",
    "numpy",
    "opencv-python-headless",
]


def main() -> None:
    if sys.platform != "win32":
        print("DirectML は Windows 専用です。このスクリプトは Windows でのみ動作します。")
        sys.exit(1)

    print(f"DirectML venv を作成中: {VENV_DIR}")
    subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)

    pip = VENV_DIR / "Scripts" / "pip.exe"
    print("pip をアップグレード中...")
    subprocess.run([str(pip), "install", "--upgrade", "pip"], check=True)
    print(f"パッケージをインストール中: {PACKAGES}")
    subprocess.run([str(pip), "install"] + PACKAGES, check=True)

    python = VENV_DIR / "Scripts" / "python.exe"
    print("\n検証中...")
    result = subprocess.run(
        [str(python), "-c",
         "import onnxruntime as ort; p=ort.get_available_providers(); "
         "print('利用可能 EP:', p); "
         "assert 'DmlExecutionProvider' in p, 'DML が見つかりません'"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(result.stdout.strip())
        print(f"\n完了: {VENV_DIR}")
        print("次回ベンチマーク実行時に iGPU (DirectML) が自動的に使用されます。")
    else:
        print("警告: DmlExecutionProvider が確認できませんでした。")
        print(result.stderr[-500:] if result.stderr else "")


if __name__ == "__main__":
    main()
