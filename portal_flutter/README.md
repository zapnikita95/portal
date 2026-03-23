# Portal Flutter

**Основной мобильный клиент Portal** — один проект **Android + iOS** (один код). Kivy **Portal-Android.apk** в репозитории остаётся как legacy.

## Возможности

- **Приём** файлов и текста с ПК по TCP `:12345` (тот же протокол, что у десктопа): на Android — foreground service в фоне + текст приёма в уведомлении; на iOS — пока приложение на экране + локальное уведомление о приёме.
- **Куда сохраняются файлы (Android, папка по умолчанию):** `Android/data/org.portal.portal_flutter/files/PortalReceive` на внутренней памяти — открывается из приложения «Файлы» (иногда нужно включить показ `Android/data`). Старый путь `…/app_flutter/PortalReceive` использовался до смены дефолта; при пустом поле «Папка приёма» новые файлы идут во внешнюю папку приложения.
- **Уведомление приёма:** локально патчится `flutter_background_service_android` (`setOngoing(false)`), чтобы его можно было смахнуть; на части прошивок ОС всё равно может требовать видимый индикатор, пока включён приём.
- **Отправка** файла (в т.ч. через **Поделиться → Portal**) и текста на отмеченные пиры. В `AndroidManifest.xml` должны быть `SEND` / `SEND_MULTIPLE` — их добавляет **`tool/patch_android_manifest.py`** (в CI после `flutter create`; без этого Portal не виден в шаринге).
- **Пиры** (иконка радара **Ping** у строки — проверка `pong`; результат во **всплывающей строке** внизу экрана). На ПК в журнале **ping не пишется** специально (чтобы не спамить при авто-проверке); для отладки: `PORTAL_VERBOSE_PING=1` при запуске Портала.
- **История** (вкладка внизу) — SQLite: приём и отправка, **повтор** файла на те же IP, копирование пути/текста.

## iPhone / iPad

Пошаговая установка и ограничения фона: **[IOS_INSTALL.md](IOS_INSTALL.md)**  
(в веб-репозитории: `…/blob/main/portal_flutter/IOS_INSTALL.md`.)

**Не APK:** для iOS нет одного файла «как .apk» в релизе; обычно сборка в **Xcode** или артефакт **Portal-Flutter-iOS-nosign.zip** из workflow **Portal Flutter Build** (job `ios-nosign`).

## Сборка локально

```bash
cd portal_flutter
flutter create . --project-name portal_flutter --org org.portal --platforms=android,ios   # один раз
python3 tool/patch_android_manifest.py   # Android
python3 tool/patch_ios_info_plist.py     # iOS: уведомления
flutter pub get
dart run flutter_launcher_icons        # иконка из assets/branding/portal_icon.png (iOS сразу; Android — после create в pubspec android: true)
flutter run
```

`tool/patch_android_manifest.py` дублируется в CI после `flutter create`.

## Отладка Android: `adb` и logcat

Команда в терминале **`adb`** — это не Python. Она из **Android SDK Platform Tools** (Google), не из `pip install adb` (это другой пакет).

**macOS — проще всего:**
```bash
brew install android-platform-tools
adb version
```

Либо путь из Android Studio: `~/Library/Android/sdk/platform-tools` — добавь в `PATH`.

**Снять лог при краше** (USB, на телефоне включена отладка по USB):
```bash
adb devices
adb logcat -c && adb logcat '*:E' 'AndroidRuntime:E' 'flutter:V' | tee portal_crash.txt
```
В **zsh** фильтры вроде `*:E` обязательно в **кавычках**, иначе shell подставит имена файлов из текущей папки.

**Иконка приложения:** исходник — `assets/branding/portal_icon.png` (копия брендинга репозитория). После смены картинки снова `dart run flutter_launcher_icons`. Для Android в `pubspec.yaml` у `flutter_launcher_icons` выставь `android: true` (когда есть папка `android/`).

## CI

Workflow **Portal Flutter Build**: артефакт `portal-flutter-apk`, релиз `portal-flutter-latest` с `Portal-Flutter.apk`. iOS: job `ios-nosign` — zip `Runner.app` без подписи (TestFlight — локальная подпись).

## APK / бинарники «не открываются» после передачи

Причина была в **мобильном приёме**: поток TCP читался небезопасно для сокета + лишние `flush` при отправке. Исправлено: один `StreamIterator` на соединение, `addStream` при отправке файла. Имя сохранённого файла — **как на десктопе** (`имя.apk`, при коллизии `имя_время.apk`), без префикса `время_`.

**Ping «нет ответа»:** на ПК должны быть нажаты **«Запустить портал»**, порт **12345**, в приложении — **тот же пароль**, что в `config.json` на ПК; проверь mesh-VPN и файрвол.

**LAN «Найти в LAN»:** на экране **Пиры** выбери сегмент **Wi‑Fi** (192.168.x), **mesh** (только mesh-VPN 100.64–127.x) или **Все**. Скан идёт **с телефона** по выбранным подсетям. В репозитории уже есть `android/`; при пересоздании проекта прогони `python3 tool/patch_android_manifest.py` и `patch_android_gradle.py`.

**Приём с десктопа:** десктоп шлёт `ping` **без перевода строки**; приём на Flutter теперь парсит так же, как Python (`read_first_json`), а не только `json\\n`.

## App Store

Не обязателен на старте: APK вручную, TestFlight после подписи iOS.
