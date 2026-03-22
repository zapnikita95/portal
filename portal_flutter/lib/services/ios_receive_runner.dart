import 'dart:io';

import 'package:portal_flutter/config.dart';
import 'package:portal_flutter/data/settings_repository.dart';
import 'package:portal_flutter/portal/receive_session.dart';
import 'package:portal_flutter/util/receive_paths.dart';

/// Приём на iOS только пока приложение живёт (без долгого фона).
class IosReceiveRunner {
  static ServerSocket? _server;

  static Future<void> start() async {
    await stop();
    final st = await SettingsRepository.load();
    final dir = await resolveReceiveDir(st.receiveDir);
    _server = await ServerSocket.bind(
      InternetAddress.anyIPv4,
      portalPort,
      shared: true,
    );
    _server!.listen((Socket client) {
      handlePortalSocket(
        client,
        receiveDir: dir,
        secret: st.secret,
        onEvent: (_, __, ___) async {},
      );
    });
  }

  static Future<void> stop() async {
    try {
      await _server?.close();
    } catch (_) {}
    _server = null;
  }

  static bool get isRunning => _server != null;
}
