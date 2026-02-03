# 画像生成エージェント 起動スクリプト (Windows PowerShell用)

Set-Location $PSScriptRoot

Write-Host "画像生成エージェントを起動しています..." -ForegroundColor Cyan
Write-Host ""

# 仮想環境があれば有効化
if (Test-Path "venv\Scripts\Activate.ps1") {
    & "venv\Scripts\Activate.ps1"
}

# Streamlitを起動
streamlit run app.py
