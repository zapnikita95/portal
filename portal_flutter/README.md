# Portal Flutter

Один проект **Android + iOS** (один код). Это **отдельное приложение** от Kivy **Portal-Android.apk** до полной миграции; на GitHub два артефакта: `Portal-Android.apk` (Python) и `Portal-Flutter.apk` (этот клиент).

## App Store

Не обязателен на старте: APK вручную, TestFlight после подписи iOS.

## Локальная сборка

```bash
cd portal_flutter
flutter create . --project-name portal_flutter --org org.portal --platforms=android,ios   # один раз
flutter pub get
flutter run
```

В `android/app/src/main/AndroidManifest.xml` для LAN/TCP без TLS на `:12345` нужен `android:usesCleartextTraffic="true"` у `<application>` (в CI это делает workflow).

## Что уже есть

- Экран с IP, паролем и **Ping** — проверка `pong` как на десктопе (`lib/services/portal_client.dart`).

## Дальше

- Отправка файла/текста (JSON + поток байт), приём в isolate, список пиров, SQLite-история по образцу `portal_history.py`.

## CI

Workflow **Portal Flutter Build**: артефакт `portal-flutter-apk`, релиз `portal-flutter-latest` с `Portal-Flutter.apk`. iOS: job `ios-nosign` — zip `Runner.app` без подписи.
