# Portal для Android (Kivy + Buildozer)

Тот же **TCP-протокол**, что у desktop [`portal.py`](../portal.py): порт **12345**, поле **`secret`** в первом JSON.

## Что сделано

- **`portal_protocol.py`** — `send_file_to_peer`, `send_text_clipboard`, поле **`portal_source: "android"`** (на ПК — уведомление «с телефона» + импульс виджета).
- **`android_share.py`** — чтение Share Intent (`SEND` / `SEND_MULTIPLE`), копирование `content://` во временный файл, Toast, `finish()`.
- **`main.py`** — экран настроек: список компьютеров (IP + имя), пароль сети, понятный онбординг; при **одном пире** — отправка сразу; при **нескольких** — «Куда отправить?» / **«На все компьютеры»**.
- **`intent_filters.xml` + `buildozer.spec`** — Portal в системном списке «Поделиться».
- **Без фонового сервиса**: Activity стартует из Share Sheet, отправляет и закрывается.

## Первый запуск

1. Установи APK, открой **Portal** один раз.
2. На ПК запусти Portal и посмотри **IP** в главном окне (часто `100.x.x.x` в Tailscale).
3. В приложении: **«+ Добавить IP компьютера»** → тот же IP, что на ПК сверху в Portal; **галочка** = «кому слать» (как на главном экране ПК); пароль — как **«Пароль сети (одинаковый на всех…)»** в ⚙ → **«Сохранить список IP и выбор»**.
4. Иконка лаунчера: положи `assets/icon.png` (скрипт из десктопа: `python3 scripts/generate_branding_icons.py`) и пересобери APK.
5. Можно **закрыть приложение**. Дальше: **Поделиться** → **Portal**.

## Huawei Pura 70 Pro и прочие без Google Play

- Включи установку из неизвестных источников для браузера/файлового менеджера, с которого ставишь APK.
- На части прошивок нужно отключить «чистый режим» / разрешить установку вручную.
- Это **обычный debug APK** (подпись debug). Для постоянного использования позже можно собрать **release** с своей подписью.

## Сборка APK

Нужен **Linux** или **Docker** (на macOS нативный Buildozer часто проблемный).

### Docker (с папки `portal-android`)

```bash
docker build -t portal-buildozer .
docker run --rm -v "$PWD":/home/user/host portal-buildozer
ls -la bin/*.apk
```

### GitHub Actions

В корне репозитория: **`.github/workflows/portal-android-apk.yml`**. После успешной сборки:

- **Release** с тегом **`portal-android-latest`** и файлом **`Portal-Android.apk`** (удобно для кнопки «Скачать APK» в десктопе).
- Артефакт **`portal-debug-apk`** (как запасной вариант).

На runner **явно ставится JDK 17** (`setup-java` + фиксация `JAVA_HOME`): иначе buildozer часто находит **Java 11** с образа и падает на Gradle. **Cython** в CI пинится как **`>=0.29.36,<3.0`**: с Cython 3.x не собирается **PyJNIUS** (`long` в `jnius_utils.pxi`). В CI по умолчанию только **arm64-v8a**; в `buildozer.spec` можно оставить **две ABI** для локальной/Docker-сборки.

Копия шаблона в этой папке: **`github-workflow-portal-android-apk.yml`**.

### Локальный Linux

```bash
cd portal-android
pip install buildozer cython
buildozer android debug
```

## Ассеты

- **`assets/icon.png`** — иконка приложения (`buildozer.spec` → `icon.filename`). Генерируется вместе с десктопными иконками: из корня репо `python3 scripts/generate_branding_icons.py`.
- Дополнительно можно положить GIF/картинку в `assets/` для фона (по желанию).

## Quick Settings tile

Не реализовано (опционально для power-users); основной сценарий — **Share Sheet**.

## Связь с десктопом

- На ПК: Портал запущен, пароль сети совпадает, файрвол пускает порт **12345**.
- В приложении те же **IP** (LAN / Tailscale) и **secret**.
