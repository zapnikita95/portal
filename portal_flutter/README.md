# Portal Flutter

**Основной мобильный клиент Portal** — один проект **Android + iOS** (один код). Kivy **Portal-Android.apk** в репозитории остаётся как legacy.

## Возможности

- **Приём** файлов и текста с ПК по TCP `:12345` (тот же протокол, что у десктопа): на Android — foreground service в фоне; на iOS — пока приложение активно.
- **Отправка** файла (в т.ч. через **Share** в приложение) и текста на отмеченные пиры.
- **Пиры**, **пароль сети**, папка приёма; **история** (SQLite) с повтором файла и копированием пути/текста.

## Сборка локально

```bash
cd portal_flutter
flutter create . --project-name portal_flutter --org org.portal --platforms=android,ios   # один раз
python3 tool/patch_android_manifest.py   # cleartext LAN + FGS + POST_NOTIFICATIONS
flutter pub get
flutter run
```

`tool/patch_android_manifest.py` дублируется в CI после `flutter create`.

## CI

Workflow **Portal Flutter Build**: артефакт `portal-flutter-apk`, релиз `portal-flutter-latest` с `Portal-Flutter.apk`. iOS: job `ios-nosign` — zip `Runner.app` без подписи (TestFlight — локальная подпись).

## App Store

Не обязателен на старте: APK вручную, TestFlight после подписи iOS.
