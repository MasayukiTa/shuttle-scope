@echo off
:: ShuttleScope 手動フェイルオーバー — standby を primary に昇格する
::
:: PC1 (primary) が死亡した場合に PC2 (worker) で実行する。
:: 実行後: PC2 が新しい primary として DB + Ray head + FastAPI を引き継ぐ。
::
:: 事前確認:
::   1. PC1 が本当に応答していないことを確認
::   2. PC2 の PostgreSQL が standby として起動していることを確認
:: ────────────────────────────────────────────────────────────────

setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
set "PROJECT_ROOT=%SCRIPT_DIR%..\..\"
pushd "%PROJECT_ROOT%"

echo [failover] ════════════════════════════════════════
echo [failover] ShuttleScope 手動フェイルオーバー
echo [failover] PC2 (このノード) を primary に昇格します
echo [failover] ════════════════════════════════════════

:: ── 確認プロンプト ────────────────────────────────────────────
set /p CONFIRM="続行しますか？ PC1 が確実に停止していることを確認してください [y/N]: "
if /i not "%CONFIRM%"=="y" (
    echo [failover] キャンセルしました
    exit /b 0
)

set "PYTHON=%CD%\backend\.venv\Scripts\python.exe"

:: ── 1. PostgreSQL standby を primary に昇格 ───────────────────
echo [failover] PostgreSQL を primary に昇格...
set "PG_CTL=%ProgramFiles%\PostgreSQL\16\bin\pg_ctl.exe"
if not exist "%PG_CTL%" set "PG_CTL=%ProgramFiles%\PostgreSQL\15\bin\pg_ctl.exe"

if exist "%PG_CTL%" (
    if not defined PG_DATA (
        set "PG_DATA=%ProgramData%\PostgreSQL\16\data"
        if not exist "!PG_DATA!" set "PG_DATA=%ProgramData%\PostgreSQL\15\data"
    )
    "%PG_CTL%" promote -D "!PG_DATA!"
    if errorlevel 1 (
        echo [failover] ERROR: PostgreSQL の昇格に失敗しました
        exit /b 1
    )
    echo [failover] PostgreSQL 昇格完了
    timeout /t 3 /nobreak >nul
) else (
    echo [failover] WARN: pg_ctl が見つかりません。PostgreSQL の昇格をスキップします。
)

:: ── 2. Ray head をこのノードで起動 ───────────────────────────
echo [failover] Ray head を起動...
if not defined SS_RAY_PORT   set SS_RAY_PORT=6379
if not defined SS_RAY_CPUS   set SS_RAY_CPUS=14
if not defined SS_RAY_GPUS   set SS_RAY_GPUS=0

where ray >nul 2>&1
if not errorlevel 1 (
    ray stop --force >nul 2>&1
    timeout /t 2 /nobreak >nul
    ray start --head ^
        --port=%SS_RAY_PORT% ^
        --dashboard-host=0.0.0.0 ^
        --dashboard-port=8265 ^
        --num-cpus=%SS_RAY_CPUS% ^
        --num-gpus=%SS_RAY_GPUS% ^
        --disable-usage-stats
    echo [failover] Ray head 起動完了
)

:: ── 3. cluster.config.yaml の mode を primary に書き換え ───────
echo [failover] cluster.config.yaml を更新...
"%PYTHON%" -c "
import yaml, pathlib
p = pathlib.Path('cluster.config.yaml')
if p.exists():
    d = yaml.safe_load(p.read_text('utf-8')) or {}
    d['mode'] = 'primary'
    if 'node' not in d: d['node'] = {}
    d['node']['role'] = 'primary'
    p.write_text(yaml.safe_dump(d, allow_unicode=True, default_flow_style=False, sort_keys=False), 'utf-8')
    print('[failover] cluster.config.yaml 更新完了')
else:
    print('[failover] WARN: cluster.config.yaml が見つかりません')
" 2>nul || echo [failover] WARN: cluster.config.yaml の更新をスキップ

:: ── 4. FastAPI 起動 ────────────────────────────────────────────
echo [failover] FastAPI を起動します...
set SS_CLUSTER_MODE=primary
if not defined API_PORT set API_PORT=8765
"%PYTHON%" backend\main.py

popd
endlocal
