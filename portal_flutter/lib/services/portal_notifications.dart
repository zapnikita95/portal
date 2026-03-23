import 'dart:io';

import 'package:flutter_local_notifications/flutter_local_notifications.dart';

/// Локальные уведомления при приёме (актуально для iOS в foreground).
/// На Android текст приёма обновляется в уведомлении foreground service из [bg_entry.dart].
class PortalNotifications {
  PortalNotifications._();

  /// Должен совпадать с [AndroidConfiguration.notificationChannelId] в [PortalServiceController].
  /// Канал обязан существовать до `FlutterBackgroundService.configure()` — иначе FGS:
  /// `RemoteServiceException: Bad notification for startForeground` (часто Huawei / Android 13+).
  static const String androidForegroundChannelId = 'portal_fg';

  static final FlutterLocalNotificationsPlugin _plugin =
      FlutterLocalNotificationsPlugin();
  static bool _inited = false;

  static Future<void> init() async {
    if (_inited) return;
    _inited = true;

    const androidInit = AndroidInitializationSettings('@mipmap/ic_launcher');
    const iosInit = DarwinInitializationSettings(
      requestAlertPermission: true,
      requestBadgePermission: true,
      requestSoundPermission: true,
    );
    const init = InitializationSettings(
      android: androidInit,
      iOS: iosInit,
    );
    await _plugin.initialize(init);

    if (Platform.isAndroid) {
      final android = _plugin.resolvePlatformSpecificImplementation<
          AndroidFlutterLocalNotificationsPlugin>();
      // IMPORTANCE_LOW на части прошивок даёт «Bad notification» при startForeground.
      const channel = AndroidNotificationChannel(
        androidForegroundChannelId,
        'Portal · приём по сети',
        description: 'Фоновый приём файлов с ПК (порт 12345)',
        importance: Importance.defaultImportance,
        playSound: false,
        enableVibration: false,
        showBadge: false,
      );
      await android?.createNotificationChannel(channel);
    }

    if (Platform.isIOS) {
      await _plugin
          .resolvePlatformSpecificImplementation<
              IOSFlutterLocalNotificationsPlugin>()
          ?.requestPermissions(alert: true, badge: true, sound: true);
    }
  }

  /// Показать строку о приёме (iOS; на Android — опционально из UI).
  static Future<void> showReceiveLine(String body) async {
    if (body.isEmpty) return;
    final short = body.length > 160 ? '${body.substring(0, 160)}…' : body;
    if (Platform.isIOS) {
      const details = NotificationDetails(
        iOS: DarwinNotificationDetails(
          presentAlert: true,
          presentBadge: true,
          presentSound: true,
        ),
      );
      await _plugin.show(
        901,
        'Portal',
        short,
        details,
      );
    }
  }
}
