# fix_ray_firewall.ps1
# Ray クラスタ用 Windows Firewall インバウンドルールを追加するスクリプト。
# 管理者権限が必要。未昇格で実行した場合は自動で UAC 昇格を試みる。

#Requires -Version 5.1

# ── 自己昇格 ──────────────────────────────────────────────────────────────────
$currentPrincipal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "管理者権限が必要です。UAC 昇格を試みます..." -ForegroundColor Yellow
    $scriptPath = $MyInvocation.MyCommand.Path
    Start-Process powershell.exe -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`""
    exit
}

Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  Ray Firewall ルール設定スクリプト" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""

# ── ルール定義 ────────────────────────────────────────────────────────────────
# Name, Protocol, LocalPort, RemoteAddress, Description
$rules = @(
    @{
        Name        = "ShuttleScope-Ray-GCS-TCP-6379"
        DisplayName = "ShuttleScope Ray GCS (TCP 6379)"
        Protocol    = "TCP"
        LocalPort   = "6379"
        RemoteAddress = "169.254.0.0/16"
        Description = "Ray GCS サーバー (クラスタ内部通信)"
    },
    @{
        Name        = "ShuttleScope-Ray-Dashboard-TCP-8265"
        DisplayName = "ShuttleScope Ray Dashboard (TCP 8265)"
        Protocol    = "TCP"
        LocalPort   = "8265"
        RemoteAddress = "Any"
        Description = "Ray Dashboard ポート"
    },
    @{
        Name        = "ShuttleScope-Ray-Workers-TCP-10000-10999"
        DisplayName = "ShuttleScope Ray Workers (TCP 10000-10999)"
        Protocol    = "TCP"
        LocalPort   = "10000-10999"
        RemoteAddress = "Any"
        Description = "Ray ワーカー間通信ポート"
    }
)

# ── ICMP (ping) ルール ────────────────────────────────────────────────────────
$icmpRuleName = "ShuttleScope-ICMP-Echo-Request"

# ── 各ルールを確認・追加 ──────────────────────────────────────────────────────
foreach ($rule in $rules) {
    $existing = Get-NetFirewallRule -Name $rule.Name -ErrorAction SilentlyContinue

    if ($existing) {
        Write-Host "[スキップ] ルール '$($rule.DisplayName)' は既に存在します。" -ForegroundColor Green
    } else {
        Write-Host "[追加中]  '$($rule.DisplayName)' ..." -ForegroundColor Yellow
        try {
            New-NetFirewallRule `
                -Name        $rule.Name `
                -DisplayName $rule.DisplayName `
                -Description $rule.Description `
                -Direction   Inbound `
                -Protocol    $rule.Protocol `
                -LocalPort   $rule.LocalPort `
                -RemoteAddress $rule.RemoteAddress `
                -Action      Allow `
                -Enabled     True `
                -Profile     Any | Out-Null
            Write-Host "[完了]    '$($rule.DisplayName)' を追加しました。" -ForegroundColor Green
        } catch {
            Write-Host "[エラー]  '$($rule.DisplayName)' の追加に失敗しました: $_" -ForegroundColor Red
        }
    }
}

# ── ICMP (ping) ルール ────────────────────────────────────────────────────────
$existingIcmp = Get-NetFirewallRule -Name $icmpRuleName -ErrorAction SilentlyContinue

if ($existingIcmp) {
    Write-Host "[スキップ] ICMP Echo Request ルールは既に存在します。" -ForegroundColor Green
} else {
    Write-Host "[追加中]  ICMP Echo Request (ping) ..." -ForegroundColor Yellow
    try {
        New-NetFirewallRule `
            -Name        $icmpRuleName `
            -DisplayName "ShuttleScope ICMP Echo Request (ping)" `
            -Description "Ray クラスタ内 ping 疎通確認用" `
            -Direction   Inbound `
            -Protocol    ICMPv4 `
            -IcmpType    8 `
            -RemoteAddress "169.254.0.0/16" `
            -Action      Allow `
            -Enabled     True `
            -Profile     Any | Out-Null
        Write-Host "[完了]    ICMP Echo Request ルールを追加しました。" -ForegroundColor Green
    } catch {
        Write-Host "[エラー]  ICMP ルールの追加に失敗しました: $_" -ForegroundColor Red
    }
}

# ── 現在のルール一覧を表示 ────────────────────────────────────────────────────
Write-Host ""
Write-Host "── 現在の ShuttleScope Ray ファイアウォールルール ──" -ForegroundColor Cyan
$allRuleNames = ($rules | ForEach-Object { $_.Name }) + @($icmpRuleName)
foreach ($name in $allRuleNames) {
    $r = Get-NetFirewallRule -Name $name -ErrorAction SilentlyContinue
    if ($r) {
        $enabled = if ($r.Enabled) { "有効" } else { "無効" }
        Write-Host "  [$enabled] $($r.DisplayName)" -ForegroundColor $(if ($r.Enabled) { "Green" } else { "Red" })
    } else {
        Write-Host "  [未設定] $name" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "======================================" -ForegroundColor Cyan
Write-Host "  設定完了" -ForegroundColor Cyan
Write-Host "======================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "注意: Ray の再起動は不要です。" -ForegroundColor Yellow
Write-Host "      既に Ray が起動している場合は、接続を再試行してください。" -ForegroundColor Yellow
Write-Host ""
Write-Host "次のステップ:" -ForegroundColor White
Write-Host "  1. K10 でも同様にこのスクリプトを実行してください。" -ForegroundColor White
Write-Host "  2. ShuttleScope の『Ray起動』ボタンを押して接続を確認してください。" -ForegroundColor White
Write-Host ""

Read-Host "Enterキーを押して終了..."
