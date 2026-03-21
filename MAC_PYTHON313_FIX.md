# Исправление для Python 3.13 на macOS

Если видишь `zsh: trace trap` (segfault) или ошибки при установке `pillow==10.2.0`:

## Проблема

Python 3.13 — очень новая версия, некоторые библиотеки (pillow, tkinterdnd2, customtkinter) могут работать нестабильно или падать с segfault.

## Решение: использовать Python 3.12

### Через pyenv (рекомендуется):

```bash
# Установи Python 3.12.7
pyenv install 3.12.7

# Используй его в этой папке
cd ~/Desktop/portal
pyenv local 3.12.7

# Проверь версию
python3 --version  # должно быть 3.12.7

# Переустанови зависимости
pip3 install -r requirements.txt

# Запусти
python3 portal.py --widget
```

### Через Homebrew:

```bash
# Установи Python 3.12
brew install python@3.12

# Используй его
python3.12 portal.py --widget
```

### Или используй системный Python macOS:

```bash
# macOS обычно имеет встроенный Python 3.9-3.11
/usr/bin/python3 portal.py --widget
```

## Если всё равно падает

1. **Обнови pip:**
   ```bash
   pip3 install --upgrade pip
   ```

2. **Установи pillow вручную (последняя версия):**
   ```bash
   pip3 install --upgrade pillow
   ```

3. **Проверь, что tkinter работает:**
   ```bash
   python3 -c "import tkinter; print('OK')"
   ```

4. **Если tkinter не работает** — см. `fix.sh` или `MAC_TKINTER_FIX.md`

## Альтернатива: без виджета

Если виджет не работает из-за Python 3.13, можно использовать **только главное окно**:

```bash
python3 portal.py  # без --widget
```

Всё остальное (отправка файлов, буфер) работает и без виджета.
