import 'dart:io';

import 'package:path_provider/path_provider.dart';

Future<String> resolveReceiveDir(String configured) async {
  final t = configured.trim();
  if (t.isNotEmpty) {
    await Directory(t).create(recursive: true);
    return t;
  }
  final d = await getApplicationDocumentsDirectory();
  final sub = Directory('${d.path}/PortalReceive');
  if (!await sub.exists()) {
    await sub.create(recursive: true);
  }
  return sub.path;
}
