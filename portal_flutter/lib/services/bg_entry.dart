import 'dart:io';
import 'dart:ui';

import 'package:flutter/widgets.dart';
import 'package:path/path.dart' as p;
import 'package:flutter_background_service/flutter_background_service.dart';
import 'package:portal_flutter/config.dart';
import 'package:portal_flutter/data/settings_repository.dart';
import 'package:portal_flutter/portal/portal_receive_mdns.dart';
import 'package:portal_flutter/portal/portal_secrets.dart';
import 'package:portal_flutter/portal/receive_session.dart';
import 'package:portal_flutter/services/portal_notifications.dart';
import 'package:portal_flutter/util/receive_paths.dart';
import 'package:shared_preferences/shared_preferences.dart';

@pragma('vm:entry-point')
void portalBackgroundMain(ServiceInstance service) async {
  WidgetsFlutterBinding.ensureInitialized();
  DartPluginRegistrant.ensureInitialized();

  ServerSocket? server;

  Future<void> startServer() async {
    await PortalReceiveMdns.stop();
    try {
      await server?.close();
    } catch (_) {}
    server = null;
    final prefs = await SharedPreferences.getInstance();
    final st = await SettingsRepository.loadFromPrefs(prefs);
    String dir;
    try {
      dir = await resolveReceiveDir(st.receiveDir);
      // С фона Android запись в выбранный пользователем путь часто падает, хотя в UI проверка прошла.
      if (Platform.isAndroid && st.receiveDir.trim().isNotEmpty) {
        try {
          final probe = File(
            p.join(dir, '.portal_bg_write_${DateTime.now().microsecondsSinceEpoch}'),
          );
          await probe.writeAsString('1', flush: true);
          await probe.delete();
        } catch (_) {
          final fallback = await resolveReceiveDir('');
          service.invoke('log', {
            't': 'Папка из настроек недоступна из фона — пишу в приложение и копию в «Загрузки/Portal».',
          });
          dir = fallback;
        }
      }
    } catch (e) {
      service.invoke('log', {
        't': 'Папка приёма: $e — проверь настройки.',
      });
      rethrow;
    }
    late ServerSocket ss;
    try {
      // Android: shared:true часто даёт краш/конфликт с другим процессом; на iOS оставляем shared.
      ss = await ServerSocket.bind(
        InternetAddress.anyIPv4,
        portalPort,
        shared: !Platform.isAndroid,
      );
    } catch (e) {
      service.invoke('log', {
        't': 'Не удалось занять порт $portalPort: $e '
            '(занят другим приложением или запрет ОС).',
      });
      rethrow;
    }
    server = ss;
    service.invoke('log', {'t': 'Слушаю :$portalPort (приём с ПК)'});
    ss.listen(
      (Socket client) {
        handlePortalSocket(
          client,
          receiveDir: dir,
          acceptedSecrets: PortalSecrets.acceptedSecretsForReceive(st),
          onEvent: (k, msg, p) async {
            service.invoke('log', {'t': msg});
            if (k == 'auth_failed' && Platform.isAndroid) {
              await PortalNotifications.showAndroidAlert(
                title: 'Portal · пароль сети',
                body: msg,
                id: 904,
              );
            }
            if (k == 'receive_fail' && Platform.isAndroid) {
              await PortalNotifications.showAndroidAlert(
                title: 'Portal · приём файла',
                body: msg,
                id: 905,
              );
            }
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
      },
      onError: (Object e, StackTrace st) {
        service.invoke('log', {'t': 'Ошибка сокета: $e'});
      },
      cancelOnError: false,
    );
    final mdnsOk =
        await PortalReceiveMdns.start(mdnsDisplayName: st.mdnsDisplayName);
    if (mdnsOk) {
      service.invoke('log', {'t': 'mDNS: объявляю Portal в LAN (как на ПК)'});
    } else {
      service.invoke('log', {
        't': 'mDNS объявление недоступно (изолят/ОС) — приём :$portalPort работает; '
            'искать этот телефон по IP или TCP-скану.',
      });
    }
  }

  try {
    await startServer();
  } catch (e, st) {
    try {
      service.invoke('log', {'t': 'Фон Portal: $e'});
    } catch (_) {}
    assert(() {
      // ignore: avoid_print
      print('portalBackgroundMain startServer: $e\n$st');
      return true;
    }());
  }

  service.on('stopIt').listen((_) async {
    await PortalReceiveMdns.stop();
    try {
      await server?.close();
    } catch (_) {}
    server = null;
    service.stopSelf();
  });

  service.on('reload').listen((_) async {
    try {
      await startServer();
    } catch (e) {
      service.invoke('log', {'t': 'Reload: $e'});
    }
  });
}

@pragma('vm:entry-point')
Future<bool> onIosBackground(ServiceInstance service) async {
  WidgetsFlutterBinding.ensureInitialized();
  DartPluginRegistrant.ensureInitialized();
  return true;
}
