# Исправление проблемы с tkinter на macOS

Если вы видите ошибку:
```
ModuleNotFoundError: No module named '_tkinter'
```

Это означает, что Python был установлен без поддержки Tkinter.

## Быстрое решение (автоматический скрипт):

Запустите скрипт исправления:
```bash
chmod +x fix_mac_tkinter.sh
./fix_mac_tkinter.sh
```

## Ручное решение для pyenv:

### Шаг 1: Установите tcl-tk
```bash
brew install tcl-tk
```

### Шаг 2: Определите путь к tcl-tk
```bash
# Для Apple Silicon (M1/M2/M3)
TCLTK_PATH="/opt/homebrew/opt/tcl-tk"

# Для Intel Mac
TCLTK_PATH="/usr/local/opt/tcl-tk"

# Или автоматически
TCLTK_PATH=$(brew --prefix tcl-tk)
```

### Шаг 3: Удалите текущую версию Python
```bash
# Узнайте текущую версию
python3 --version

# Удалите её (замените 3.12.7 на вашу версию)
pyenv uninstall 3.12.7
```

### Шаг 4: Установите Python заново с поддержкой tkinter
```bash
# Установите переменные окружения
export PATH="$TCLTK_PATH/bin:$PATH"
export LDFLAGS="-L$TCLTK_PATH/lib"
export CPPFLAGS="-I$TCLTK_PATH/include"
export PKG_CONFIG_PATH="$TCLTK_PATH/lib/pkgconfig"

# Установите Python
pyenv install 3.12.7

# Установите как глобальную версию
pyenv global 3.12.7
```

### Шаг 5: Переустановите зависимости
```bash
pip install -r requirements.txt
```

## Альтернативное решение (без переустановки):

### Вариант 1: Используйте системный Python macOS
```bash
/usr/bin/python3 portal.py --widget
```

### Вариант 2: Используйте Homebrew Python
```bash
brew install python@3.12
python3 portal.py --widget
```

## Проверка:

После установки проверьте:
```bash
python3 -c "import tkinter; print('✅ Tkinter работает!')"
```

Если ошибка сохраняется:
- Убедитесь что Homebrew обновлен: `brew update`
- Проверьте что tcl-tk установлен: `brew list tcl-tk`
- Проверьте переменные окружения перед установкой Python
