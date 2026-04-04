@echo off
REM バックエンド仮想環境セットアップスクリプト（Windows）

echo === ShuttleScope バックエンドセットアップ ===

cd %~dp0
python -m venv .venv
echo 仮想環境を作成しました

.venv\Scripts\pip install --upgrade pip
.venv\Scripts\pip install -r requirements.txt

echo.
echo === セットアップ完了 ===
echo バックエンドの起動方法:
echo   cd backend
echo   python main.py
echo.
pause
