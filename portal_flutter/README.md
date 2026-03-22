# Portal Flutter

**Основной мобильный клиент Portal** — один проект **Android + iOS** (один код). Kivy **Portal-Android.apk** в репозитории остаётся как legacy.

## Возможности

- **Приём** файлов и текста с ПК по TCP `:12345` (тот же протокол, что у десктопа): на Android — foreground service в фоне + текст приёма в уведомлении; на iOS — пока приложение на экране + локальное уведомление о приёме.
- **Отправка** файла (в т.ч. через **Share** в приложение) и текста на отмеченные пиры.
- **Пиры** (иконка радара **Ping** у строки — проверка `pong` с ПК), **пароль сети**, папка приёма.
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
flutter run
```

`tool/patch_android_manifest.py` дублируется в CI после `flutter create`.

## CI

Workflow **Portal Flutter Build**: артефакт `portal-flutter-apk`, релиз `portal-flutter-latest` с `Portal-Flutter.apk`. iOS: job `ios-nosign` — zip `Runner.app` без подписи (TestFlight — локальная подпись).

## APK / бинарники «не открываются» после передачи

Причина была в **мобильном приёме**: поток TCP читался небезопасно для сокета + лишние `flush` при отправке. Исправлено: один `StreamIterator` на соединение, `addStream` при отправке файла. Имя сохранённого файла — **как на десктопе** (`имя.apk`, при коллизии `имя_время.apk`), без префикса `время_`.

**Ping «нет ответа»:** на ПК должны быть нажаты **«Запустить портал»**, порт **12345**, в приложении — **тот же пароль**, что в `config.json` на ПК; проверь Tailscale и файрвол.

## App Store

Не обязателен на старте: APK вручную, TestFlight после подписи iOS.
