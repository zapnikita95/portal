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

# Проверка Python 3.13+
PYVER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
if python3 -c "import sys; exit(0 if sys.version_info < (3, 13) else 1)" 2>/dev/null; then
    echo "⚠️  Python $PYVER обнаружен. Python 3.13+ может вызывать segfault."
    echo "   Рекомендуется Python 3.12. См. MAC_PYTHON313_FIX.md"
    echo ""
fi

if ! python3 -c "import customtkinter" 2>/dev/null; then
    echo "📦 Ставлю зависимости..."
    pip3 install -r requirements.txt || exit 1
fi

echo "💡 Виджет: Cmd+Option+P | Общий буфер: Cmd+Shift+C → отправить, Cmd+Shift+V → забрать"
echo "💡 Окно портала: Alt+тащить | Файл: Ctrl+клик | IP: двойной клик"
echo ""

if [ -d "__pycache__" ]; then
    rm -rf __pycache__
fi
if ! python3 -m py_compile portal_widget.py 2>/dev/null; then
    echo "❌ Ошибка в portal_widget.py. Выполни в этой папке: git pull"
    python3 -m py_compile portal_widget.py
    read -r _
    exit 1
fi

exec python3 portal.py
