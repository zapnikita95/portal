#!/bin/bash
# Автоматическое исправление tkinter на macOS - просто запустите этот файл!

set -e

echo "========================================"
echo "   🌀 Автоисправление tkinter на Mac"
echo "========================================"
echo ""

# Проверка macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "❌ Этот скрипт только для macOS!"
    exit 1
fi

# Проверка Homebrew
if ! command -v brew &> /dev/null; then
    echo "❌ Homebrew не установлен!"
    echo "   Устанавливаю Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

echo "✅ Homebrew готов"
echo ""

# Установка tcl-tk
echo "📦 Устанавливаю tcl-tk..."
brew install tcl-tk 2>/dev/null || brew upgrade tcl-tk

# Определяем путь к tcl-tk
if [ -d "/opt/homebrew/opt/tcl-tk" ]; then
    TCLTK_PATH="/opt/homebrew/opt/tcl-tk"  # Apple Silicon
elif [ -d "/usr/local/opt/tcl-tk" ]; then
    TCLTK_PATH="/usr/local/opt/tcl-tk"  # Intel
else
    TCLTK_PATH=$(brew --prefix tcl-tk)
fi

echo "✅ tcl-tk установлен: $TCLTK_PATH"
echo ""

# Проверяем pyenv
if ! command -v pyenv &> /dev/null; then
    echo "⚠️  pyenv не найден"
    echo ""
    echo "💡 Используйте системный Python:"
    echo "   /usr/bin/python3 portal.py --widget"
    echo ""
    echo "Или установите Python через Homebrew:"
    echo "   brew install python@3.12"
    echo "   python3 portal.py --widget"
    exit 0
fi

# Получаем текущую версию Python
CURRENT_VERSION=$(python3 --version 2>&1 | awk '{print $2}' | cut -d. -f1,2,3)
echo "📍 Текущая версия Python: $CURRENT_VERSION"
echo ""

# Устанавливаем переменные окружения
export PATH="$TCLTK_PATH/bin:$PATH"
export LDFLAGS="-L$TCLTK_PATH/lib"
export CPPFLAGS="-I$TCLTK_PATH/include"
export PKG_CONFIG_PATH="$TCLTK_PATH/lib/pkgconfig"

echo "🔧 Удаляю старую версию Python..."
pyenv uninstall -f $CURRENT_VERSION 2>/dev/null || echo "   (версия уже удалена или не найдена)"

echo ""
echo "🔧 Устанавливаю Python $CURRENT_VERSION с поддержкой tkinter..."
echo "   (это займет несколько минут)"
echo ""

# Устанавливаем Python
CONFIGURE_OPTS="--with-tcltk-includes='-I$TCLTK_PATH/include' --with-tcltk-libs='-L$TCLTK_PATH/lib -ltcl8.6 -ltk8.6'" \
PATH="$TCLTK_PATH/bin:$PATH" \
LDFLAGS="-L$TCLTK_PATH/lib" \
CPPFLAGS="-I$TCLTK_PATH/include" \
PKG_CONFIG_PATH="$TCLTK_PATH/lib/pkgconfig" \
pyenv install -f $CURRENT_VERSION

echo ""
echo "✅ Python переустановлен!"
echo ""

# Устанавливаем как глобальную версию
pyenv global $CURRENT_VERSION

echo "📦 Переустанавливаю зависимости..."
cd "$(dirname "$0")"
pip3 install -r requirements.txt --quiet

echo ""
echo "========================================"
echo "   ✅ ГОТОВО! Всё исправлено!"
echo "========================================"
echo ""
echo "Проверка:"
python3 -c "import tkinter; print('✅ Tkinter работает!')" && echo ""
echo "Теперь запустите:"
echo "   python3 portal.py --widget"
echo ""
