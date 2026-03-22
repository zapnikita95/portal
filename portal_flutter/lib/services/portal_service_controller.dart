import 'dart:io';

import 'package:flutter_background_service/flutter_background_service.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:portal_flutter/services/bg_entry.dart';
import 'package:portal_flutter/services/ios_receive_runner.dart';

class PortalServiceController {
  static Future<void> initialize() async {
    final s = FlutterBackgroundService();
    await s.configure(
      androidConfiguration: AndroidConfiguration(
        onStart: portalBackgroundMain,
        isForegroundMode: true,
        autoStart: false,
        notificationChannelId: 'portal_fg',
        initialNotificationTitle: 'Portal',
        initialNotificationContent: 'Приём файлов :12345',
        foregroundServiceNotificationId: 889,
        foregroundServiceTypes: [AndroidForegroundType.dataSync],
      ),
      iosConfiguration: IosConfiguration(
        autoStart: false,
        onBackground: onIosBackground,
      ),
    );
  }

  static Future<bool> androidRunning() async =>
      FlutterBackgroundService().isRunning();

  /// Дожидаемся, пока плагин увидит сервис (иначе тумблер остаётся «выкл» сразу после старта).
  static Future<void> startAndroidReceive() async {
    final n = await Permission.notification.request();
    if (n != PermissionStatus.granted) {
      throw StateError(
        'Нужны уведомления для фонового приёма (разреши в настройках).',
      );
    }
    final s = FlutterBackgroundService();
    if (!await s.isRunning()) {
      await s.startService();
    } else {
      s.invoke('reload');
    }
    for (var i = 0; i < 50; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 100));
      if (await s.isRunning()) {
        return;
      }
    }
    throw StateError(
      'Foreground service не поднялся за ~5 с. Проверь разрешения, батарею (без ограничений) и logcat.',
    );
  }

  static Future<void> stopAndroidReceive() async {
    final s = FlutterBackgroundService();
    if (await s.isRunning()) {
      s.invoke('stopIt');
    }
  }

  static Future<void> startIosReceive() => IosReceiveRunner.start();
  static Future<void> stopIosReceive() => IosReceiveRunner.stop();
  static bool get iosRunning => IosReceiveRunner.isRunning;

  static Future<void> startReceiveForPlatform() async {
    if (Platform.isAndroid) {
      await startAndroidReceive();
    } else {
      await startIosReceive();
    }
  }

  static Future<void> stopReceiveForPlatform() async {
    if (Platform.isAndroid) {
      await stopAndroidReceive();
    } else {
      await stopIosReceive();
    }
  }

  static Future<void> reloadAndroidReceive() async {
    if (Platform.isAndroid && await androidRunning()) {
      FlutterBackgroundService().invoke('reload');
    }
  }

  /// После смены папки приёма / пароля: перезапустить сервис, если приём был включён.
  static Future<void> reloadReceiveIfRunning() async {
    if (Platform.isAndroid) {
      await reloadAndroidReceive();
      return;
    }
    if (Platform.isIOS && iosRunning) {
      await stopIosReceive();
      await startIosReceive();
    }
  }
}
