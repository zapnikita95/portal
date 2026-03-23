import 'dart:io';

import 'package:multicast_dns/multicast_dns.dart';
import 'package:portal_flutter/util/android_multicast_lock.dart';

/// Совпадает с [portal_mdns.SERVICE_TYPE] на десктопе (Python zeroconf).
const String kPortalMdnsServicePointer = '_portal._tcp.local';

/// Устройство Portal, найденное по mDNS (как «Найти локально» на ПК).
class PortalMdnsPeer {
  PortalMdnsPeer({
    required this.ipv4,
    required this.displayName,
    required this.port,
  });

  final String ipv4;
  final String displayName;
  final int port;
}

String _normalizeMdnsHost(String target) {
  var t = target.trim();
  if (t.endsWith('.')) {
    t = t.substring(0, t.length - 1);
  }
  return t;
}

String _labelFromInstanceFqdn(String fqdn) {
  var s = fqdn.trim();
  if (s.endsWith('.')) s = s.substring(0, s.length - 1);
  const low = '._portal._tcp.local';
  final sl = s.toLowerCase();
  if (sl.endsWith(low)) {
    s = s.substring(0, s.length - low.length);
  }
  return s.isEmpty ? fqdn : s;
}

/// TXT от zeroconf: строки `display=…`, `name=…` или одна строка без `=`.
String? _parseDisplayFromTxt(String raw) {
  if (raw.trim().isEmpty) return null;
  for (final line in raw.split(RegExp(r'\r?\n'))) {
    final t = line.trim();
    if (t.isEmpty) continue;
    final eq = t.indexOf('=');
    if (eq > 0) {
      final k = t.substring(0, eq).trim().toLowerCase();
      final v = t.substring(eq + 1).trim();
      if ((k == 'display' || k == 'name') && v.isNotEmpty) return v;
    }
  }
  final first = raw.split(RegExp(r'\r?\n')).first.trim();
  if (first.isNotEmpty && !first.contains('=')) return first;
  return null;
}

Future<PortalMdnsPeer?> _resolveOneInstance(
  MDnsClient client,
  String instanceFqdn,
) async {
  SrvResourceRecord? srv;
  await for (final r in client.lookup<SrvResourceRecord>(
    ResourceRecordQuery.service(instanceFqdn),
    timeout: const Duration(milliseconds: 1800),
  )) {
    srv = r;
    break;
  }
  if (srv == null) return null;

  var display = '';
  await for (final r in client.lookup<TxtResourceRecord>(
    ResourceRecordQuery.text(instanceFqdn),
    timeout: const Duration(milliseconds: 1200),
  )) {
    final p = _parseDisplayFromTxt(r.text);
    if (p != null && p.isNotEmpty) {
      display = p;
      break;
    }
  }
  if (display.isEmpty) {
    display = _labelFromInstanceFqdn(instanceFqdn);
  }

  final target = _normalizeMdnsHost(srv.target);
  String? ipv4;

  await for (final r in client.lookup<IPAddressResourceRecord>(
    ResourceRecordQuery.addressIPv4('$target.'),
    timeout: const Duration(milliseconds: 1500),
  )) {
    if (r.address.type == InternetAddressType.IPv4) {
      ipv4 = r.address.address;
      break;
    }
  }

  if (ipv4 == null) {
    await for (final r in client.lookup<IPAddressResourceRecord>(
      ResourceRecordQuery.addressIPv4(target),
      timeout: const Duration(milliseconds: 1200),
    )) {
      if (r.address.type == InternetAddressType.IPv4) {
        ipv4 = r.address.address;
        break;
      }
    }
  }

  if (ipv4 == null) {
    try {
      final addrs = await InternetAddress.lookup(target);
      for (final a in addrs) {
        if (a.type == InternetAddressType.IPv4) {
          ipv4 = a.address;
          break;
        }
      }
    } catch (_) {}
  }

  if (ipv4 == null || ipv4.startsWith('127.')) return null;
  return PortalMdnsPeer(
    ipv4: ipv4,
    displayName: display,
    port: srv.port,
  );
}

/// Поиск соседей с Portal в LAN по mDNS (тот же `_portal._tcp`, что на десктопе).
///
/// Не находит узлы только в mesh без mDNS (например чистый Tailscale) — для них остаётся TCP-скан.
Future<List<PortalMdnsPeer>> discoverPortalMdnsPeers({
  Duration ptrListen = const Duration(milliseconds: 2800),
}) async {
  await androidMulticastLockAcquire();
  final MDnsClient client = MDnsClient();
  try {
    await client.start();
  } catch (_) {
    try {
      client.stop();
    } catch (_) {}
    await androidMulticastLockRelease();
    return [];
  }

  try {
    final ptrNames = <String>{};
    await for (final PtrResourceRecord ptr in client.lookup<PtrResourceRecord>(
      ResourceRecordQuery.serverPointer(kPortalMdnsServicePointer),
      timeout: ptrListen,
    )) {
      final n = ptr.domainName.trim();
      if (n.isNotEmpty) ptrNames.add(n);
    }

    if (ptrNames.isEmpty) return [];

    final resolved = await Future.wait(
      ptrNames.map((fqdn) => _resolveOneInstance(client, fqdn)),
    );

    final byIp = <String, PortalMdnsPeer>{};
    for (final p in resolved) {
      if (p == null) continue;
      byIp[p.ipv4] = p;
    }
    final out = byIp.values.toList()
      ..sort((a, b) {
        final c =
            a.displayName.toLowerCase().compareTo(b.displayName.toLowerCase());
        if (c != 0) return c;
        return _compareIpv4(a.ipv4, b.ipv4);
      });
    return out;
  } catch (_) {
    return [];
  } finally {
    try {
      client.stop();
    } catch (_) {}
    await androidMulticastLockRelease();
  }
}

int _compareIpv4(String a, String b) {
  final pa = a.split('.');
  final pb = b.split('.');
  if (pa.length != 4 || pb.length != 4) return a.compareTo(b);
  for (var i = 0; i < 4; i++) {
    final na = int.tryParse(pa[i]) ?? 0;
    final nb = int.tryParse(pb[i]) ?? 0;
    final c = na.compareTo(nb);
    if (c != 0) return c;
  }
  return 0;
}
