@echo off
chcp 65001 >nul
setlocal

set "BACKUP_DIR=C:\ShuttleScope\backups"
set "SQLITE_DB=%~dp0..\backend\db\shuttlescope.db"

if not exist "%BACKUP_DIR%" (
    mkdir "%BACKUP_DIR%"
)

:: タイムスタンプ生成（YYYYMMDD_HHMM）
for /f "tokens=1-3 delims=/" %%a in ("%date%") do (
    set "YY=%%a"
    set "MM=%%b"
    set "DD=%%c"
)
for /f "tokens=1-2 delims=:" %%a in ("%time: =0%") do (
    set "HH=%%a"
    set "MIN=%%b"
)
set "TIMESTAMP=%YY%%MM%%DD%_%HH%%MIN%"

:: SQLite バックアップ（本番稼働DB）
if exist "%SQLITE_DB%" (
    set "DEST_SQLITE=%BACKUP_DIR%\shuttlescope_%TIMESTAMP%.db"
    copy /Y "%SQLITE_DB%" "%DEST_SQLITE%" >nul
    echo [OK] SQLite backup: %DEST_SQLITE%
) else (
    echo [SKIP] SQLite DB not found: %SQLITE_DB%
)

:: PostgreSQL バックアップ（PostgreSQL 移行後に有効化）
:: set "DEST_SQL=%BACKUP_DIR%\shuttlescope_%TIMESTAMP%.sql"
:: pg_dump -U ss_user -h 192.168.100.1 shuttlescope > "%DEST_SQL%"
:: if errorlevel 1 (
::     echo [ERROR] pg_dump failed
:: ) else (
::     echo [OK] PostgreSQL backup: %DEST_SQL%
:: )

:: 30日以上前のバックアップを削除
forfiles /p "%BACKUP_DIR%" /m "shuttlescope_*.db" /d -30 /c "cmd /c del /f @path" 2>nul
forfiles /p "%BACKUP_DIR%" /m "shuttlescope_*.sql" /d -30 /c "cmd /c del /f @path" 2>nul

echo Backup complete: %TIMESTAMP%
endlocal
