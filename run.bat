@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"
echo 🌀 Запуск Портала...
echo.
python portal.py
if errorlevel 1 (
    echo.
    echo ❌ Ошибка при запуске
    pause
)
