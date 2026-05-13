@echo off
chcp 65001 > nul
:: ╔══════════════════════════════════════════╗
:: ║  🔵 チビタル - USB監視エージェント       ║
:: ║     青い三連星セキュリティシステム       ║
:: ╚══════════════════════════════════════════╝
:: Windows 11 x64 対応

set USB_DIR=%~dp0
set USB_DIR=%USB_DIR:~0,-1%

echo.
echo ╔══════════════════════════════════════════╗
echo ║  🔵 チビタル 起動  (Windows)            ║
echo ╚══════════════════════════════════════════╝
echo.
echo 何をしますか？
echo   1: 🔵 セキュリティ監視開始（青い三連星）
echo   2: 🦠 ウイルスチェック（ClamAV必要）
echo   3: 📦 エージェントインストール
echo   4: 🔍 Vault品質チェック（蔵丸）
echo   0: 終了
echo.
set /p CHOICE=選択 ^>

if "%CHOICE%"=="1" goto MONITOR
if "%CHOICE%"=="2" goto VIRUS
if "%CHOICE%"=="3" goto INSTALL
if "%CHOICE%"=="4" goto VAULT
if "%CHOICE%"=="0" goto END
echo ？
goto END

:MONITOR
echo.
echo 🔵 三連星を展開しますわ...
call "%USB_DIR%\aoko\launch_win.bat"
echo 🔵 監視開始...
python "%USB_DIR%\aoko\monitor.py"
goto END

:VIRUS
echo.
echo 🦠 ウイルスチェック開始...
where clamscan >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ⚠️  ClamAV が見つかりません
    echo インストール: https://www.clamav.net/downloads
    goto END
)
clamscan -r %USERPROFILE% ^
    --database="%USB_DIR%\scan\clamdb" ^
    --exclude-dir=".git" ^
    --infected ^
    --log=%TEMP%\clamav_result.txt
echo.
echo ✅ スキャン完了
echo 📋 ログ: %TEMP%\clamav_result.txt
goto END

:INSTALL
echo.
echo 📦 インストーラー
echo   1: 🔵 青っ子（セキュリティ監視）
echo   2: 👁️  蔵丸（Vault品質管理）
echo   3: 全部まとめて
echo.
set /p INST_CHOICE=選択 ^>

set INSTALL_DIR=%USERPROFILE%\ランドセル
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

if "%INST_CHOICE%"=="1" (
    xcopy /E /I /Y "%USB_DIR%\aoko" "%INSTALL_DIR%\aoko"
    echo ✅ 青っ子インストール完了: %INSTALL_DIR%\aoko\
)
if "%INST_CHOICE%"=="2" (
    if exist "%USB_DIR%\install\kuramaru.py" (
        copy /Y "%USB_DIR%\install\kuramaru.py" "%INSTALL_DIR%\"
        echo ✅ 蔵丸インストール完了: %INSTALL_DIR%\kuramaru.py
    ) else (
        echo ⚠️  蔵丸はUSBに含まれていません
    )
)
if "%INST_CHOICE%"=="3" (
    xcopy /E /I /Y "%USB_DIR%\aoko" "%INSTALL_DIR%\aoko"
    if exist "%USB_DIR%\install\kuramaru.py" copy /Y "%USB_DIR%\install\kuramaru.py" "%INSTALL_DIR%\"
    echo ✅ 全インストール完了: %INSTALL_DIR%\
)
goto END

:VAULT
echo.
set KURAMARU=%USERPROFILE%\ランドセル\kuramaru.py
if exist "%KURAMARU%" (
    python "%KURAMARU%"
) else (
    echo ⚠️  蔵丸が見つかりません: %KURAMARU%
    echo 選択 3 でインストールしてください
)
goto END

:END
echo.
pause
