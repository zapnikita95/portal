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
