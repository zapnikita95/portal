import 'dart:convert';

import 'package:shared_preferences/shared_preferences.dart';

class PeerDto {
  PeerDto({
    required this.ip,
    required this.name,
    required this.send,
    this.networkKind = 'auto',
    this.peerSecret = '',
  });
  final String ip;
  final String name;
  final bool send;

  /// auto | lan | tailscale — для фильтра вкладок Wi‑Fi / mesh на экране «Пиры».
  final String networkKind;

  /// Пароль Portal именно для этого IP (если пусто — используется общий из настроек).
  final String peerSecret;

  Map<String, dynamic> toJson() => {
        'ip': ip,
        'name': name,
        'send': send,
        'network_kind': networkKind,
        'peer_secret': peerSecret,
      };

  static PeerDto fromJson(Map<String, dynamic> m) {
    final nk = (m['network_kind'] ?? 'auto').toString().trim().toLowerCase();
    return PeerDto(
      ip: (m['ip'] ?? '').toString(),
      name: (m['name'] ?? '').toString(),
      send: m['send'] == true,
      networkKind: (nk == 'lan' || nk == 'tailscale') ? nk : 'auto',
      peerSecret: (m['peer_secret'] ?? '').toString(),
    );
  }
}

/// Именованная группа IP. На мобильном выбор «куда слать» делается на экране «Отправить» (чипы групп);
/// поле send_to_group в JSON сохраняется как false с клиента для совместимости с десктопом.
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
    this.lanScanMode = 'wifi',
    this.lanSeedHintIp = '',
    this.mdnsDisplayName = '',
  });

  final List<PeerDto> peers;
  final String secret;
  final String receiveDir;

  /// Пресет: pulse | static | rings | branding (GIF portal_main)
  final String portalAnimPreset;

  final List<PeerGroupDto> peerGroups;

  /// wifi | tailscale | all — для кнопки «Найти в LAN» на экране пиров.
  final String lanScanMode;

  /// Подсказка для LAN-скана: IP телефона в Wi‑Fi (как в настройках сети).
  final String lanSeedHintIp;

  /// Имя в LAN для mDNS (как `portal_mdns_display_name` на ПК). Пусто — подставится «Portal-iPhone» / «Portal-Android».
  final String mdnsDisplayName;

  Map<String, dynamic> toJson() => {
        'peers': peers.map((e) => e.toJson()).toList(),
        'secret': secret,
        'receive_dir': receiveDir,
        'portal_anim': portalAnimPreset,
        'peer_groups': peerGroups.map((e) => e.toJson()).toList(),
        'lan_scan_mode': lanScanMode,
        'lan_seed_hint_ip': lanSeedHintIp,
        'portal_mdns_display_name': mdnsDisplayName,
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
      lanScanMode: (m['lan_scan_mode'] ?? 'wifi').toString(),
      lanSeedHintIp: (m['lan_seed_hint_ip'] ?? '').toString(),
      mdnsDisplayName: (m['portal_mdns_display_name'] ?? '').toString(),
    );
  }

  static PortalSettings empty() => PortalSettings(
        peers: [],
        secret: '',
        receiveDir: '',
        portalAnimPreset: 'branding',
        peerGroups: [],
        lanScanMode: 'wifi',
        lanSeedHintIp: '',
        mdnsDisplayName: '',
      );

  /// Все пиры с непустым IP — кандидаты на экране «Отправить» (без фильтра peer.send / групп из «Пиры»).
  List<PeerDto> peersWithIpForSendUi() {
    return peers.where((p) => p.ip.trim().isNotEmpty).toList();
  }

  /// Совместимость со старым кодом; на мобильном эквивалентно [peersWithIpForSendUi].
  List<PeerDto> peersForSending() => peersWithIpForSendUi();
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
