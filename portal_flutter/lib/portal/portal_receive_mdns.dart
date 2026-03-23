import 'dart:io';

import 'package:bonsoir/bonsoir.dart';
import 'package:portal_flutter/config.dart';

/// Объявление `_portal._tcp` в LAN, пока телефон слушает приём (как Python `portal_mdns.start_advertise`).
class PortalReceiveMdns {
  PortalReceiveMdns._();

  static BonsoirBroadcast? _broadcast;

  static String _defaultLabel() {
    if (Platform.isIOS) return 'Portal-iPhone';
    if (Platform.isAndroid) return 'Portal-Android';
    return 'Portal';
  }

  /// Имя экземпляра сервиса для Bonsoir (без спецсимволов, короткое).
  static String _safeServiceName(String display) {
    var s = display.trim();
    if (s.isEmpty) s = _defaultLabel();
    s = s.replaceAll(RegExp(r'[\x00-\x1f\x7f]'), '');
    s = s.replaceAll(RegExp(r'[^\p{L}\p{N}\-_. ]', unicode: true), '-');
    s = s.replaceAll(RegExp(r'^[\-_. ]+|[\-_. ]+$'), '');
    if (s.isEmpty) s = 'portal';
    return s.length > 63 ? s.substring(0, 63) : s;
  }

  /// Остановить объявление (перед закрытием сокета или перезапуском).
  static Future<void> stop() async {
    final b = _broadcast;
    _broadcast = null;
    if (b == null) return;
    try {
      await b.stop();
    } catch (_) {}
  }

  /// Запустить mDNS после успешного `ServerSocket.bind` + `listen`.
  /// `false` — не удалось (например плагин в изоляте FGS); приём TCP всё равно работает.
  static Future<bool> start({required String mdnsDisplayName}) async {
    await stop();
    if (!Platform.isIOS && !Platform.isAndroid) return false;

    final displayRaw = mdnsDisplayName.trim();
    final display = displayRaw.isEmpty ? _defaultLabel() : displayRaw;
    final dispTxt = display.length > 200 ? display.substring(0, 200) : display;
    final instanceName = _safeServiceName(display);

    try {
      final service = BonsoirService(
        name: instanceName,
        type: '_portal._tcp',
        port: portalPort,
        attributes: {
          ...BonsoirService.defaultAttributes,
          'display': dispTxt,
        },
      );
      final broadcast = BonsoirBroadcast(
        service: service,
        printLogs: false,
      );
      await broadcast.initialize();
      await broadcast.start();
      _broadcast = broadcast;
      return true;
    } catch (_) {
      _broadcast = null;
      return false;
    }
  }
}
