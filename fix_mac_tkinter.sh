#!/bin/bash
# Скрипт для исправления проблемы с tkinter на macOS

echo "========================================"
echo "   Исправление tkinter на macOS"
echo "========================================"
echo ""

# Проверка Homebrew
if ! command -v brew &> /dev/null; then
    echo "❌ Homebrew не установлен!"
    echo "   Установите: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    exit 1
fi

echo "✅ Homebrew найден"
echo ""

# Установка tcl-tk
echo "📦 Установка tcl-tk..."
brew install tcl-tk

if [ $? -ne 0 ]; then
    echo "❌ Ошибка установки tcl-tk"
    exit 1
fi

echo "✅ tcl-tk установлен"
echo ""

# Определяем путь к tcl-tk
TCLTK_PATH="/opt/homebrew/opt/tcl-tk"
if [ ! -d "$TCLTK_PATH" ]; then
    TCLTK_PATH="/usr/local/opt/tcl-tk"
fi

if [ ! -d "$TCLTK_PATH" ]; then
    echo "⚠️  Не удалось найти tcl-tk. Пробуем альтернативный путь..."
    TCLTK_PATH=$(brew --prefix tcl-tk)
fi

echo "📍 Путь к tcl-tk: $TCLTK_PATH"
echo ""

# Проверяем текущую версию Python
CURRENT_PYTHON=$(python3 --version 2>&1 | awk '{print $2}')
echo "Текущая версия Python: $CURRENT_PYTHON"
echo ""

# Устанавливаем переменные окружения
export PATH="$TCLTK_PATH/bin:$PATH"
export LDFLAGS="-L$TCLTK_PATH/lib"
export CPPFLAGS="-I$TCLTK_PATH/include"
export PKG_CONFIG_PATH="$TCLTK_PATH/lib/pkgconfig"

echo "🔧 Переменные окружения установлены:"
echo "   PATH=$TCLTK_PATH/bin:\$PATH"
echo "   LDFLAGS=-L$TCLTK_PATH/lib"
echo "   CPPFLAGS=-I$TCLTK_PATH/include"
echo "   PKG_CONFIG_PATH=$TCLTK_PATH/lib/pkgconfig"
echo ""

# Проверяем pyenv
if command -v pyenv &> /dev/null; then
    echo "✅ pyenv найден"
    echo ""
    echo "📝 Следующие шаги:"
    echo ""
    echo "1. Удалите текущую версию Python:"
    echo "   pyenv uninstall $CURRENT_PYTHON"
    echo ""
    echo "2. Установите Python заново с поддержкой tkinter:"
    echo "   export PATH=\"$TCLTK_PATH/bin:\$PATH\""
    echo "   export LDFLAGS=\"-L$TCLTK_PATH/lib\""
    echo "   export CPPFLAGS=\"-I$TCLTK_PATH/include\""
    echo "   export PKG_CONFIG_PATH=\"$TCLTK_PATH/lib/pkgconfig\""
    echo "   pyenv install $CURRENT_PYTHON"
    echo ""
    echo "3. Или используйте системный Python:"
    echo "   /usr/bin/python3 portal.py --widget"
    echo ""
else
    echo "⚠️  pyenv не найден"
    echo ""
    echo "💡 Рекомендуется использовать системный Python macOS:"
    echo "   /usr/bin/python3 portal.py --widget"
    echo ""
    echo "Или установите Python через Homebrew:"
    echo "   brew install python@3.12"
    echo "   python3 portal.py --widget"
    echo ""
fi

echo "========================================"
echo "   Готово!"
echo "========================================"
