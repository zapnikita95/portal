@echo off
REM Запуск Портала с виджетом на рабочем столе
REM Автоматически определяет путь к скрипту

cd /d "%~dp0"
echo ========================================
echo    🌀 ПОРТАЛ - Запуск приложения
echo ========================================
echo.

REM Проверка наличия Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python не найден! Установите Python 3.8+ с python.org
    pause
    exit /b 1
)

echo ✅ Python найден
echo.

REM Проверка зависимостей
echo 📦 Проверка зависимостей...
pip show customtkinter >nul 2>&1
if errorlevel 1 (
    echo ⚠️  Зависимости не установлены. Устанавливаю...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo ❌ Ошибка установки зависимостей
        pause
        exit /b 1
    )
)

echo ✅ Зависимости готовы
echo.
echo 🚀 Запуск Портала с виджетом...
echo.
echo 💡 Используйте Ctrl+Alt+P для показа/скрытия виджета
echo 📝 Отладка хоткеев: %TEMP%\portal_hotkey_debug.log
echo.

python portal.py --widget

if errorlevel 1 (
    echo.
    echo ❌ Ошибка при запуске приложения
    pause
    exit /b 1
)
