@echo off
chcp 65001 >nul 2>&1
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
    echo.
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
    pip install -r requirements.txt --quiet --disable-pip-version-check
    if errorlevel 1 (
        echo ❌ Ошибка установки зависимостей
        echo.
        pause
        exit /b 1
    )
)

echo ✅ Зависимости готовы
echo.

REM Быстрый тест keyboard (для хоткеев)
echo 🔍 Тест библиотеки keyboard для хоткеев...
python -c "import keyboard; print('✅ keyboard работает')" 2>nul
if errorlevel 1 (
    echo ⚠️  keyboard не работает — хоткеи могут не сработать
    echo    Установи: pip install keyboard
) else (
    echo ✅ keyboard готов
)
echo.

REM Авто-конвертация портала если GIF ещё нет
if not exist "assets\portal_animated.gif" (
    if exist "C:\Users\1\Downloads\tumblr_mm55e88N8H1rnir1do1_500.gif.mp4" (
        echo 🎞️ Генерация анимации портала из MP4...
        python import_portal_from_mp4.py "C:\Users\1\Downloads\tumblr_mm55e88N8H1rnir1do1_500.gif.mp4"
        echo.
    )
)

echo 🚀 Запуск Портала...
echo.
echo 💡 Используйте Ctrl+Alt+P для показа/скрытия виджета
echo    (запасной: Win+Shift+P если Ctrl+Alt+P не работает)
echo 📝 Отладка хоткеев: %TEMP%\portal_hotkey_debug.log
echo.

REM Очистка кеша Python (на случай если старый код закеширован)
if exist "__pycache__" (
    echo 🧹 Очистка кеша Python...
    rmdir /s /q __pycache__ 2>nul
)

REM Проверка синтаксиса до запуска (сразу видно битый файл / конфликт OneDrive)
echo 🔎 Проверка синтаксиса portal_widget.py...
python -m py_compile portal_widget.py 2>nul
if errorlevel 1 (
    echo.
    echo ❌ Ошибка в portal_widget.py ^(часто лишний отступ у if^)
    echo    Скачай свежую версию: git pull
    echo    Или открой portal_widget.py около строки 31 — блок debug_log_path должен быть с отступом 4 пробела.
    echo.
    python -m py_compile portal_widget.py
    pause
    exit /b 1
)
echo ✅ Синтаксис OK
echo.

REM Запуск БЕЗ --widget, т.к. теперь виджет запускается по умолчанию
python portal.py

if errorlevel 1 (
    echo.
    echo ❌ Ошибка при запуске приложения
    pause
    exit /b 1
)
