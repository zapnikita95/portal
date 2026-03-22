import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

class PeerDto {
  PeerDto({required this.ip, required this.name, required this.send});
  final String ip;
  final String name;
  final bool send;

  Map<String, dynamic> toJson() => {
        'ip': ip,
        'name': name,
        'send': send,
      };

  static PeerDto fromJson(Map<String, dynamic> m) => PeerDto(
        ip: (m['ip'] ?? '').toString(),
        name: (m['name'] ?? '').toString(),
        send: m['send'] == true,
      );
}

class PortalSettings {
  PortalSettings({
    required this.peers,
    required this.secret,
    required this.receiveDir,
  });

  final List<PeerDto> peers;
  final String secret;
  final String receiveDir;

  Map<String, dynamic> toJson() => {
        'peers': peers.map((e) => e.toJson()).toList(),
        'secret': secret,
        'receive_dir': receiveDir,
      };

  static PortalSettings fromJson(Map<String, dynamic> m) {
    final raw = m['peers'];
    final list = <PeerDto>[];
    if (raw is List) {
      for (final x in raw) {
        if (x is Map) {
          list.add(PeerDto.fromJson(Map<String, dynamic>.from(x)));
        }
      }
    }
    return PortalSettings(
      peers: list,
      secret: (m['secret'] ?? '').toString(),
      receiveDir: (m['receive_dir'] ?? '').toString(),
    );
  }

  static PortalSettings empty() =>
      PortalSettings(peers: [], secret: '', receiveDir: '');
}

class SettingsRepository {
  static const _key = 'portal_settings_json_v1';

  static Future<PortalSettings> load() async {
    final p = await SharedPreferences.getInstance();
    final s = p.getString(_key);
    if (s == null || s.isEmpty) return PortalSettings.empty();
    try {
      return PortalSettings.fromJson(
        jsonDecode(s) as Map<String, dynamic>,
      );
    } catch (_) {
      return PortalSettings.empty();
    }
  }

  static Future<void> save(PortalSettings st) async {
    final p = await SharedPreferences.getInstance();
    await p.setString(_key, jsonEncode(st.toJson()));
  }

  /// Для изолята фонового сервиса (тот же ключ).
  static Future<PortalSettings> loadFromPrefs(SharedPreferences p) async {
    final s = p.getString(_key);
    if (s == null || s.isEmpty) return PortalSettings.empty();
    try {
      return PortalSettings.fromJson(
        jsonDecode(s) as Map<String, dynamic>,
      );
    } catch (_) {
      return PortalSettings.empty();
    }
  }
}
