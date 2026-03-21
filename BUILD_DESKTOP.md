# Сборка Portal для Windows (.exe) и macOS (.app)

Обычный запуск без терминала: **двойной клик** по `Portal.exe` (Windows) или **`Portal.app`** (Mac).

## Сразу: получить Portal.app на Mac (у себя на компьютере)

В терминале из **корня репозитория** (`~/Desktop/portal` или где лежит проект):

```bash
cd ~/Desktop/portal
python3 -m pip install -r requirements.txt pyinstaller pillow
python3 scripts/generate_branding_icons.py
pyinstaller pyinstaller_portal.spec
open dist/Portal.app
```

Готовое приложение: **`dist/Portal.app`**. Его можно перетащить в папку «Программы».

Если macOS пишет, что файл из интернета и не открывается:

```bash
xattr -dr com.apple.quarantine dist/Portal.app
```

*(Виртуальное окружение `python3 -m venv .venv` по желанию — см. раздел «Подготовка» ниже.)*

---

## GitHub Actions: ошибка `without workflow scope`

Если при `git push` видишь:

`refusing to allow a Personal Access Token to create or update workflow ... without workflow scope`

это **ограничение GitHub для HTTPS + PAT**: таким токеном **нельзя** менять файлы в `.github/workflows/`.

### Вариант 1 — через сайт GitHub (без токена, проще всего)

1. Открой репозиторий на github.com → **Add file** → **Create new file**.
2. Имя файла: **`.github/workflows/portal-desktop-release.yml`** (GitHub сам создаст папки).
3. Открой на компьютере **`github-workflow-portal-desktop.yml`** из этого репо, скопируй **весь** текст → вставь в редактор на GitHub.
4. **Commit changes** (внизу).

После этого workflow уже в репо, `git pull` у себя — и можно пользоваться Actions.

### Вариант 2 — дать PAT право `workflow` (classic token)

GitHub → **Settings** → **Developer settings** → **Personal access tokens** → свой токен → **Edit** → включи scope **`workflow`** → сохрани. Потом снова `git push`.

### Вариант 3 — SSH вместо HTTPS

```bash
git remote set-url origin git@github.com:zapnikita95/portal.git
git push origin main
```

(Нужен SSH-ключ, добавленный в GitHub.)

### Если остался локальный коммит с workflow, а push не прошёл

Чтобы не путаться с историей:

```bash
git fetch origin
git reset --hard origin/main
```

Потом добавь workflow **через сайт** (вариант 1) или исправь токен/SSH и запушь снова.

---

## Сборка в облаке (GitHub Actions)

После того как файл **`portal-desktop-release.yml`** уже лежит в **`.github/workflows/`** (через веб или push с нужными правами):

- **Вручную:** **Actions** → **Portal Desktop Build** → **Run workflow** → скачай артефакты `Portal-macOS` / `Portal-Windows`.
- **Релиз:** `git tag v1.2.0 && git push origin v1.2.0` — к релизу прикрепятся оба ZIP.

Шаблон для копирования: **`github-workflow-portal-desktop.yml`** в корне репозитория.

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
