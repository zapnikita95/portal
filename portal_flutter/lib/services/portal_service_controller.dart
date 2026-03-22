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

  static Future<void> startAndroidReceive() async {
    await Permission.notification.request();
    final s = FlutterBackgroundService();
    if (!await s.isRunning()) {
      await s.startService();
    } else {
      s.invoke('reload');
    }
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
}
