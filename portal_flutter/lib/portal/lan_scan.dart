import 'dart:io';

import 'package:network_info_plus/network_info_plus.dart';
import 'package:portal_flutter/portal/protocol_client.dart';

/// Где искать Portal в LAN-скане.
enum LanScanScope {
  /// Локальная сеть (192.168.x, 10.x, 172.16–31.x), без подсети Tailscale 100.64–127.x.
  /// Плюс явный IP Wi‑Fi с `getWifiIP()` (главный ориентир для домашнего роутера).
  wifi,

  /// Только CGNAT-диапазон Tailscale 100.64.0.0/10.
  tailscale,

  /// Все IPv4-интерфейсы (Wi‑Fi + VPN + Tailscale сразу).
  all,
}

String lanScanScopeStorageValue(LanScanScope s) {
  switch (s) {
    case LanScanScope.wifi:
      return 'wifi';
    case LanScanScope.tailscale:
      return 'tailscale';
    case LanScanScope.all:
      return 'all';
  }
}

LanScanScope lanScanScopeFromStorage(String? raw) {
  switch ((raw ?? '').trim().toLowerCase()) {
    case 'tailscale':
      return LanScanScope.tailscale;
    case 'all':
      return LanScanScope.all;
    default:
      return LanScanScope.wifi;
  }
}

String lanScanScopeLabel(LanScanScope s) {
  switch (s) {
    case LanScanScope.wifi:
      return 'Wi‑Fi (локальная сеть)';
    case LanScanScope.tailscale:
      return 'mesh-VPN (100.x…)';
    case LanScanScope.all:
      return 'Все интерфейсы';
  }
}

/// True если IPv4 в диапазоне Tailscale 100.64.0.0/10.
bool isTailscaleCgNatIpv4(String ip) {
  final p = ip.split('.');
  if (p.length != 4) return false;
  final a = int.tryParse(p[0]);
  final b = int.tryParse(p[1]);
  if (a == null || b == null) return false;
  if (a != 100) return false;
  return b >= 64 && b <= 127;
}

/// RFC1918 частные сети (без 127, без Tailscale — тот считается отдельно).
bool isPrivateLanIpv4(String ip) {
  final p = ip.split('.');
  if (p.length != 4) return false;
  final a = int.tryParse(p[0]);
  final b = int.tryParse(p[1]);
  if (a == null || b == null) return false;
  if (a == 10) return true;
  if (a == 172 && b >= 16 && b <= 31) return true;
  if (a == 192 && b == 168) return true;
  return false;
}

bool _validIpv4(String s) {
  return InternetAddress.tryParse(s.trim())?.type == InternetAddressType.IPv4;
}

/// Сырые данные для выбора подсетей скана.
class LanSeedBundle {
  LanSeedBundle({this.wifiIp, required this.allIpv4});

  /// IP в Wi‑Fi сети (если ОС отдала).
  final String? wifiIp;

  /// Все увиденные IPv4 (интерфейсы + при необходимости wifi).
  final List<String> allIpv4;
}

Future<LanSeedBundle> collectLanSeedBundle() async {
  final all = <String>[];
  final seen = <String>{};
  String? wifiIp;

  void addIp(String? s) {
    final t = (s ?? '').trim();
    if (t.isEmpty || t.startsWith('127.')) return;
    if (!_validIpv4(t)) return;
    if (seen.add(t)) all.add(t);
  }

  if (Platform.isAndroid || Platform.isIOS) {
    try {
      final w = await NetworkInfo().getWifiIP();
      final t = w?.trim();
      if (t != null && t.isNotEmpty && _validIpv4(t)) {
        wifiIp = t;
        addIp(t);
      }
    } catch (_) {}
  }

  try {
    final list = await NetworkInterface.list(
      includeLinkLocal: false,
      includeLoopback: false,
    );
    for (final ni in list) {
      for (final addr in ni.addresses) {
        if (addr.type != InternetAddressType.IPv4) continue;
        addIp(addr.address);
      }
    }
  } catch (_) {}

  return LanSeedBundle(wifiIp: wifiIp, allIpv4: all);
}

