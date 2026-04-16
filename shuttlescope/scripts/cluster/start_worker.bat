@echo off
:: ShuttleScope クラスタ起動スクリプト — ワーカーノード (PC2)
:: 必須環境変数:
::   SS_PRIMARY_IP : プライマリノードのクラスタ IP (例: 192.168.100.1)
:: オプション環境変数:
::   SS_RAY_PORT   : Ray head ポート (デフォルト 6379)
::   SS_RAY_CPUS   : ワーカーが使用する CPU コア数 (デフォルト 14)
::   SS_RAY_GPUS   : ワーカーが使用する GPU 数 (デフォルト 0)
:: 使い方:
::   set SS_PRIMARY_IP=192.168.100.1
::   scripts\cluster\start_worker.bat
:: ────────────────────────────────────────────────────────────────

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%..\..\"
pushd "%PROJECT_ROOT%"

echo [worker] ShuttleScope ワーカーノード起動

:: ── 環境変数のデフォルト設定 ─────────────────────────────────
if not defined SS_PRIMARY_IP (
    echo [worker] ERROR: SS_PRIMARY_IP が未設定です。
    echo           例: set SS_PRIMARY_IP=192.168.100.1
    exit /b 1
)
if not defined SS_RAY_PORT   set SS_RAY_PORT=6379
if not defined SS_RAY_CPUS   set SS_RAY_CPUS=14
if not defined SS_RAY_GPUS   set SS_RAY_GPUS=0

set "RAY_HEAD=%SS_PRIMARY_IP%:%SS_RAY_PORT%"
echo [worker] プライマリ: %RAY_HEAD%

:: ── Python 仮想環境の確認 ─────────────────────────────────────
set "PYTHON=%CD%\backend\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [worker] ERROR: 仮想環境が見つかりません: %PYTHON%
    exit /b 1
)

:: ── PostgreSQL standby 起動 ───────────────────────────────────
echo [worker] PostgreSQL standby を確認...
set "PG_CTL=%ProgramFiles%\PostgreSQL\16\bin\pg_ctl.exe"
if not exist "%PG_CTL%" set "PG_CTL=%ProgramFiles%\PostgreSQL\15\bin\pg_ctl.exe"

if exist "%PG_CTL%" (
    if not defined PG_DATA (
        set "PG_DATA=%ProgramData%\PostgreSQL\16\data"
        if not exist "!PG_DATA!" set "PG_DATA=%ProgramData%\PostgreSQL\15\data"
    )
    "%PG_CTL%" status -D "!PG_DATA!" >nul 2>&1
    if errorlevel 1 (
        echo [worker] PostgreSQL standby を起動します...
        "%PG_CTL%" start -D "!PG_DATA!" -l "%TEMP%\pg_standby.log"
        timeout /t 3 /nobreak >nul
    ) else (
        echo [worker] PostgreSQL standby は既に稼働中
    )
) else (
    echo [worker] WARN: pg_ctl が見つかりません。スキップします。
)

:: ── Ray worker 起動 ───────────────────────────────────────────
echo [worker] Ray worker を起動 (head=%RAY_HEAD%)...
where ray >nul 2>&1
if errorlevel 1 (
    echo [worker] WARN: ray コマンドが見つかりません。推論タスクはローカル実行のみになります。
) else (
    ray stop --force >nul 2>&1
    timeout /t 2 /nobreak >nul
    ray start ^
        --address="%RAY_HEAD%" ^
        --num-cpus=%SS_RAY_CPUS% ^
        --num-gpus=%SS_RAY_GPUS% ^
        --disable-usage-stats
    if errorlevel 1 (
        echo [worker] WARN: Ray worker の起動に失敗しました。
    ) else (
        echo [worker] Ray worker 接続完了
    )
)

:: ── ヘルスモニタ起動（プライマリを監視） ──────────────────────
echo [worker] ヘルスモニタを起動 (プライマリ監視)...
set SS_HEALTH_URL=http://%SS_PRIMARY_IP%:8765/api/health
start "ss-health-worker" /min "%PYTHON%" "%CD%\scripts\health_monitor.py"

echo [worker] 起動完了。プライマリ (%SS_PRIMARY_IP%) からタスクを受け付けます。
echo [worker] 停止するには Ctrl+C または ray stop を実行してください。

:: Ray worker はバックグラウンドプロセスとして動くため、終了待機
:loop
timeout /t 30 /nobreak >nul
ray status >nul 2>&1
if errorlevel 1 (
    echo [worker] Ray との接続が切れました。再接続を試みます...
    ray start --address="%RAY_HEAD%" --num-cpus=%SS_RAY_CPUS% --num-gpus=%SS_RAY_GPUS% --disable-usage-stats >nul 2>&1
)
goto loop

popd
endlocal
