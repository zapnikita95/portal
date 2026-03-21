#!/bin/bash
# Запуск Портала с виджетом на рабочем столе для macOS
# Автоматически определяет путь к скрипту

# Восстанавливаем права (слетают после git pull)
chmod +x "$0" 2>/dev/null

# Переход в директорию скрипта
cd "$(dirname "$0")"

echo "========================================"
echo "   🌀 ПОРТАЛ - Запуск приложения"
echo "========================================"
echo ""

# Проверка наличия Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не найден! Установите Python 3.8+"
    echo "   Можно через Homebrew: brew install python3"
    read -p "Нажмите Enter для выхода..."
    exit 1
fi

echo "✅ Python3 найден"
echo ""

# Проверка зависимостей
echo "📦 Проверка зависимостей..."
if ! python3 -c "import customtkinter" &> /dev/null; then
    echo "⚠️  Зависимости не установлены. Устанавливаю..."
    pip3 install -r requirements.txt
    if [ $? -ne 0 ]; then
        echo "❌ Ошибка установки зависимостей"
        read -p "Нажмите Enter для выхода..."
        exit 1
    fi
fi

echo "✅ Зависимости готовы"
echo ""
echo "🚀 Запуск Портала с виджетом..."
echo ""
if ! python3 -c "import tkinter" 2>/dev/null; then
    echo "❌ Нет tkinter. В этой папке выполните: chmod +x fix.sh && ./fix.sh"
    read -p "Нажмите Enter для выхода..."
    exit 1
fi

echo "💡 Виджет: Cmd+Option+P | Буфер: Cmd+Shift+C отправить / Cmd+Shift+V забрать"
echo "💡 Окно: Alt+тащить | Файл: Ctrl+клик по порталу | IP: двойной клик"
echo ""

# Очистка кеша (на случай старого .pyc)
if [ -d "__pycache__" ]; then
    echo "🧹 Очистка __pycache__..."
    rm -rf __pycache__
fi

echo "🔎 Проверка синтаксиса portal_widget.py..."
if ! python3 -m py_compile portal_widget.py 2>/dev/null; then
    echo ""
    echo "❌ Ошибка в portal_widget.py. Обнови папку: git pull"
    python3 -m py_compile portal_widget.py
    read -p "Нажмите Enter для выхода..."
    exit 1
fi
echo "✅ Синтаксис OK"
echo ""

# Виджет включается по умолчанию (как на Windows); --no-widget чтобы отключить
python3 portal.py

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Ошибка при запуске приложения"
    read -p "Нажмите Enter для выхода..."
    exit 1
fi
