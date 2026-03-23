import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:portal_flutter/config.dart';
import 'package:portal_flutter/portal/framing.dart';
import 'package:portal_flutter/util/portal_host.dart';

Map<String, dynamic> _withSecret(Map<String, dynamic> msg, String secret) {
  final s = secret.trim();
  if (s.isEmpty) return msg;
  return {...msg, 'secret': s};
}

/// Читает короткий ответ сервера (OK / ERR / portal_auth_failed) с таймаутом простоя.
Future<(bool ok, String err)> _readPortalTcpAck(Socket socket) async {
  final buf = BytesBuilder(copy: false);
  try {
    await for (final chunk in socket.timeout(const Duration(seconds: 60))) {
      buf.add(chunk);
      if (buf.length > 1024) {
        return (false, 'bad_response');
      }
      final s = utf8.decode(buf.toBytes(), allowMalformed: true);
      if (s.contains('portal_auth_failed')) {
        return (false, 'auth');
      }
      if (s.startsWith('OK')) {
        return (true, 'ok');
      }
      if (s.startsWith('ERR')) {
        return (false, 'bad_response');
      }
    }
  } on TimeoutException {
    return (false, 'no_response');
  }
  return (false, 'no_response');
}

/// Пробует секреты по очереди, пока один не даст pong (для скана LAN / mesh).
Future<bool> pingPortalTrySecrets(
  String host, {
  required List<String> secrets,
  int port = portalPort,
  Duration? connectTimeout,
  Duration readTimeout = const Duration(seconds: 5),
}) async {
  final uniq = <String>[];
  final seen = <String>{};
  for (final s in secrets) {
    final t = s.trim();
    if (seen.contains(t)) continue;
    seen.add(t);
    uniq.add(t);
  }
  if (uniq.isEmpty) {
    return pingPortal(
      host,
      secret: '',
      port: port,
      connectTimeout: connectTimeout,
      readTimeout: readTimeout,
    );
  }
  for (final sec in uniq) {
    if (await pingPortal(
      host,
      secret: sec,
      port: port,
      connectTimeout: connectTimeout,
      readTimeout: readTimeout,
    )) {
      return true;
    }
  }
  return false;
}

Future<bool> pingPortal(
  String host, {
  String secret = '',
  int port = portalPort,
  Duration? connectTimeout,
  Duration readTimeout = const Duration(seconds: 5),
}) async {
  final h = host.trim();
  if (h.isEmpty || !isPlausiblePortalHost(h)) return false;
  Socket? socket;
  try {
    final addr = InternetAddress.tryParse(h);
    socket = addr != null
        ? await Socket.connect(
            addr,
            port,
            timeout: connectTimeout ?? portalConnectTimeout,
          )
        : await Socket.connect(
            h,
            port,
            timeout: connectTimeout ?? portalConnectTimeout,
          );
    final raw = jsonEncode(_withSecret({'type': 'ping'}, secret));
    socket.add(utf8.encode('$raw\n'));
    await socket.flush();
    // Ответ может прийти несколькими TCP-пакетами — копим буфер, как на десктопе.
    final buf = BytesBuilder(copy: false);
    await for (final data in socket.timeout(readTimeout)) {
      if (data.isEmpty) break;
      buf.add(data);
      final text = utf8.decode(buf.toBytes(), allowMalformed: true);
      if (text.contains('portal_auth_failed')) return false;
      final obj = parseFirstJsonObjectFromString(text);
      if (obj != null) {
        return obj['type'] == 'pong';
      }
      if (buf.length > 16384) break;
    }
    final tail = utf8.decode(buf.toBytes(), allowMalformed: true);
    if (tail.contains('portal_auth_failed')) return false;
    final obj = parseFirstJsonObjectFromString(tail);
    return obj != null && obj['type'] == 'pong';
  } catch (_) {
    return false;
  } finally {
    try {
      await socket?.close();
    } catch (_) {}
  }
}

Future<(bool ok, String err)> sendFileToPeer(
  String host,
  String filePath, {
  String secret = '',
  int port = portalPort,
}) async {
  final h = host.trim();
  if (h.isEmpty || !await File(filePath).exists()) {
    return (false, 'bad_args');
  }
  if (!isPlausiblePortalHost(h)) {
    return (
      false,
      'некорректный адрес — введи полный IP ПК (например 192.168.1.5), не одну цифру',
    );
  }
  Socket? socket;
  try {
    final f = File(filePath);
    final name = filePath.split(Platform.pathSeparator).last;
    final len = await f.length();
    final hdr = _withSecret(
      {
        'type': 'file',
        'filename': name,
        'filesize': len,
        'portal_source': 'flutter',
      },
      secret,
    );
    socket = await Socket.connect(h, port, timeout: const Duration(seconds: 30));
    // Не addStream(): на части сборок возможен рассинхрон с filesize (любой бинарник).
    // JPEG/PDF/DOCX — одни и те же байты; отдельной логики по типу файла не нужно.
    socket.add(utf8.encode('${jsonEncode(hdr)}\n'));
    const maxMem = 48 * 1024 * 1024;
    if (len <= maxMem) {
      final bytes = await f.readAsBytes();
      if (bytes.length != len) {
        return (false, 'size_changed');
      }
      socket.add(bytes);
    } else {
      var sent = 0;
      await for (final chunk in f.openRead(65536)) {
        socket.add(chunk);
        sent += chunk.length;
      }
      if (sent != len) {
        return (false, 'size_mismatch');
      }
    }
    await socket.flush();
    return _readPortalTcpAck(socket);
  } catch (e) {
    return (false, e.toString());
  } finally {
    try {
      await socket?.close();
    } catch (_) {}
  }
}

Future<(bool ok, String err)> sendTextToPeer(
  String host,
  String text, {
  String secret = '',
  int port = portalPort,
}) async {
  final h = host.trim();
  if (h.isEmpty) return (false, 'bad_host');
  if (!isPlausiblePortalHost(h)) {
    return (
      false,
      'некорректный адрес — введи полный IP ПК (например 192.168.1.5), не одну цифру',
    );
  }
  Socket? socket;
  try {
    final hdr = _withSecret(
      {
        'type': 'clipboard',
        'text': text,
        'portal_source': 'flutter',
      },
      secret,
    );
    socket = await Socket.connect(h, port, timeout: const Duration(seconds: 20));
    socket.add(utf8.encode('${jsonEncode(hdr)}\n'));
    await socket.flush();
    try {
      final data = await socket.timeout(const Duration(seconds: 12)).first;
      final s = utf8.decode(data);
      if (s.contains('portal_auth_failed')) return (false, 'auth');
    } catch (_) {
      return (true, 'ok');
    }
    return (true, 'ok');
  } catch (e) {
    return (false, e.toString());
  } finally {
    try {
      await socket?.close();
    } catch (_) {}
  }
}
