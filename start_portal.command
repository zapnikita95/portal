#!/bin/bash
# Запуск Портала (macOS). По умолчанию — фон; прозрачность виджета — как в коде (альфа + Cocoa).
#
# Передний план (отладка, всё в этом окне Терминала):
#   ./start_portal.command --foreground
#   или: PORTAL_FOREGROUND=1 ./start_portal.command
#
# Если виджет не виден — явно хромакей (#FF00FF вырезается):
#   PORTAL_MAC_CHROMA_ONLY=1 ./start_portal.command
#
# Виджет в отдельном окне с рамкой и тёмным фоном (по умолчанию на Mac):
#   PORTAL_WIDGET_FRAMED=1   (или ничего не задавать)
# Старое поведение без рамки / «дырявое» окно на весь угол:
#   PORTAL_WIDGET_FRAMED=0 ./start_portal.command
#
# Важно: для глобальных хоткеев нужны ДВА разрешения в «Конфиденциальность»:
#   • Универсальный доступ (Accessibility)
#   • Мониторинг ввода (Input Monitoring)  ← отдельно, не то же самое!
#   Включи для того приложения, КОТОРЫМ запущен python3 (Терминал / iTerm / Cursor и т.д.).
#   После фонового запуска добавь ещё python3 из пути, который виден в логе, если хоткеи молчат.

chmod +x "$0" 2>/dev/null
cd "$(dirname "$0")" || exit 1

LOG="${HOME}/Library/Logs/portal_nohup.log"

FOREGROUND="${PORTAL_FOREGROUND:-0}"
if [[ "$1" == "--foreground" || "$1" == "-f" ]]; then
    FOREGROUND=1
    shift
fi
# Старый флаг — то же самое, что теперь по умолчанию
if [[ "$1" == "--background" || "$1" == "-b" ]]; then
    shift
fi

echo "========================================"
echo "   🌀 ПОРТАЛ - Запуск приложения"
echo "========================================"
echo ""

if pgrep -f "[P]ython.*portal\.py" >/dev/null 2>&1 || pgrep -f "[p]ython3.*portal\.py" >/dev/null 2>&1; then
    echo "⚠️  Похоже, Портал уже запущен. Если дубли — закрой лишнее окно в Dock."
    echo ""
fi

if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 не найден! Установите Python 3.8+"
    echo "   Можно через Homebrew: brew install python3"
    read -p "Нажмите Enter для выхода..."
    exit 1
fi

echo "✅ Python3 найден"
echo ""

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
if ! python3 -c "import AppKit" 2>/dev/null; then
    echo "💡 Для донастройки окна виджета: pip3 install 'pyobjc-framework-Cocoa>=10'"
fi
echo ""

if ! python3 -c "import tkinter" 2>/dev/null; then
    echo "❌ Нет tkinter. В этой папке выполните: chmod +x fix.sh && ./fix.sh"
    read -p "Нажмите Enter для выхода..."
    exit 1
fi

echo "💡 Виджет/буфер (macOS): по умолчанию Cmd+Ctrl+P / C / V | legacy: PORTAL_MAC_HOTKEY_LEGACY=1 → Cmd+Opt+P, Cmd+Shift+C/V"
echo "💡 По умолчанию: запуск в ФОНЕ (Терминал не должен всплывать при хоткеях). Лог: $LOG"
echo "💡 Виджет не виден? Запусти с: PORTAL_MAC_CHROMA_ONLY=1 $0"
echo "💡 Обязательно: Настройки → Конфиденциальность → Мониторинг ввода + Универсальный доступ"
echo ""

if [ -d "__pycache__" ]; then
    echo "🧹 Очистка __pycache__..."
    rm -rf __pycache__
fi

echo "🔎 Проверка синтаксиса (виджет + hotkey-helper)..."
if ! python3 -m py_compile portal_widget.py portal_mac_hotkey_helper.py 2>/dev/null; then
    echo ""
    echo "❌ Ошибка в portal_widget.py / portal_mac_hotkey_helper.py. Обнови папку: git pull"
    python3 -m py_compile portal_widget.py portal_mac_hotkey_helper.py
    read -p "Нажмите Enter для выхода..."
    exit 1
fi
echo "✅ Синтаксис OK"
echo ""

if [[ "$FOREGROUND" == "1" ]]; then
    echo "🚀 Запуск в переднем плане (это окно останется «хозяином» процесса)..."
    exec env PYTHONUNBUFFERED=1 python3 -u portal.py "$@"
fi

echo "🚀 Запуск в фоне (отвязка от Терминала)..."
mkdir -p "$(dirname "$LOG")"
{
    echo ""
    echo "======== $(date '+%Y-%m-%d %H:%M:%S') Портал (nohup) ========"
} >>"$LOG"

nohup env PYTHONUNBUFFERED=1 python3 -u portal.py "$@" >>"$LOG" 2>&1 </dev/null &
disown 2>/dev/null || true

echo "✅ Готово. Портал работает в фоне."
echo "   📄 Лог: $LOG"
echo "   Окно Терминала можно закрыть — иконка останется в Dock (если не закрывал приложение)."
echo "   Отладка здесь же: $0 --foreground"
sleep 0.25
exit 0
