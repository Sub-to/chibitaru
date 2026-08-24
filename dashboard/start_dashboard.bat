@echo off
chcp 65001 > nul
:: ╔══════════════════════════════════════════╗
:: ║  🖥 ちびたるダッシュボード               ║
:: ╚══════════════════════════════════════════╝
:: 使い方: ダブルクリックで起動
::         引数に --check を付けると情報源チェック

set DASH_DIR=%~dp0
set DASH_DIR=%DASH_DIR:~0,-1%

where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ❌ Python が見つかりません
    echo    https://www.python.org/downloads/ から入れてください
    echo    ※インストール時に "Add python.exe to PATH" にチェック
    pause
    exit /b 1
)

if "%CHIBITARU_VAULT%"=="" (
    echo ℹ️  CHIBITARU_VAULT が未設定です。既定: %%USERPROFILE%%\ObsidianVault
    echo    別の場所なら: setx CHIBITARU_VAULT "C:\path\to\YourVault"
    echo.
)

python "%DASH_DIR%\server.py" %*
pause
