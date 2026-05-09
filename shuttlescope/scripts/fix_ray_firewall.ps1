#Requires -Version 5.1
# fix_ray_firewall.ps1 - Add Windows Firewall inbound rules for Ray cluster
# Run as Administrator

$currentPrincipal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    $scriptPath = $MyInvocation.MyCommand.Path
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
    exit
}

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Ray Firewall Setup" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# Round 258 R7 P1 fix (Codex review):
# 旧コードは RemoteAddress = "Any" で Ray ポートを全 IP に開放していた。
# Ray GCS / dashboard / worker port は **無認証** で RCE 可能 (cloudpickle 経由)。
# 「Any」は事実上 anyone-with-network-reach を Ray クラスタの管理者にする。
# 既定はリンクローカル (169.254.0.0/16) のみ。public 公開は SS_RAY_FIREWALL_REMOTE
# 環境変数で上書きを必須化し、ログにも警告を出す。
$RayRemote = if ($env:SS_RAY_FIREWALL_REMOTE) {
    $env:SS_RAY_FIREWALL_REMOTE
} else {
    "169.254.0.0/16"
}

# Round 258 R19 P0 fix (R18a-3 P0-2): 旧コードは Write-Warning で警告のみ、
# そのまま `Any` / `0.0.0.0/0` で New-NetFirewallRule を実行していた。
# Ray GCS / dashboard / worker は **無認証で cloudpickle RCE 可能** な経路で、
# WireGuard / SSH tunnel / Cloudflare Access の背後配置を**実装で強制**する必要がある。
# 修正: `Any` / `0.0.0.0/0` / `::/0` / `*` は throw し、`SS_RAY_FIREWALL_FORCE_PUBLIC=1`
# を別途 set した時のみ警告継続。この env はコード上に残るのでレビュー時に把握できる。
if ($RayRemote -eq "Any" -or $RayRemote -eq "0.0.0.0/0" -or $RayRemote -eq "::/0" -or $RayRemote -eq "*") {
    if ($env:SS_RAY_FIREWALL_FORCE_PUBLIC -eq "1") {
        Write-Warning "[Ray firewall] RemoteAddress=$RayRemote (FORCE_PUBLIC=1)"
        Write-Warning "[Ray firewall] Ray は無認証で RCE 可能です。WireGuard / Cloudflare Access / SSH tunnel の背後でのみ運用してください。"
    } else {
        throw "[Ray firewall] RemoteAddress=$RayRemote は public 公開を意味します。Ray は無認証で RCE 可能です。本当に必要なら SS_RAY_FIREWALL_FORCE_PUBLIC=1 を明示的に set してから再実行してください。"
    }
}

$rules = @(
    @{
        Name          = "ShuttleScope-Ray-GCS-TCP-6379"
        DisplayName   = "ShuttleScope Ray GCS TCP 6379"
        Protocol      = "TCP"
        LocalPort     = "6379"
        RemoteAddress = $RayRemote
        Description   = "Ray GCS server (Round 258 R7: no-auth; restrict to link-local)"
    },
    @{
        Name          = "ShuttleScope-Ray-Dashboard-TCP-8265"
        DisplayName   = "ShuttleScope Ray Dashboard TCP 8265"
        Protocol      = "TCP"
        LocalPort     = "8265"
        RemoteAddress = $RayRemote
        Description   = "Ray Dashboard (Round 258 R7: no-auth; restrict to link-local)"
    },
    @{
        Name          = "ShuttleScope-Ray-Workers-TCP-10000-10999"
        DisplayName   = "ShuttleScope Ray Workers TCP 10000-10999"
        Protocol      = "TCP"
        LocalPort     = "10000-10999"
        RemoteAddress = $RayRemote
        Description   = "Ray worker communication (Round 258 R7: restrict to link-local)"
    }
)

foreach ($rule in $rules) {
    $existing = Get-NetFirewallRule -Name $rule.Name -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Host "[SKIP]  $($rule.DisplayName) already exists." -ForegroundColor Green
    } else {
        Write-Host "[ADD]   $($rule.DisplayName) ..." -ForegroundColor Yellow
        try {
            New-NetFirewallRule `
                -Name          $rule.Name `
                -DisplayName   $rule.DisplayName `
                -Description   $rule.Description `
                -Direction     Inbound `
                -Protocol      $rule.Protocol `
                -LocalPort     $rule.LocalPort `
                -RemoteAddress $rule.RemoteAddress `
                -Action        Allow `
                -Enabled       True `
                -Profile       Any | Out-Null
            Write-Host "[OK]    $($rule.DisplayName) added." -ForegroundColor Green
        } catch {
            Write-Host "[ERROR] $($rule.DisplayName) failed: $_" -ForegroundColor Red
        }
    }
}

$icmpName = "ShuttleScope-ICMP-Echo-Request"
$existingIcmp = Get-NetFirewallRule -Name $icmpName -ErrorAction SilentlyContinue
if ($existingIcmp) {
    Write-Host "[SKIP]  ICMP Echo Request already exists." -ForegroundColor Green
} else {
    Write-Host "[ADD]   ICMP Echo Request (ping) ..." -ForegroundColor Yellow
    try {
        New-NetFirewallRule `
            -Name          $icmpName `
            -DisplayName   "ShuttleScope ICMP Echo Request" `
            -Description   "Ray cluster ping" `
            -Direction     Inbound `
            -Protocol      ICMPv4 `
            -IcmpType      8 `
            -RemoteAddress "169.254.0.0/16" `
            -Action        Allow `
            -Enabled       True `
            -Profile       Any | Out-Null
        Write-Host "[OK]    ICMP rule added." -ForegroundColor Green
    } catch {
        Write-Host "[ERROR] ICMP rule failed: $_" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "--- Current ShuttleScope rules ---" -ForegroundColor Cyan
$allNames = ($rules | ForEach-Object { $_.Name }) + @($icmpName)
foreach ($name in $allNames) {
    $r = Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue
    if ($r) {
        Write-Host "  [OK] $($r.DisplayName)" -ForegroundColor Green
    } else {
        Write-Host "  [MISSING] $name" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Done. No Ray restart needed." -ForegroundColor Green
Write-Host "Run this script on K10 as well." -ForegroundColor Yellow
Write-Host ""
Read-Host "Press Enter to exit"
