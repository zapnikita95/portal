import 'dart:io';
import 'dart:ui';

import 'package:flutter/widgets.dart';
import 'package:flutter_background_service/flutter_background_service.dart';
import 'package:portal_flutter/config.dart';
import 'package:portal_flutter/data/settings_repository.dart';
import 'package:portal_flutter/portal/receive_session.dart';
import 'package:portal_flutter/util/receive_paths.dart';
import 'package:shared_preferences/shared_preferences.dart';

@pragma('vm:entry-point')
void portalBackgroundMain(ServiceInstance service) async {
  WidgetsFlutterBinding.ensureInitialized();
  DartPluginRegistrant.ensureInitialized();

  ServerSocket? server;

  Future<void> startServer() async {
    try {
      await server?.close();
    } catch (_) {}
    server = null;
    final prefs = await SharedPreferences.getInstance();
    final st = await SettingsRepository.loadFromPrefs(prefs);
    final dir = await resolveReceiveDir(st.receiveDir);
    final ss = await ServerSocket.bind(
      InternetAddress.anyIPv4,
      portalPort,
      shared: true,
    );
    server = ss;
    ss.listen((Socket client) {
      handlePortalSocket(
        client,
        receiveDir: dir,
        secret: st.secret,
        onEvent: (k, msg, p) async {
          service.invoke('log', {'t': msg});
          if (Platform.isAndroid) {
            final line =
                msg.length > 96 ? '${msg.substring(0, 96)}…' : msg;
            try {
              // AndroidServiceInstance без импорта android-артефакта (iOS-сборка).
              // ignore: avoid_dynamic_calls
              (service as dynamic).setForegroundNotificationInfo(
                title: 'Portal · приём',
                content: line,
              );
            } catch (_) {}
          }
        },
      );
    });
  }

  await startServer();

  service.on('stopIt').listen((_) async {
    try {
      await server?.close();
    } catch (_) {}
    server = null;
    service.stopSelf();
  });

  service.on('reload').listen((_) async {
    await startServer();
  });
}

@pragma('vm:entry-point')
Future<bool> onIosBackground(ServiceInstance service) async {
  WidgetsFlutterBinding.ensureInitialized();
  DartPluginRegistrant.ensureInitialized();
  return true;
}
