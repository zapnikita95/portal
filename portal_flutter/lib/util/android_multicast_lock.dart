import 'dart:io';

import 'package:flutter/services.dart';

const MethodChannel _kMulticastLockChannel =
    MethodChannel('org.portal.portal/multicast_lock');

/// На Android Wi‑Fi стек часто отбрасывает multicast, пока не взят [WifiManager.MulticastLock].
/// Вызывать перед mDNS (Bonjour), затем обязательно [androidMulticastLockRelease].
Future<void> androidMulticastLockAcquire() async {
  if (!Platform.isAndroid) return;
  try {
    await _kMulticastLockChannel.invokeMethod<void>('acquire');
  } catch (_) {
    // Без блокировки mDNS на части устройств всё равно может сработать.
  }
}

Future<void> androidMulticastLockRelease() async {
  if (!Platform.isAndroid) return;
  try {
    await _kMulticastLockChannel.invokeMethod<void>('release');
  } catch (_) {}
}
