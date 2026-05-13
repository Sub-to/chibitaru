@echo off
chcp 65001 > nul
:: 🔵 青っ子 Windows版 起動スクリプト

set SCRIPT_DIR=%~dp0
set SCRIPT_DIR=%SCRIPT_DIR:~0,-1%
set MODEL=%SCRIPT_DIR%\model\Qwen2.5-1.5B-Instruct-Q4_K_M.gguf
set LLAMA=%SCRIPT_DIR%\..\bin\win-x64\llama-server.exe

if not exist "%LLAMA%" (
    where llama-server >nul 2>&1
    if %ERRORLEVEL% equ 0 (
        set LLAMA=llama-server
    ) else (
        echo ❌ llama-server.exe が見つかりません
        echo    場所: %SCRIPT_DIR%\..\bin\win-x64\llama-server.exe
        pause
        exit /b 1
    )
)

echo 🔵🔵🔵 青い三連星 展開中... (Windows)

:: DLL パスを通す
set PATH=%SCRIPT_DIR%\..\bin\win-x64;%PATH%

start /B "" "%LLAMA%" --model "%MODEL%" --port 11201 --ctx-size 512 --threads 2 > %TEMP%\aoko_1.log 2>&1
start /B "" "%LLAMA%" --model "%MODEL%" --port 11202 --ctx-size 512 --threads 2 > %TEMP%\aoko_2.log 2>&1
start /B "" "%LLAMA%" --model "%MODEL%" --port 11203 --ctx-size 512 --threads 2 > %TEMP%\aoko_3.log 2>&1

echo 起動待機中（20秒）...
timeout /t 20 /nobreak > nul

:: ヘルスチェック
set OK=0
curl -s http://localhost:11201/health >nul 2>&1 && set /a OK+=1
curl -s http://localhost:11202/health >nul 2>&1 && set /a OK+=1
curl -s http://localhost:11203/health >nul 2>&1 && set /a OK+=1

echo ✅ %OK%/3 号機 起動完了
if "%OK%"=="3" (
    echo 🔵 三連星 完全展開！
) else (
    echo ⚠️ 一部未起動 ^(ログ: %TEMP%\aoko_?.log^)
)
