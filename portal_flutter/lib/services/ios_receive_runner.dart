import 'dart:io';

import 'package:portal_flutter/config.dart';
import 'package:portal_flutter/data/settings_repository.dart';
import 'package:portal_flutter/portal/portal_receive_mdns.dart';
import 'package:portal_flutter/portal/portal_secrets.dart';
import 'package:portal_flutter/portal/receive_session.dart';
import 'package:portal_flutter/services/portal_notifications.dart';
import 'package:portal_flutter/util/receive_paths.dart';

/// Приём на iOS: TCP пока приложение на экране (процесс активен).
/// В фоне iOS не держит произвольный TCP-сервер — см. IOS_INSTALL.md в репозитории.
class IosReceiveRunner {
  static ServerSocket? _server;

  static Future<void> start() async {
    await stop();
    final st = await SettingsRepository.load();
    final dir = await resolveReceiveDir(st.receiveDir);
    try {
      _server = await ServerSocket.bind(
        InternetAddress.anyIPv4,
        portalPort,
        shared: true,
      );
    } catch (e) {
      throw StateError(
        'Не удалось слушать :$portalPort на iPhone ($e). '
        'Порт занят или запрещён; закрой другие копии / VPN.',
      );
    }
    _server!.listen((Socket client) {
      handlePortalSocket(
        client,
        receiveDir: dir,
        acceptedSecrets: PortalSecrets.acceptedSecretsForReceive(st),
        onEvent: (_, msg, __) async {
          await PortalNotifications.showReceiveLine(msg);
        },
      );
    });
    await PortalReceiveMdns.start(mdnsDisplayName: st.mdnsDisplayName);
  }

  static Future<void> stop() async {
    await PortalReceiveMdns.stop();
    try {
      await _server?.close();
    } catch (_) {}
    _server = null;
  }

  static bool get isRunning => _server != null;
}
