Локальный плагин Portal: после приёма файла копирует его в **Загрузки/Portal** через `MediaStore` (Android 10+) или прямой путь (ниже API 29).

Регистрируется в `.flutter-plugins`, поэтому **MethodChannel доступен и из foreground service** (второй FlutterEngine).
