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

/// Именованная группа IP: галочка «отправка на группу» включает все member_ips из сохранённых пиров.
class PeerGroupDto {
  PeerGroupDto({
    required this.id,
    required this.name,
    required this.memberIps,
    this.sendToGroup = false,
  });

  final String id;
  final String name;
  final List<String> memberIps;
  final bool sendToGroup;

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
        'member_ips': memberIps,
        'send_to_group': sendToGroup,
      };

  static PeerGroupDto fromJson(Map<String, dynamic> m) {
    final raw = m['member_ips'];
    final ips = <String>[];
    if (raw is List) {
      for (final x in raw) {
        final s = x.toString().trim();
        if (s.isNotEmpty) ips.add(s);
      }
    }
    return PeerGroupDto(
      id: (m['id'] ?? '').toString(),
      name: (m['name'] ?? '').toString(),
      memberIps: ips,
      sendToGroup: m['send_to_group'] == true,
    );
  }
}

class PortalSettings {
  PortalSettings({
    required this.peers,
    required this.secret,
    required this.receiveDir,
    this.portalAnimPreset = 'pulse',
    this.peerGroups = const [],
  });

  final List<PeerDto> peers;
  final String secret;
  final String receiveDir;

  /// Пресет: pulse | static | rings | branding (GIF portal_main)
  final String portalAnimPreset;

  final List<PeerGroupDto> peerGroups;

  Map<String, dynamic> toJson() => {
        'peers': peers.map((e) => e.toJson()).toList(),
        'secret': secret,
        'receive_dir': receiveDir,
        'portal_anim': portalAnimPreset,
        'peer_groups': peerGroups.map((e) => e.toJson()).toList(),
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
    final groups = <PeerGroupDto>[];
    final graw = m['peer_groups'];
    if (graw is List) {
      for (final x in graw) {
        if (x is Map) {
          groups.add(PeerGroupDto.fromJson(Map<String, dynamic>.from(x)));
        }
      }
    }
    return PortalSettings(
      peers: list,
      secret: (m['secret'] ?? '').toString(),
      receiveDir: (m['receive_dir'] ?? '').toString(),
      portalAnimPreset: (m['portal_anim'] ?? 'pulse').toString(),
      peerGroups: groups,
    );
  }

  static PortalSettings empty() => PortalSettings(
        peers: [],
        secret: '',
        receiveDir: '',
        portalAnimPreset: 'branding',
        peerGroups: [],
      );

  /// Кому слать: если у хотя бы одной группы sendToGroup — только IP из отмеченных групп (пересечение с peers).
  /// Иначе — классика: peer.send.
  List<PeerDto> peersForSending() {
    final fromGroups = <String>{};
    var anyGroupOn = false;
    for (final g in peerGroups) {
      if (g.sendToGroup) {
        anyGroupOn = true;
        for (final ip in g.memberIps) {
          final t = ip.trim();
          if (t.isNotEmpty) fromGroups.add(t);
        }
      }
    }
    if (anyGroupOn) {
      return peers.where((p) => fromGroups.contains(p.ip.trim())).toList();
    }
    return peers.where((p) => p.send && p.ip.trim().isNotEmpty).toList();
  }
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
