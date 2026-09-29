#!/bin/bash
# バックエンド仮想環境セットアップスクリプト

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== ShuttleScope バックエンドセットアップ ==="

# 仮想環境の作成
cd "$SCRIPT_DIR"
python -m venv .venv
echo "仮想環境を作成しました: $SCRIPT_DIR/.venv"

# 仮想環境を有効化してパッケージをインストール
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "win32" ]]; then
    source .venv/Scripts/activate
else
    source .venv/bin/activate
fi

pip install --upgrade pip
pip install -r requirements.txt

echo ""
echo "=== セットアップ完了 ==="
echo "バックエンドの起動方法:"
echo "  cd backend && python main.py"
echo ""
