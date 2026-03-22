import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:portal_flutter/config.dart';

Map<String, dynamic> _withSecret(Map<String, dynamic> msg, String secret) {
  final s = secret.trim();
  if (s.isEmpty) return msg;
  return {...msg, 'secret': s};
}

Future<bool> pingPortal(
  String host, {
  String secret = '',
  int port = portalPort,
  Duration? connectTimeout,
  Duration readTimeout = const Duration(seconds: 5),
}) async {
  final h = host.trim();
  if (h.isEmpty) return false;
  Socket? socket;
  try {
    socket = await Socket.connect(
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
      final obj = _firstJsonObject(text);
      if (obj != null) {
        return obj['type'] == 'pong';
      }
      if (buf.length > 16384) break;
    }
    return false;
  } catch (_) {
    return false;
  } finally {
    try {
      await socket?.close();
    } catch (_) {}
  }
}

Map<String, dynamic>? _firstJsonObject(String s) {
  final i = s.indexOf('{');
  if (i < 0) return null;
  var depth = 0;
  for (var j = i; j < s.length; j++) {
    final c = s[j];
    if (c == '{') {
      depth++;
    } else if (c == '}') {
      depth--;
      if (depth == 0) {
        try {
          final o = jsonDecode(s.substring(i, j + 1));
          if (o is Map<String, dynamic>) return o;
          if (o is Map) {
            return o.map((k, v) => MapEntry(k.toString(), v));
          }
        } catch (_) {
          return null;
        }
      }
    }
  }
  return null;
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
  Socket? socket;
  try {
    final f = File(filePath);
    final size = await f.length();
    final name = filePath.split(Platform.pathSeparator).last;
    final hdr = _withSecret(
      {
        'type': 'file',
        'filename': name,
        'filesize': size,
        'portal_source': 'flutter',
      },
      secret,
    );
    socket = await Socket.connect(h, port, timeout: const Duration(seconds: 30));
    socket.add(utf8.encode('${jsonEncode(hdr)}\n'));
    await socket.flush();
    // Цельный поток байт без flush на каждый chunk — меньше риска артефактов на приёме.
    await socket.addStream(f.openRead());
    await socket.flush();
    final resp = await socket.timeout(const Duration(seconds: 60)).first;
    final ok = utf8.decode(resp).startsWith('OK');
    return (ok, ok ? 'ok' : 'bad_response');
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
