# Сборка Portal для Windows (.exe) и macOS (.app)

Обычный запуск без терминала: **двойной клик** по `Portal.exe` (Windows) или **`Portal.app`** (Mac).

## Сборка в облаке (GitHub Actions)

Шаблон workflow лежит в корне: **`github-workflow-portal-desktop.yml`**. Скопируй в репозиторий:

```bash
mkdir -p .github/workflows
cp github-workflow-portal-desktop.yml .github/workflows/portal-desktop-release.yml
git add .github/workflows/portal-desktop-release.yml && git commit -m "ci: desktop build" && git push
```

*(Если push с Personal Access Token падает с ошибкой про `workflow` — у токена в GitHub → Settings → Developer settings нужен scope **workflow**, либо добавь файл через веб-интерфейс GitHub.)*

После появления workflow в `.github/workflows/`:

- **Вручную:** Actions → **Portal Desktop Build** → **Run workflow** → артефакты `Portal-macOS` / `Portal-Windows`.
- **Релиз:** `git tag v1.2.0 && git push origin v1.2.0` — к релизу прикрепятся оба ZIP.

Скилл Cursor: `.cursor/skills/portal-desktop-release/SKILL.md`.

## 1. Подготовка

```bash
cd portal   # корень репозитория
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller
```

## 2. Иконки (логотип приложения)

Из картинки `assets/branding/portal_icon.png` генерируются `portal.ico`, `portal.icns` и копия для Android:

```bash
python3 scripts/generate_branding_icons.py
```

Если нет Pillow: `pip install pillow`.

## 3. Сборка PyInstaller

**На той ОС, под которую собираешь** (exe — на Windows, app — на Mac):

```bash
pyinstaller pyinstaller_portal.spec
```

Результат:

| Платформа | Путь |
|-----------|------|
| Windows | `dist/Portal/Portal.exe` |
| macOS | `dist/Portal.app` |

Папку `dist/Portal/` (Windows) можно заархивировать в ZIP и отдать пользователю. На Mac — перетащить `Portal.app` в «Программы».

### macOS: карантин и подпись

Без подписи Apple может блокировать запуск:

```bash
xattr -dr com.apple.quarantine dist/Portal.app
```

Глобальные хоткеи: в «Конфиденциальность» выдай **Универсальный доступ** и **Мониторинг ввода** приложению **Portal** (или первому запуску — как система предложит).

### Windows

Иногда SmartScreen ругается на неподписанный exe — «Подробнее» → «Выполнить в любом случае» или подпиши сертификатом.

## 4. Что внутри сборки

- В каталоге рядом с exe лежит папка `_internal` (или всё внутри `.app`) — **не удалять**.
- Ресурсы `assets/` упакованы внутрь; конфиг по-прежнему в `%APPDATA%\Portal\` / `~/Library/Application Support/Portal/`.

## 5. Отладка без консоли

Сборка **без чёрного окна консоли**. Если нужен вывод в терминал — временно в `pyinstaller_portal.spec` поставь `console=True` для `EXE` и пересобери.
