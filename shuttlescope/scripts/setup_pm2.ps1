# ShuttleScope PM2 セットアップ (Windows)
# 明示実行しない限り開発機への影響ゼロ。
# 使い方:
#   powershell -ExecutionPolicy Bypass -File scripts\setup_pm2.ps1

[CmdletBinding()]
param(
    [ValidateSet('nssm','wsl','pm2-only')]
    [string]$Mode = 'pm2-only'
)

Write-Host "[ShuttleScope] PM2 セットアップ (Mode=$Mode)" -ForegroundColor Cyan

# 1. Node / npm 確認
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Error "Node.js が見つかりません。https://nodejs.org/ から LTS を導入してください。"
    exit 1
}

# 2. pm2 をグローバル導入 (既に入っていれば skip)
if (-not (Get-Command pm2 -ErrorAction SilentlyContinue)) {
    Write-Host "pm2 をグローバルインストール..."
    npm install -g pm2
} else {
    Write-Host "pm2 は既に導入済み"
}

switch ($Mode) {
    'pm2-only' {
        Write-Host "pm2 のみ導入しました。手動起動例:"
        Write-Host "  pm2 start scripts\pm2\ecosystem.config.js"
        Write-Host "  pm2 save"
    }
    'nssm' {
        # NSSM で pm2-runtime をサービス化 (pm2-windows-service は保守停止のため非推奨)
        if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
            Write-Error "NSSM がありません。choco install nssm または公式 zip を導入してください。"
            exit 1
        }
        $cwd = (Get-Location).Path
        $eco = Join-Path $cwd 'scripts\pm2\ecosystem.config.js'
        nssm install ShuttleScopePM2 (Get-Command pm2-runtime).Source $eco
        nssm set ShuttleScopePM2 AppDirectory $cwd
        nssm set ShuttleScopePM2 Start SERVICE_AUTO_START
        Write-Host "サービス 'ShuttleScopePM2' を登録しました。開始: Start-Service ShuttleScopePM2"
    }
    'wsl' {
        Write-Host "WSL 経由で運用する場合は WSL 内で scripts/setup_pm2.sh を実行してください。"
    }
}

Write-Host "[ShuttleScope] 完了" -ForegroundColor Green
