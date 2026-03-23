import 'dart:io';

import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';

/// Папка приёма по умолчанию.
///
/// На Android — **внешняя память приложения** (`Android/data/<package>/files/PortalReceive`):
/// её проще открыть из «Файлов», чем приватный `app_flutter` под `/data/user/0/...`
/// (туда без root обычно не попасть).
Future<String> resolveReceiveDir(String configured) async {
  final t = configured.trim();
  if (t.isNotEmpty) {
    await Directory(t).create(recursive: true);
    return t;
  }
  if (Platform.isAndroid) {
    try {
      final ext = await getExternalStorageDirectory();
      if (ext != null && ext.path.isNotEmpty) {
        final sub = Directory(p.join(ext.path, 'PortalReceive'));
        await sub.create(recursive: true);
        return sub.path;
      }
    } catch (_) {
      // fallback ниже
    }
  }
  final d = await getApplicationDocumentsDirectory();
  final sub = Directory(p.join(d.path, 'PortalReceive'));
  if (!await sub.exists()) {
    await sub.create(recursive: true);
  }
  return sub.path;
}

/// Проверка, что в папку реально можно писать (SAF-путь с фона может не работать).
Future<(bool ok, String err)> validateReceiveDirWritable(String configured) async {
  final t = configured.trim();
  if (t.isEmpty) return (true, '');
  try {
    final d = Directory(t);
    await d.create(recursive: true);
    final test = File(
      p.join(
        d.path,
        '.portal_write_test_${DateTime.now().microsecondsSinceEpoch}',
      ),
    );
    await test.writeAsString('ok', flush: true);
    final ex = await test.exists();
    try {
      await test.delete();
    } catch (_) {}
    if (!ex) {
      return (false, 'Не удалось создать тестовый файл в выбранной папке.');
    }
    return (true, '');
  } catch (e) {
    return (false, 'Папка недоступна для записи: $e');
  }
}
