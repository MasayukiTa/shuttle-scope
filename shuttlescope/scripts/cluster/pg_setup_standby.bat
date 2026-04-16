@echo off
:: ShuttleScope PostgreSQL スタンバイ初期設定 (PC2 で実行)
::
:: 実行タイミング: プライマリ (PC1) のセットアップ完了後
:: 事前準備:
::   1. PostgreSQL 15 or 16 をインストール済みであること
::   2. SS_PRIMARY_IP にプライマリのクラスタIPを設定すること
::   3. 管理者権限で実行すること
::
:: 実行内容:
::   - pg_basebackup でプライマリからベースバックアップを取得
::   - standby.signal を配置してスタンバイモードで起動
:: ────────────────────────────────────────────────────────────────

setlocal EnableDelayedExpansion

if not defined SS_PRIMARY_IP (
    echo ERROR: SS_PRIMARY_IP が未設定です
    echo 例: set SS_PRIMARY_IP=192.168.100.1
    exit /b 1
)

if not defined PG_VERSION set PG_VERSION=16
set "PG_BIN=%ProgramFiles%\PostgreSQL\%PG_VERSION%\bin"
if not exist "%PG_BIN%\pg_basebackup.exe" (
    set PG_VERSION=15
    set "PG_BIN=%ProgramFiles%\PostgreSQL\15\bin"
)
if not exist "%PG_BIN%\pg_basebackup.exe" (
    echo ERROR: pg_basebackup が見つかりません。PostgreSQL をインストールしてください。
    exit /b 1
)

if not defined PG_DATA (
    set "PG_DATA=%ProgramData%\PostgreSQL\%PG_VERSION%\data"
)
if not defined SS_REPL_PASSWORD set SS_REPL_PASSWORD=repl_pass

echo [pg_standby] プライマリ: %SS_PRIMARY_IP%
echo [pg_standby] データディレクトリ: %PG_DATA%

:: ── 既存データディレクトリをバックアップ ──────────────────────
if exist "%PG_DATA%" (
    echo [pg_standby] 既存データを退避します...
    set "PG_DATA_BAK=%PG_DATA%.bak_%DATE:~0,4%%DATE:~5,2%%DATE:~8,2%"
    ren "%PG_DATA%" "!PG_DATA_BAK:~-20!" 2>nul || (
        echo [pg_standby] WARN: データディレクトリの退避に失敗。手動で移動してください。
        exit /b 1
    )
)

:: ── pg_basebackup でプライマリからバックアップ取得 ─────────────
echo [pg_standby] プライマリからベースバックアップを取得...
set PGPASSWORD=%SS_REPL_PASSWORD%
"%PG_BIN%\pg_basebackup.exe" ^
    -h %SS_PRIMARY_IP% ^
    -U replicator ^
    -D "%PG_DATA%" ^
    -P -Xs -R ^
    --checkpoint=fast
if errorlevel 1 (
    echo [pg_standby] ERROR: pg_basebackup が失敗しました
    exit /b 1
)

:: ── PostgreSQL を起動（スタンバイモード） ─────────────────────
echo [pg_standby] スタンバイとして PostgreSQL を起動...
"%PG_BIN%\pg_ctl.exe" start -D "%PG_DATA%" -l "%TEMP%\pg_standby_start.log"
timeout /t 5 /nobreak >nul

echo [pg_standby] ══════════════════════════════════
echo [pg_standby] スタンバイ設定完了
echo [pg_standby]   プライマリ: %SS_PRIMARY_IP%
echo [pg_standby]   モード: hot standby (読み取り専用)
echo [pg_standby]
echo [pg_standby] フェイルオーバーが必要になった場合:
echo [pg_standby]   scripts\cluster\failover_promote.bat を実行
echo [pg_standby] ══════════════════════════════════

endlocal
