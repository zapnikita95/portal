import 'dart:io';

import 'package:portal_flutter/portal/protocol_client.dart';

/// Собираем IPv4 с интерфейсов (LAN / Tailscale — что поднято на телефоне).
Future<List<String>> collectLocalIpv4Seeds() async {
  final out = <String>[];
  final seen = <String>{};
  try {
    final list = await NetworkInterface.list(
      includeLinkLocal: false,
      includeLoopback: false,
    );
    for (final ni in list) {
      for (final addr in ni.addresses) {
        if (addr.type != InternetAddressType.IPv4) continue;
        final s = addr.address.trim();
        if (s.isEmpty || s.startsWith('127.')) continue;
        if (seen.add(s)) out.add(s);
      }
    }
  } catch (_) {}
  return out;
}

String? subnet24Prefix(String ip) {
  final p = ip.split('.');
  if (p.length != 4) return null;
  for (final x in p) {
    final n = int.tryParse(x);
    if (n == null || n < 0 || n > 255) return null;
  }
  return '${p[0]}.${p[1]}.${p[2]}';
}

/// Параллельный скан /24 для Portal (ping), как на десктопе.
Future<List<String>> scanLanForPortalHosts({
  required String secret,
  Duration connectTimeout = const Duration(milliseconds: 900),
  int workers = 48,
}) async {
  final seeds = await collectLocalIpv4Seeds();
  final prefixes = <String>{};
  for (final s in seeds) {
    final pre = subnet24Prefix(s);
    if (pre != null) prefixes.add(pre);
  }
  if (prefixes.isEmpty) return [];

  final hosts = <String>[];
  final seen = <String>{};
  for (final pre in prefixes) {
    for (var i = 1; i < 255; i++) {
      final h = '$pre.$i';
      if (seen.add(h)) hosts.add(h);
    }
  }

  final found = <String>[];
  final n = hosts.length;
  final per = (n / workers).ceil().clamp(1, n);

  Future<void> runSlice(int start, int end) async {
    for (var j = start; j < end; j++) {
      final ip = hosts[j];
      final ok = await pingPortal(
        ip,
        secret: secret,
        connectTimeout: connectTimeout,
      );
      if (ok) found.add(ip);
    }
  }

  final futures = <Future<void>>[];
  for (var w = 0; w * per < n; w++) {
    final start = w * per;
    final end = (start + per).clamp(0, n);
    if (start >= end) break;
    futures.add(runSlice(start, end));
  }
  await Future.wait(futures);
  found.sort((a, b) {
    final pa = a.split('.').map(int.parse).toList();
    final pb = b.split('.').map(int.parse).toList();
    for (var i = 0; i < 4; i++) {
      final c = pa[i].compareTo(pb[i]);
      if (c != 0) return c;
    }
    return 0;
  });
  return found;
}
