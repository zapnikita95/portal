@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo 🌀 Запуск Портала...
echo.
if /I not "%PORTAL_SKIP_SMOKE%"=="1" (
    python scripts\verify_portal_smoke.py
    if errorlevel 1 (
        echo ❌ Smoke не прошёл. set PORTAL_SKIP_SMOKE=1 чтобы пропустить.
        pause
        exit /b 1
    )
)
python portal.py
if errorlevel 1 (
    echo.
    echo ❌ Ошибка при запуске
    pause
)
