import 'dart:convert';
import 'dart:io';

import 'package:portal_flutter/config.dart';

/// Минимальный клиент: ping → ожидаем JSON с type=pong (как probe_portal_peer).
Future<bool> pingPortal(
  String host, {
  String secret = '',
  int port = portalPort,
}) async {
  final h = host.trim();
  if (h.isEmpty) return false;
  Socket? socket;
  try {
    socket = await Socket.connect(
      h,
      port,
      timeout: portalConnectTimeout,
    );
    final msg = <String, dynamic>{'type': 'ping'};
    final s = secret.trim();
    if (s.isNotEmpty) msg['secret'] = s;
    socket.add(utf8.encode(jsonEncode(msg)));
    await socket.flush();

    final buf = BytesBuilder(copy: false);
    await for (final chunk in socket.timeout(const Duration(seconds: 4))) {
      buf.add(chunk);
      final text = utf8.decode(buf.toBytes(), allowMalformed: true);
      final pong = _firstJsonObject(text);
      if (pong != null && pong['type'] == 'pong') {
        return true;
      }
      if (buf.length > 65536) break;
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
          final obj = jsonDecode(s.substring(i, j + 1));
          if (obj is Map<String, dynamic>) return obj;
          if (obj is Map) {
            return obj.map((k, v) => MapEntry(k.toString(), v));
          }
        } catch (_) {
          return null;
        }
      }
    }
  }
  return null;
}
