import 'package:portal_flutter/portal/lan_scan.dart';

/// Понятные сообщения об ошибках отправки (TCP / пароль / Tailscale).
String humanizePortalSendError(
  String err, {
  required String host,
}) {
  final h = host.trim();
  final ts = isTailscaleCgNatIpv4(h);
  final lower = err.toLowerCase();

  if (err == 'auth' ||
      lower.contains('portal_auth') ||
      lower.contains('auth_failed')) {
    return '$h: отклонено — неверный или пустой пароль сети. '
        'Задай тот же пароль, что в Portal на ПК (и во вкладке «Настроить» здесь).';
  }

  if (lower.contains('connection refused') ||
      err.contains('Connection refused')) {
    return '$h: соединение отклонено — на этом адресе не слушает Portal. '
        'На ПК нажми «Запустить портал» / включи приём, проверь порт 12345 и файрвол.';
  }

  if (lower.contains('network is unreachable') ||
      lower.contains('no route to host') ||
      lower.contains('host is unreachable') ||
      lower.contains('errno = 101') ||
      lower.contains('errno = 113')) {
    if (ts) {
      return '$h: нет маршрута до mesh-адреса (100.x…). '
          'Включи Tailscale на этом телефоне и проверь, что второй узел онлайн в той же сети.';
    }
    return '$h: нет маршрута до адреса. Подключись к той же Wi‑Fi / VPN, что и ПК.';
  }

  if (lower.contains('timed out') ||
      lower.contains('timeout') ||
      err == 'no_response') {
    if (ts) {
      return '$h: таймаут. Часто: Tailscale выключен, узел офлайн или блокируется сеть.';
    }
    return '$h: таймаут — узел не отвечает. Проверь IP и что Portal на ПК принимает соединения.';
  }

  if (err == 'bad_response') {
    return '$h: получен неожиданный ответ от ПК (файл мог не сохраниться).';
  }

  if (err == 'bad_host' || err == 'bad_args') {
    return 'Некорректные параметры отправки.';
  }

  // Сырой SocketException и т.п. — коротко
  if (err.length > 160) {
    return '$h: ошибка сети (${err.substring(0, 120)}…)';
  }
  return '$h: $err';
}
