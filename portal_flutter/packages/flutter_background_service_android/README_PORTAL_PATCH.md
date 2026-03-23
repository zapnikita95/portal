# Патч для Portal

Форк пакета `flutter_background_service_android` **6.3.1** с одним изменением:

- `BackgroundService.updateNotificationInfo()`: `setOngoing(false)` вместо `true`, чтобы уведомление foreground service можно было смахнуть после приёма файла (на части прошивок при `ongoing=true` оно «залипает»).

При обновлении зависимости сверьте версию с `pubspec.lock` и перенесите патч вручную.
