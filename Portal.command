#!/bin/bash
# Двойной клик в Finder: запуск Портала с виджетом (macOS)
cd "$(dirname "$0")"

echo "🌀 Портал — запуск..."
echo ""

if ! command -v python3 &>/dev/null; then
    echo "❌ Нет python3. Установите: brew install python3"
    read -r _
    exit 1
fi

if ! python3 -c "import tkinter" 2>/dev/null; then
    echo "❌ Нет tkinter (_tkinter). Запустите в терминале из этой папки:"
    echo "   chmod +x fix.sh && ./fix.sh"
    read -r _
    exit 1
fi

if ! python3 -c "import customtkinter" 2>/dev/null; then
    echo "📦 Ставлю зависимости..."
    pip3 install -r requirements.txt || exit 1
fi

echo "💡 Виджет: Cmd+Option+P | Общий буфер: Cmd+Shift+C → отправить, Cmd+Shift+V → забрать"
echo "💡 Окно портала: Alt+тащить | Файл: Ctrl+клик | IP: двойной клик"
echo ""

exec python3 portal.py --widget
