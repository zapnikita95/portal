# Portal для Android (Kivy + Buildozer)

Тот же **TCP-протокол**, что у desktop [`portal.py`](../portal.py): порт **12345**, поле **`secret`** в первом JSON.

## Что сделано

- **`portal_protocol.py`** — `send_file_to_peer`, `send_text_clipboard`, поле **`portal_source: "android"`** (на ПК — уведомление «с телефона» + импульс виджета).
- **`android_share.py`** — чтение Share Intent (`SEND` / `SEND_MULTIPLE`), копирование `content://` во временный файл, Toast, `finish()`.
- **`main.py`** — настройки пиров (`[{"ip":"...","name":"ПК"}]`), shared secret; при **одном пире** — отправка сразу; при **нескольких** — всплывающее окно «Куда отправить?» и **«Все компы»**.
- **`intent_filters.xml` + `buildozer.spec`** — Portal в системном списке «Поделиться».
- **Без фонового сервиса**: Activity стартует из Share Sheet, отправляет и закрывается.

## Первый запуск

1. Установи APK, открой **Portal** один раз.
2. Вставь JSON пиров и пароль сети (как на ПК), нажми **Сохранить**.
3. Можно **закрыть приложение**. Дальше: Галерея / Файлы / браузер → **Поделиться** → **Portal**.

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

На runner **явно ставится JDK 17** (`setup-java`): иначе buildozer часто находит **Java 11** с образа и падает на Gradle. В CI по умолчанию собирается только **arm64-v8a** (меньше RAM/времени); в `buildozer.spec` по-прежнему можно **две ABI** для локальной/Docker-сборки.

Копия шаблона в этой папке: **`github-workflow-portal-android-apk.yml`**.

### Локальный Linux

```bash
cd portal-android
pip install buildozer cython
buildozer android debug
```

## Ассеты (анимация портала)

Положи GIF/картинку виджета (как на десктопе) в `assets/` — при желании подключи в KV (`Image` source `assets/...`). Без файла приложение работает.

## Quick Settings tile

Не реализовано (опционально для power-users); основной сценарий — **Share Sheet**.

## Связь с десктопом

- На ПК: Портал запущен, пароль сети совпадает, файрвол пускает порт **12345**.
- В приложении те же **IP** (LAN / Tailscale) и **secret**.
