import 'dart:io';

import 'package:flutter/services.dart';

/// Копия файла в **Загрузки → Portal** (видно в приложении «Загрузки»).
/// Работает из основного и фонового Flutter Engine (плагин в .flutter-plugins).
class PortalAndroidDownloads {
  PortalAndroidDownloads._();

  static const MethodChannel _ch = MethodChannel('org.portal.portal/downloads');

  static Future<bool> copyToDownloadsPortal(
    String sourceAbsolutePath,
    String displayFileName,
  ) async {
    if (!Platform.isAndroid) return false;
    if (sourceAbsolutePath.isEmpty || displayFileName.isEmpty) return false;
    try {
      final r = await _ch.invokeMethod<Map<dynamic, dynamic>>(
        'saveToDownloadsPortal',
        <String, dynamic>{
          'path': sourceAbsolutePath,
          'displayName': displayFileName,
        },
      );
      return r != null && r['ok'] == true;
    } catch (_) {
      return false;
    }
  }
}
