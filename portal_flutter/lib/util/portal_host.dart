import 'dart:io';

/// Проверка строки перед [Socket.connect]: не пусто, не мусор вроде «1», который ОС пытается резолвить как хост.
bool isPlausiblePortalHost(String raw) {
  final s = raw.trim();
  if (s.isEmpty) return false;
  // Частая ошибка: в поле IP осталась одна цифра / октет — DNS даёт "Failed host lookup: '1'".
  if (RegExp(r'^\d{1,3}$').hasMatch(s)) return false;
  final asIp = InternetAddress.tryParse(s);
  if (asIp != null) return true;
  // mDNS
  if (s.endsWith('.local') && s.length > 7) return true;
  // Имя хоста (Tailscale DNS и т.п.): есть точка, безопасный набор символов
  if (s.contains('.') &&
      s.length >= 4 &&
      RegExp(r'^[a-zA-Z0-9.\-]+$').hasMatch(s)) {
    return true;
  }
  return false;
}
