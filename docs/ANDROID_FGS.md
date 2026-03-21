# Android: Foreground Service + уведомления (реализовано)

## Что сделано

1. **`buildozer.spec`**
   - `services = receive:portal_receive_service.py:foreground` — отдельный процесс p4a.
   - Разрешения: `FOREGROUND_SERVICE`, `FOREGROUND_SERVICE_DATA_SYNC`, `POST_NOTIFICATIONS`, `WAKE_LOCK`.

2. **`portal_receive_service.py`**
   - Запускается, если в окружении есть `PYTHON_SERVICE_ARGUMENT` (так помечает p4a процесс сервиса).
   - Читает `portal_android_config.json`, поднимает `ReceiveServer` с `use_kivy_clock=False`.
   - `setAutoRestartService(True)` — перезапуск при падении (насколько позволяет OEM).

3. **`main.py`**
   - `android_start_receive_foreground_service()` / `android_stop_receive_foreground_service()` — JNI `org.portal.portalshare.ServiceReceive`.
   - При старте приложения на Android сначала пытается FGS; при ошибке — старый in-process `ReceiveServer`.
   - При **Сохранить** настройки: stop + повторный start сервиса (подхват пароля/папки).
   - `on_stop` не гасит FGS — приём остаётся в фоне.

4. **`android_notifier.py`**
   - По событиям `receive_file` / `receive_text` — второе уведомление (канал `portal_receive_v1`), androidx или support `NotificationCompat`.

## Ограничения

- **FileProvider / «Открыть файл»** из уведомления — следующий шаг (нужен `content://` и intent).
- Android 13+: для некоторых уведомлений может понадобиться runtime-запрос `POST_NOTIFICATIONS` (пока только manifest).
- Имя JNI-класса сервиса должно совпадать с p4a: сервис `receive` → `ServiceReceive`. Если сборка падает, смотри лог `adb logcat` и правь `_android_fgs_jni_service_class()` в `main.py`.

## Ручная проверка

После установки APK: сверни приложение, отправь файл с ПК — приём должен продолжиться; в шторке — уведомление FGS + при приёме — краткое уведомление.
