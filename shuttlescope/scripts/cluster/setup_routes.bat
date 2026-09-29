@echo off
:: ShuttleScope ネットワークルーティング設定
:: クラスタ専用サブネット / フォールバックサブネットへのルートを追加する。
::
:: 環境変数で上書き可能:
::   SS_CLUSTER_GW    : クラスタ向けゲートウェイ IP
::   SS_FALLBACK_GW   : フォールバック向けゲートウェイ IP
::   SS_CLUSTER_SUBNET: クラスタサブネット (デフォルト 192.168.100.0)
::   SS_FALLBACK_SUBNET: フォールバックサブネット (デフォルト 192.168.101.0)
::
:: 注意: 管理者権限が必要です。
:: ────────────────────────────────────────────────────────────────

setlocal

if not defined SS_CLUSTER_SUBNET  set SS_CLUSTER_SUBNET=192.168.100.0
if not defined SS_FALLBACK_SUBNET set SS_FALLBACK_SUBNET=192.168.101.0

:: クラスタ専用サブネット (2.5GbE 直結)
if defined SS_CLUSTER_GW (
    echo [routes] クラスタルート追加: %SS_CLUSTER_SUBNET% via %SS_CLUSTER_GW%
    route add %SS_CLUSTER_SUBNET% mask 255.255.255.0 %SS_CLUSTER_GW% metric 10 >nul 2>&1
    if errorlevel 1 (
        echo [routes] INFO: ルートが既に存在するか追加権限がありません（無視）
    )
)

:: フォールバックサブネット (USB-C) — メトリックを高く設定して優先度を下げる
if defined SS_FALLBACK_GW (
    echo [routes] フォールバックルート追加: %SS_FALLBACK_SUBNET% via %SS_FALLBACK_GW% (metric=100)
    route add %SS_FALLBACK_SUBNET% mask 255.255.255.0 %SS_FALLBACK_GW% metric 100 >nul 2>&1
    if errorlevel 1 (
        echo [routes] INFO: フォールバックルートが既に存在するか追加権限がありません（無視）
    )
)

:: インターフェースメトリック設定 (PowerShell で実行)
:: クラスタ IF: 低メトリック（優先） / フォールバック IF: 高メトリック
if defined SS_CLUSTER_IF (
    echo [routes] クラスタIFメトリック設定: %SS_CLUSTER_IF% = 10
    powershell -NoProfile -Command ^
        "Set-NetIPInterface -InterfaceAlias '%SS_CLUSTER_IF%' -InterfaceMetric 10 -ErrorAction SilentlyContinue"
)
if defined SS_FALLBACK_IF (
    echo [routes] フォールバックIFメトリック設定: %SS_FALLBACK_IF% = 100
    powershell -NoProfile -Command ^
        "Set-NetIPInterface -InterfaceAlias '%SS_FALLBACK_IF%' -InterfaceMetric 100 -ErrorAction SilentlyContinue"
)

echo [routes] ルーティング設定完了
endlocal
