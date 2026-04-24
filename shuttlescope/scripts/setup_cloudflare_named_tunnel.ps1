param(
    [string]$TunnelName = "shuttlescope",
    [string]$Hostname = "app.shuttle-scope.com"
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "== $Message ==" -ForegroundColor Cyan
}

$root = Split-Path -Parent $PSScriptRoot
$template = Join-Path $root "infra\cloudflared\config.yml"
$cfHome = Join-Path $env:USERPROFILE ".cloudflared"

Write-Step "Checking cloudflared"
$cf = Get-Command cloudflared -ErrorAction SilentlyContinue
if (-not $cf) {
    throw "cloudflared が見つかりません。先にインストールしてください。"
}

New-Item -ItemType Directory -Force -Path $cfHome | Out-Null

Write-Step "Checking Cloudflare login"
$certPath = Join-Path $cfHome "cert.pem"
if (-not (Test-Path $certPath)) {
    Write-Host "Cloudflare ログインを開始します。ブラウザ承認が必要です..." -ForegroundColor Yellow
    & $cf.Source tunnel login
}

Write-Step "Creating or locating named tunnel"
$listOutput = & $cf.Source tunnel list 2>&1
$uuid = $null
foreach ($line in $listOutput) {
    if ($line -match "([0-9a-f]{8}-[0-9a-f-]{27,})" -and $line -match $TunnelName) {
        $uuid = $matches[1]
        break
    }
}

if (-not $uuid) {
    $createOutput = & $cf.Source tunnel create $TunnelName 2>&1
    foreach ($line in $createOutput) {
        if ($line -match "([0-9a-f]{8}-[0-9a-f-]{27,})") {
            $uuid = $matches[1]
            break
        }
    }
}

if (-not $uuid) {
    throw "トンネル UUID を取得できませんでした。cloudflared tunnel create の出力を確認してください。"
}

$credPath = Join-Path $cfHome "$uuid.json"
if (-not (Test-Path $credPath)) {
    throw "credentials ファイルが見つかりません: $credPath"
}

Write-Step "Writing config.yml"
$configText = Get-Content $template -Raw
$configText = $configText.Replace("<UUID>", $uuid)
$configText = $configText.Replace("<USER>", $env:USERNAME)
$configText = $configText.Replace("app.shuttle-scope.com", $Hostname)
$configPath = Join-Path $cfHome "config.yml"
Set-Content -Path $configPath -Value $configText -Encoding UTF8

Write-Step "Routing DNS (app)"
& $cf.Source tunnel route dns $TunnelName $Hostname

Write-Step "Routing DNS (ssh)"
$sshHostname = "ssh.shuttle-scope.com"
& $cf.Source tunnel route dns $TunnelName $sshHostname

Write-Step "Done"
Write-Host "Config: $configPath" -ForegroundColor Green
Write-Host "Tunnel: $TunnelName ($uuid)" -ForegroundColor Green
Write-Host "App  : https://$Hostname" -ForegroundColor Green
Write-Host "SSH  : $sshHostname (Cloudflare Tunnel 経由)" -ForegroundColor Green
Write-Host ""
Write-Host "次のどちらかで起動してください:"
Write-Host "  1. cloudflared tunnel --config `"$configPath`" run"
Write-Host "  2. cloudflared service install"
Write-Host ""
Write-Host "SSH 接続前に OpenSSH Server のセットアップも必要:"
Write-Host "  管理者 PS で: .\infra\ssh\server-setup.ps1"
