#!/usr/bin/env bash
# ShuttleScope PM2 セットアップ (Ubuntu / WSL)
# 使い方: bash scripts/setup_pm2.sh
set -euo pipefail

echo "[ShuttleScope] PM2 セットアップ (Ubuntu)"

if ! command -v node >/dev/null 2>&1; then
    echo "Node.js を導入します (NodeSource LTS)"
    curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
    sudo apt-get install -y nodejs
fi

if ! command -v pm2 >/dev/null 2>&1; then
    sudo npm install -g pm2
else
    echo "pm2 は既に導入済み"
fi

# 現ユーザーでの systemd 起動スクリプトを生成
pm2 startup systemd -u "$USER" --hp "$HOME" | tail -n 1 | sudo bash || true

echo "ecosystem 起動例:"
echo "  pm2 start scripts/pm2/ecosystem.config.js"
echo "  pm2 save"

echo "[ShuttleScope] 完了"
