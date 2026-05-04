@echo off
:: ShuttleScope PostgreSQL プライマリ初期設定
::
:: 実行タイミング: 初回セットアップ時のみ（1回実行で完了）
:: 事前準備:
::   1. PostgreSQL 15 or 16 をインストール済みであること
::   2. 管理者権限で実行すること
::   3. 環境変数を必要に応じて設定すること
::
:: 設定される内容:
::   - shuttlescope データベースと ss_user ロールの作成
::   - レプリケーション用ロール (replicator) の作成
::   - pg_hba.conf の更新（クラスタネットワークからの接続を許可）
::   - postgresql.conf の更新（ストリーミングレプリケーション有効化）
:: ────────────────────────────────────────────────────────────────

setlocal EnableDelayedExpansion

if not defined PG_VERSION set PG_VERSION=16
set "PG_BIN=%ProgramFiles%\PostgreSQL\%PG_VERSION%\bin"
if not exist "%PG_BIN%\psql.exe" (
    set PG_VERSION=15
    set "PG_BIN=%ProgramFiles%\PostgreSQL\15\bin"
)
if not exist "%PG_BIN%\psql.exe" (
    echo ERROR: psql が見つかりません。PostgreSQL をインストールしてください。
    exit /b 1
)

if not defined PG_DATA (
    set "PG_DATA=%ProgramData%\PostgreSQL\%PG_VERSION%\data"
)
if not defined SS_DB_PASSWORD  set SS_DB_PASSWORD=shuttlescope_pass
if not defined SS_REPL_PASSWORD set SS_REPL_PASSWORD=repl_pass
if not defined CLUSTER_SUBNET  set CLUSTER_SUBNET=192.168.100.0/24

echo [pg_primary] PostgreSQL バージョン: %PG_VERSION%
echo [pg_primary] データディレクトリ: %PG_DATA%
echo [pg_primary] クラスタサブネット: %CLUSTER_SUBNET%

:: ── データベース・ユーザー作成 ────────────────────────────────
echo [pg_primary] データベースとユーザーを作成...
"%PG_BIN%\psql.exe" -U postgres -c "CREATE ROLE ss_user WITH LOGIN PASSWORD '%SS_DB_PASSWORD%';" 2>nul
"%PG_BIN%\psql.exe" -U postgres -c "CREATE DATABASE shuttlescope OWNER ss_user;" 2>nul
"%PG_BIN%\psql.exe" -U postgres -c "GRANT ALL PRIVILEGES ON DATABASE shuttlescope TO ss_user;" 2>nul

:: ── レプリケーションロール作成 ────────────────────────────────
echo [pg_primary] レプリケーションロールを作成...
"%PG_BIN%\psql.exe" -U postgres -c ^
    "CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD '%SS_REPL_PASSWORD%';" 2>nul

:: ── postgresql.conf: レプリケーション設定 ────────────────────
echo [pg_primary] postgresql.conf を設定...
"%PG_BIN%\psql.exe" -U postgres -c "ALTER SYSTEM SET wal_level = 'replica';"
"%PG_BIN%\psql.exe" -U postgres -c "ALTER SYSTEM SET max_wal_senders = 5;"
"%PG_BIN%\psql.exe" -U postgres -c "ALTER SYSTEM SET wal_keep_size = '256MB';"
"%PG_BIN%\psql.exe" -U postgres -c "ALTER SYSTEM SET hot_standby = 'on';"
"%PG_BIN%\psql.exe" -U postgres -c "ALTER SYSTEM SET listen_addresses = '*';"

:: ── pg_hba.conf: クラスタネットワークからの接続を許可 ─────────
echo [pg_primary] pg_hba.conf を設定...
set "HBA=%PG_DATA%\pg_hba.conf"
:: 既にエントリがなければ追加
findstr /C:"shuttlescope" "%HBA%" >nul 2>&1
if errorlevel 1 (
    echo host    shuttlescope    ss_user        %CLUSTER_SUBNET%     scram-sha-256 >> "%HBA%"
    echo host    replication     replicator     %CLUSTER_SUBNET%     scram-sha-256 >> "%HBA%"
    echo [pg_primary] pg_hba.conf にクラスタサブネットのエントリを追加しました
) else (
    echo [pg_primary] pg_hba.conf は既に設定済みです
)

:: ── PostgreSQL 再起動（設定反映） ────────────────────────────
echo [pg_primary] PostgreSQL を再起動して設定を反映...
"%PG_BIN%\pg_ctl.exe" restart -D "%PG_DATA%" -l "%TEMP%\pg_restart.log"
timeout /t 5 /nobreak >nul

echo [pg_primary] ══════════════════════════════════
echo [pg_primary] プライマリ初期設定完了
echo [pg_primary]   DB:       shuttlescope
echo [pg_primary]   ユーザー: ss_user
echo [pg_primary]   接続URL:  postgresql://ss_user:%SS_DB_PASSWORD%@localhost/shuttlescope
echo [pg_primary]
echo [pg_primary] 次のステップ:
echo [pg_primary]   1. scripts\cluster\pg_migrate_sqlite.py で既存データを移行
echo [pg_primary]   2. PC2 で scripts\cluster\pg_setup_standby.bat を実行
echo [pg_primary] ══════════════════════════════════

endlocal
