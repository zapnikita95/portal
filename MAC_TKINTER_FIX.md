# Исправление проблемы с tkinter на macOS

Если вы видите ошибку:
```
ModuleNotFoundError: No module named '_tkinter'
```

Это означает, что Python был установлен без поддержки Tkinter.

## Решение для pyenv:

1. **Установите tcl-tk через Homebrew:**
   ```bash
   brew install tcl-tk
   ```

2. **Переустановите Python через pyenv с поддержкой tkinter:**
   ```bash
   # Удалите текущую версию Python
   pyenv uninstall 3.12.7
   
   # Установите заново с указанием пути к tcl-tk
   export PATH="/opt/homebrew/opt/tcl-tk/bin:$PATH"
   export LDFLAGS="-L/opt/homebrew/opt/tcl-tk/lib"
   export CPPFLAGS="-I/opt/homebrew/opt/tcl-tk/include"
   export PKG_CONFIG_PATH="/opt/homebrew/opt/tcl-tk/lib/pkgconfig"
   
   pyenv install 3.12.7
   ```

3. **Или используйте системный Python:**
   ```bash
   # macOS обычно имеет встроенный Python с tkinter
   /usr/bin/python3 portal.py --widget
   ```

## Альтернативное решение:

Используйте Homebrew Python вместо pyenv:
```bash
brew install python@3.12
python3 portal.py --widget
```

## Проверка:

После установки проверьте:
```bash
python3 -c "import tkinter; print('Tkinter работает!')"
```

Если ошибка сохраняется, убедитесь что:
- Homebrew установлен и обновлен: `brew update`
- tcl-tk установлен: `brew list tcl-tk`
- Python переустановлен с правильными переменными окружения
