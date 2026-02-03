@echo off
chcp 65001 > nul
REM 画像生成エージェント 起動スクリプト (Windows CMD用)

cd /d "%~dp0"

echo 画像生成エージェントを起動しています...
echo.

REM 仮想環境があれば有効化
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

REM Streamlitを起動
streamlit run app.py

pause