/// Сиды (уникальные IPv4) для выбранного режима скана.
///
/// [extraHints] — ручные IP из поля «пиры»: если ОС не отдала Wi‑Fi IP
/// (Android без ACCESS_WIFI_STATE), хотя бы попадём в нужный /24 по IP пира.
List<String> seedsForScope(
  LanSeedBundle bundle,
  LanScanScope scope, {
  List<String> extraHints = const [],

  /// Явный IP «моей Wi‑Fi сети» из настроек телефона — первый кандидат для /24.
  List<String> manualWifiHints = const [],
}) {
  final manual = manualWifiHints
      .map((s) => s.trim())
      .where(_validIpv4)
      .toList();
  final hints = <String>[...manual, ...extraHints]
      .map((s) => s.trim())
      .where(_validIpv4)
      .toList();

  switch (scope) {
    case LanScanScope.wifi:
      final out = <String>{};
      if (bundle.wifiIp != null && _validIpv4(bundle.wifiIp!)) {
        out.add(bundle.wifiIp!.trim());
      }
      for (final ip in bundle.allIpv4) {
        if (isPrivateLanIpv4(ip) && !isTailscaleCgNatIpv4(ip)) {
          out.add(ip);
        }
      }
      // Fallback: если ОС ничего не дала, но пользователь вручную ввёл LAN-IP пира.
      if (out.isEmpty) {
        for (final ip in hints) {
          if (isPrivateLanIpv4(ip) && !isTailscaleCgNatIpv4(ip)) {
            out.add(ip);
          }
        }
      }
      return out.toList();
    case LanScanScope.tailscale:
      // Всегда объединяем IP интерфейса и подсказки из пиров — иначе при своём
      // 100.x сканируется только один /24, а остальные mesh-узлы в других /24 не видны.
      final out = <String>{};
      for (final ip in bundle.allIpv4) {
        if (isTailscaleCgNatIpv4(ip)) out.add(ip);
      }
      for (final ip in hints) {
        if (isTailscaleCgNatIpv4(ip)) out.add(ip);
      }
      return out.toList();
    case LanScanScope.all:
      final out = <String>{...bundle.allIpv4, ...hints};
      return out.toList();
  }
}

/// Совместимость: все интерфейсы как раньше.
Future<List<String>> collectLocalIpv4Seeds() async {
  final b = await collectLanSeedBundle();
  return seedsForScope(b, LanScanScope.all);
}

/// Сиды для LAN-скана с учётом режима вкладки.
///
/// Для **mesh** дополнительно подмешиваются сиды **Wi‑Fi / домашней LAN** (и подсказки),
/// чтобы в одном проходе находить и 100.x, и 192.168.x — иначе iPhone без VPN в mesh-режиме
/// вообще не попадал в перебор адресов.
List<String> effectiveLanScanSeeds(
  LanSeedBundle bundle,
  LanScanScope scope, {
  List<String> extraHints = const [],
  List<String> manualWifiHints = const [],
}) {
  final primary = seedsForScope(
    bundle,
    scope,
    extraHints: extraHints,
    manualWifiHints: manualWifiHints,
  );
  if (scope != LanScanScope.tailscale) return primary;
  final lanSide = seedsForScope(
    bundle,
    LanScanScope.wifi,
    extraHints: extraHints,
    manualWifiHints: manualWifiHints,
  );
  return {...primary, ...lanSide}.toList();
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

/// Параллельный скан по IPv4-сегментам: для каждого известного префикса перебираются
/// хосты `.1`–`.254` (типичный размер сегмента домашнего роутера).
///
/// [peerHints] — IP из настроек пиров, используются как fallback-сиды если ОС
/// не отдала Wi‑Fi IP (старый Android APK без ACCESS_WIFI_STATE).
Future<List<String>> scanLanForPortalHosts({
  required List<String> candidateSecrets,
  LanScanScope scope = LanScanScope.wifi,
  List<String> peerHints = const [],

  /// IP из настроек Wi‑Fi телефона (или прошлый сохранённый) — усиливает скан домашней /24.
  String manualLanSeedIp = '',
  Duration connectTimeout = const Duration(milliseconds: 1400),
  int workers = 48,
}) async {
  final bundle = await collectLanSeedBundle();
  final manualWifi = <String>[];
  final one = manualLanSeedIp.trim();
  if (one.isNotEmpty) manualWifi.add(one);
  final seeds = effectiveLanScanSeeds(
    bundle,
    scope,
    extraHints: peerHints,
    manualWifiHints: manualWifi,
  );
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

  /// Пустой список = пробовать ping без secret (как на ПК без пароля).
  final secrets =
      candidateSecrets.isNotEmpty ? candidateSecrets : <String>[''];

  Future<void> runSlice(int start, int end) async {
    for (var j = start; j < end; j++) {
      final ip = hosts[j];
      final ok = await pingPortalTrySecrets(
        ip,
        secrets: secrets,
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
