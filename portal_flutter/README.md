# Portal Flutter

**Основной мобильный клиент Portal** — один проект **Android + iOS** (один код). Kivy **Portal-Android.apk** в репозитории остаётся как legacy.

## Возможности

- **Приём** файлов и текста с ПК по TCP `:12345` (тот же протокол, что у десктопа): на Android — foreground service в фоне + текст приёма в уведомлении; на iOS — пока приложение на экране + локальное уведомление о приёме.
- **Отправка** файла (в т.ч. через **Share** в приложение) и текста на отмеченные пиры.
- **Пиры** (иконка радара **Ping** у строки — проверка `pong` с ПК), **пароль сети**, папка приёма.
- **История** (вкладка внизу) — SQLite: приём и отправка, **повтор** файла на те же IP, копирование пути/текста.

## iPhone / iPad

Пошаговая установка и ограничения фона: **[IOS_INSTALL.md](IOS_INSTALL.md)**.

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

## App Store

Не обязателен на старте: APK вручную, TestFlight после подписи iOS.
