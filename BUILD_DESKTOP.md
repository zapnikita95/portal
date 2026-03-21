# Сборка Portal для Windows (.exe) и macOS (.app)

Обычный запуск без терминала: **двойной клик** по `Portal.exe` (Windows) или **`Portal.app`** (Mac).

## Сразу: получить Portal.app на Mac (у себя на компьютере)

В терминале из **корня репозитория** (`~/Desktop/portal` или где лежит проект):

```bash
cd ~/Desktop/portal
python3 -m pip install -r requirements.txt pyinstaller pillow
python3 scripts/generate_branding_icons.py
pyinstaller -y pyinstaller_portal.spec
open dist/Portal.app
```

Готовое приложение: **`dist/Portal.app`**. Его можно перетащить в папку «Программы».

**DMG одной командой** (рядом появятся `dist/Portal-macOS.zip` и `dist/Portal-macOS.dmg`):

```bash
chmod +x scripts/build_mac_dmg.sh
./scripts/build_mac_dmg.sh
```

Проверка, что на macOS хоткеи не зависят от таймера `after()` при свёрнутом окне:

```bash
python3 scripts/test_mac_hotkey_fileevent.py
```

Флаг **`-y`** у PyInstaller автоматически подтверждает очистку старой **`dist/Portal`** — при пересборке это ожидаемо (иначе спрашивает `Continue? (y/N)` в терминале).

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

- **Вручную:** **Actions** → **Portal Desktop Build** → **Run workflow** → скачай артефакт `Portal-macOS` (внутри **ZIP + DMG**) и `Portal-Windows`.
- **Релиз:** `git tag v1.2.0 && git push origin v1.2.0` — к релизу прикрепятся **Portal-macOS.zip**, **Portal-macOS.dmg** и **Portal-Windows.zip**.

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

Из **`assets/portal_main.gif`** (первый кадр, без фона — хромакей как у виджета) пишется `assets/branding/portal_icon.png`, затем **`portal.ico`**, **`portal.icns`** и копия для Android:

```bash
python3 scripts/generate_branding_icons.py
```

Если нет Pillow: `pip install pillow`.

## 3. Сборка PyInstaller

**На той ОС, под которую собираешь** (exe — на Windows, app — на Mac):

```bash
pyinstaller -y pyinstaller_portal.spec
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

### Windows: `PermissionError` / WinError 5 при пересборке

Сообщение вроде **«Отказано в доступе»** при удалении `dist\Portal\...` почти всегда значит: **файлы заняты**.

1. **Закрой `Portal.exe`** (и любые копии из `dist\Portal`). В диспетчере задач проверь процессы **Portal**.
2. Закрой **Проводник**, если открыта папка `dist\Portal`.
3. Проект в **OneDrive** (`OneDrive\Desktop\...`) — синхронизация может держать файлы. Пауза синхронизации или сборка в копии проекта вне OneDrive (например `C:\dev\Portal`) часто решает проблему.
4. На время пересборки отключи **антивирусное сканирование** папки `dist` / `build` (или добавь исключение).
5. Потом снова: `pyinstaller -y pyinstaller_portal.spec`

В крайнем случае перезагрузка ПК снимает «залипшие» блокировки.

## 6. «Обычный» установщик (опционально)

Сборка PyInstaller даёт **портативную папку** — это нормально. Если нужен мастер «Далее → Далее»:

### Windows (.exe установщик) — Inno Setup 6.7.x, что жать

**Перед Inno:** в корне проекта уже есть сборка PyInstaller:

```text
pyinstaller -y pyinstaller_portal.spec
```

Должна существовать папка **`dist\Portal\`** с **`Portal.exe`** внутри и рядом папка **`_internal`** (и прочие dll) — **ничего из этого не выкидывать**.

#### Запуск мастера

1. Открой **Inno Setup Compiler**.
2. Либо **Файл → Создать** (*File → New*), в диалоге выбери **«Create a new script file using the Script Wizard»** / **создать скрипт с помощью мастера** → **ОК**.  
   Либо на панели инструментов нажми иконку **документ с волшебной палочкой** (тот же мастер).

#### Шаги мастера (Next / Далее везде, пока не сказано иначе)

| Шаг | Что выбрать |
|-----|-------------|
| **1. Приветствие** | **Next** |
| **2. Информация о приложении** | **Application name:** `Portal` (или как хочешь). **Version:** например `1.0.0`. **Publisher** — по желанию. **Next** |
| **3. Папка установки у пользователя** | Обычно уже стоит **Program Files** и подпапка с именем приложения — оставь, будет что-то вроде `{autopf}\Portal`. **Next** |
| **4. Главный исполняемый файл** | **Browse** → укажи **`...\твой_проект\dist\Portal\Portal.exe`**. **Next** |
| **5. Другие файлы приложения** | **Критично:** рядом с exe должны попасть **`_internal`** и все dll. Нажми **Add folder(s)** / **Добавить папку** → выбери папку **`dist\Portal`** (ту самую, где лежит `Portal.exe`). Если спросят про вложенные папки — **включи подпапки** (*subfolders* / *recurse*). **Next** |
| **6. Ярлыки** | Включи **Start Menu** (меню «Пуск»). По желанию — **Desktop** (рабочий стол). **Next** |
| **7. Лицензия / инфо** | Можно ничего не указывать. **Next** |
| **8. Режим установки** | Обычно «для всех пользователей» или как предложит мастер — ок для домашнего ПК. **Next** |
| **9. Выход компилятора** | **Output folder** — куда положить готовый установщик (например Рабочий стол или `installer`). **Output base filename** — имя файла без `.exe`, например `PortalSetup`. **Next** |
| **10. Готово** | Если стоит галочка **сразу скомпилировать** — нажми **Finish** и дождись конца. Иначе **Finish**, потом в меню **Build → Compile** (*Сборка → Компилировать*) или клавиша **F9**. |

#### После компиляции

- В папке из шага 9 появится **`PortalSetup.exe`** (или как назвал).
- При установке программа окажется в **`Program Files\Portal\`** (или аналог); там же рядом с **`Portal.exe`** должна быть **`_internal`**.

#### Если установщик ставит только один exe без `_internal`

Мастер иногда кладёт файлы не так. Открой сгенерированный **`.iss`**, найди секцию **`[Files]`** и проверь, что есть строка в духе (путь подставь свой):

```iss
Source: "C:\ПУТЬ\К\ПРОЕКТУ\dist\Portal\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
```

Сохрани **.iss** и снова **Build → Compile** (F9).

---

**Кратко:** волшебная палочка → **Next** по шагам → **Browse** на **`dist\Portal\Portal.exe`** → **Add folder** на **`dist\Portal`** с подпапками → ярлыки → папка вывода → **Finish** / **F9**.

Альтернативы: **NSIS**, **WiX Toolset** — по сути то же: упаковать содержимое `dist/Portal` в Program Files + ярлык.

### macOS (.dmg)

1. После сборки лежит **`dist/Portal.app`**.
2. В **Дисковой утилите** → **Файл → Новый образ → Пустой образ** → перетащи в открывшееся окно **`Portal.app`** и (по желанию) ярлык на папку «Программы» → сохрани как `.dmg`.  
   Либо утилита **`create-dmg`** (Homebrew: `brew install create-dmg`) — удобнее для красивого окна «перетащи в Программы».

Подпись и нотаризация для чужих Mac — отдельно, нужен **Apple Developer Program**; без этого пользователи всё равно могут обойти карантин (`xattr`), см. выше.

Общий обзор «ZIP vs установщик»: **[DISTRIBUTION.md](DISTRIBUTION.md)**.
