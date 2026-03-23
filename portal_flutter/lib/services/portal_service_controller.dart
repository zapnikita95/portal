import 'dart:io';

import 'package:flutter_background_service/flutter_background_service.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:portal_flutter/services/bg_entry.dart';
import 'package:portal_flutter/services/portal_notifications.dart';
import 'package:portal_flutter/services/ios_receive_runner.dart';

class PortalServiceController {
  static Future<void> initialize() async {
    final s = FlutterBackgroundService();
    await s.configure(
      androidConfiguration: AndroidConfiguration(
        onStart: portalBackgroundMain,
        isForegroundMode: true,
        autoStart: false,
        notificationChannelId:
            PortalNotifications.androidForegroundChannelId,
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
    // Уведомления нужны для FGS-уведомления. Если отказано — продолжаем без них (FGS всё равно может работать).
    try {
      final n = await Permission.notification.request();
      if (n == PermissionStatus.permanentlyDenied) {
        throw StateError(
          'Уведомления заблокированы насовсем. Включи в Настройки → Приложения → Portal → Уведомления.',
        );
      }
    } catch (e) {
      if (e is StateError) rethrow;
      // permission_handler может кидать исключение на некоторых прошивках — игнорируем.
    }

    final s = FlutterBackgroundService();
    try {
      if (!await s.isRunning()) {
        await s.startService();
      } else {
        s.invoke('reload');
        return;
      }
    } catch (e) {
      throw StateError(
        'Не удалось запустить FGS: $e\n'
        'Android 14+: нужен foregroundServiceType в AndroidManifest. '
        'Пересобери APK или открой logcat.',
      );
    }
    for (var i = 0; i < 50; i++) {
      await Future<void>.delayed(const Duration(milliseconds: 100));
      if (await s.isRunning()) return;
    }
    throw StateError(
      'Foreground service не поднялся за ~5 с. '
      'Проверь батарею (без ограничений), уведомления и logcat.',
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
