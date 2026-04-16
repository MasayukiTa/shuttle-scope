@echo off
:: ShuttleScope クラスタ起動スクリプト — プライマリノード (PC1)
:: cluster.config.yaml の内容を環境変数で上書き可能。
:: 使い方: scripts\cluster\start_primary.bat
:: ────────────────────────────────────────────────────────────────

setlocal EnableDelayedExpansion

:: スクリプトが置かれているディレクトリを基準にプロジェクトルートを解決
set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%..\..\"
pushd "%PROJECT_ROOT%"

echo [primary] ShuttleScope プライマリノード起動
echo [primary] プロジェクトルート: %CD%

:: ── 1. Python 仮想環境の確認 ──────────────────────────────────
set "PYTHON=%CD%\backend\.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
    echo [primary] ERROR: 仮想環境が見つかりません: %PYTHON%
    echo           backend\setup_venv.bat を先に実行してください。
    exit /b 1
)
echo [primary] Python: %PYTHON%

:: ── 2. 環境変数のデフォルト設定 ──────────────────────────────
:: cluster.config.yaml を Python で読んでセットすることもできるが、
:: ここでは .env.development を優先し必要な値のみ上書き。
if not defined SS_CLUSTER_MODE   set SS_CLUSTER_MODE=primary
if not defined SS_RAY_PORT       set SS_RAY_PORT=6379
if not defined SS_RAY_DASHBOARD  set SS_RAY_DASHBOARD=8265
if not defined SS_RAY_CPUS       set SS_RAY_CPUS=8
if not defined SS_RAY_GPUS       set SS_RAY_GPUS=1
if not defined API_PORT          set API_PORT=8765

echo [primary] クラスタモード: %SS_CLUSTER_MODE%

:: ── 3. ネットワークルーティング設定 ──────────────────────────
echo [primary] ネットワークルーティングを設定...
call "%SCRIPT_DIR%setup_routes.bat"
if errorlevel 1 (
    echo [primary] WARN: ルーティング設定に失敗しましたが続行します
)

:: ── 4. PostgreSQL 起動確認 ────────────────────────────────────
echo [primary] PostgreSQL を確認...
set "PG_CTL=%ProgramFiles%\PostgreSQL\16\bin\pg_ctl.exe"
if not exist "%PG_CTL%" set "PG_CTL=%ProgramFiles%\PostgreSQL\15\bin\pg_ctl.exe"

if exist "%PG_CTL%" (
    if not defined PG_DATA (
        set "PG_DATA=%ProgramData%\PostgreSQL\16\data"
        if not exist "!PG_DATA!" set "PG_DATA=%ProgramData%\PostgreSQL\15\data"
    )
    "%PG_CTL%" status -D "!PG_DATA!" >nul 2>&1
    if errorlevel 1 (
        echo [primary] PostgreSQL を起動します...
        "%PG_CTL%" start -D "!PG_DATA!" -l "%TEMP%\pg_start.log"
        timeout /t 3 /nobreak >nul
    ) else (
        echo [primary] PostgreSQL は既に稼働中
    )
) else (
    echo [primary] WARN: pg_ctl が見つかりません。PostgreSQL が起動済みか確認してください。
)

:: ── 5. Ray head 起動 ──────────────────────────────────────────
echo [primary] Ray head を起動...
where ray >nul 2>&1
if errorlevel 1 (
    echo [primary] WARN: ray コマンドが見つかりません。SS_CLUSTER_MODE=off で続行します。
    set SS_CLUSTER_MODE=off
) else (
    :: すでに起動していれば stop して再起動（冪等化）
    ray stop --force >nul 2>&1
    timeout /t 2 /nobreak >nul
    ray start --head ^
        --port=%SS_RAY_PORT% ^
        --dashboard-host=0.0.0.0 ^
        --dashboard-port=%SS_RAY_DASHBOARD% ^
        --num-cpus=%SS_RAY_CPUS% ^
        --num-gpus=%SS_RAY_GPUS% ^
        --disable-usage-stats
    if errorlevel 1 (
        echo [primary] WARN: Ray head の起動に失敗しました。SS_CLUSTER_MODE=off で続行します。
        set SS_CLUSTER_MODE=off
    ) else (
        echo [primary] Ray head 起動完了 (port=%SS_RAY_PORT%)
    )
)

:: ── 6. ヘルスモニタ起動（バックグラウンド） ──────────────────
echo [primary] ヘルスモニタを起動...
start "ss-health" /min "%PYTHON%" "%CD%\scripts\health_monitor.py"

:: ── 7. FastAPI 起動（フォアグラウンド） ──────────────────────
echo [primary] FastAPI を起動します (port=%API_PORT%)...
set SS_CLUSTER_MODE=%SS_CLUSTER_MODE%
"%PYTHON%" backend\main.py

popd
endlocal
