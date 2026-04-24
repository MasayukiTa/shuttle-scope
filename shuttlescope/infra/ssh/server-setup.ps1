<#
.SYNOPSIS
    本番サーバー（自宅 PC）で一回だけ実行する OpenSSH Server セットアップ

.DESCRIPTION
    - OpenSSH Server をインストール・起動・自動起動設定
    - ファイアウォールでポート 22 を許可（LAN のみ。外部は Cloudflare Tunnel 経由）
    - 管理者権限で実行すること

.EXAMPLE
    # 管理者 PowerShell で
    Set-ExecutionPolicy Bypass -Scope Process
    .\infra\ssh\server-setup.ps1
#>

$ErrorActionPreference = "Stop"

function Step([string]$msg) { Write-Host "`n== $msg ==" -ForegroundColor Cyan }

# 管理者チェック
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "管理者権限で実行してください"
}

# ── 1. OpenSSH Server インストール ────────────────────────────────────────────
Step "Installing OpenSSH Server"
$cap = Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*'
if ($cap.State -ne 'Installed') {
    Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0
    Write-Host "  installed" -ForegroundColor Green
} else {
    Write-Host "  already installed" -ForegroundColor Yellow
}

# ── 2. サービス起動 + 自動起動 ───────────────────────────────────────────────
Step "Starting sshd service"
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd
$svc = Get-Service sshd
Write-Host "  sshd: $($svc.Status)" -ForegroundColor Green

# ── 3. ファイアウォール（LAN 内のみ許可） ────────────────────────────────────
Step "Firewall rule for SSH (LAN only)"
$existingRule = Get-NetFirewallRule -Name "OpenSSH-Server-In-TCP" -ErrorAction SilentlyContinue
if ($existingRule) {
    Write-Host "  rule already exists — skipping" -ForegroundColor Yellow
} else {
    New-NetFirewallRule `
        -Name "OpenSSH-Server-In-TCP" `
        -DisplayName "OpenSSH Server (TCP-In)" `
        -Enabled True `
        -Direction Inbound `
        -Protocol TCP `
        -Action Allow `
        -LocalPort 22 | Out-Null
    Write-Host "  rule created" -ForegroundColor Green
}

# ── 4. 確認 ──────────────────────────────────────────────────────────────────
Step "Verification"
Write-Host "  sshd status : $(( Get-Service sshd ).Status)"
Write-Host "  listening   : $(netstat -ano | Select-String ':22 ')"
Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "次のステップ: cloudflared tunnel route dns shuttlescope ssh.shuttle-scope.com" -ForegroundColor Cyan
