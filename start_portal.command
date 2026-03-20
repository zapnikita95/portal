#!/bin/bash
# Запуск Портала с виджетом на рабочем столе для macOS
# Автоматически определяет путь к скрипту

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
echo "💡 Используйте Cmd+Option+P для показа/скрытия виджета"
echo ""

# Запуск приложения
python3 portal.py --widget

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Ошибка при запуске приложения"
    read -p "Нажмите Enter для выхода..."
    exit 1
fi
