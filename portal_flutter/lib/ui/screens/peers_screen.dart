import 'package:flutter/material.dart';
import 'package:portal_flutter/data/settings_repository.dart';
import 'package:portal_flutter/portal/lan_scan.dart';
import 'package:portal_flutter/portal/portal_mdns_discover.dart';
import 'package:portal_flutter/portal/portal_secrets.dart';
import 'package:portal_flutter/portal/protocol_client.dart';

class PeersScreen extends StatefulWidget {
  const PeersScreen({super.key});

  @override
  State<PeersScreen> createState() => _PeersScreenState();
}

class _PeersScreenState extends State<PeersScreen> {
  final _rows = <_PeerRow>[];
  final _groups = <_GroupEdit>[];
  final _lanSeed = TextEditingController();
  final _draftIp = TextEditingController();
  final _draftName = TextEditingController();
  final _draftSecret = TextEditingController();
  String _draftKind = 'lan';
  bool _loading = true;
  LanScanScope _lanScope = LanScanScope.wifi;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _disposeRows() {
    for (final r in _rows) {
      r.dispose();
    }
    _rows.clear();
  }

  void _disposeGroups() {
    for (final g in _groups) {
      g.dispose();
    }
    _groups.clear();
  }

  String _defaultKindForTab() {
    switch (_lanScope) {
      case LanScanScope.wifi:
        return 'lan';
      case LanScanScope.tailscale:
        return 'tailscale';
      case LanScanScope.all:
        return 'auto';
    }
  }

  void _applyFromSettings(PortalSettings st) {
    _disposeRows();
    _disposeGroups();

    for (final p in st.peers) {
      _rows.add(_PeerRow(
        ip: TextEditingController(text: p.ip),
        name: TextEditingController(text: p.name),
        peerSecret: TextEditingController(text: p.peerSecret),
        send: true,
        networkKind: p.networkKind,
      ));
    }

    _lanScope = lanScanScopeFromStorage(st.lanScanMode);
    _lanSeed.text = st.lanSeedHintIp;
    _draftKind = _defaultKindForTab();

    for (final g in st.peerGroups) {
      _groups.add(_GroupEdit(
        id: g.id.isNotEmpty ? g.id : _newId(),
        name: TextEditingController(text: g.name),
        memberIps: List<String>.from(g.memberIps),
        sendToGroup: false,
      ));
    }
  }

  Future<void> _load() async {
    final st = await SettingsRepository.load();
    if (!mounted) return;
    setState(() {
      _applyFromSettings(st);
      _loading = false;
    });
  }

  String _newId() =>
      'g_${DateTime.now().microsecondsSinceEpoch}_${UniqueKey().hashCode}';

  bool _peerRowMatchesTab(_PeerRow r) {
    final ip = r.ip.text.trim();
    if (ip.isEmpty) return true;
    final kind = r.networkKind;
    switch (_lanScope) {
      case LanScanScope.wifi:
        if (kind == 'lan') return true;
        if (kind == 'tailscale') return false;
        return isPrivateLanIpv4(ip) && !isTailscaleCgNatIpv4(ip);
      case LanScanScope.tailscale:
        if (kind == 'tailscale') return true;
        if (kind == 'lan') return false;
        return isTailscaleCgNatIpv4(ip);
      case LanScanScope.all:
        return true;
    }
  }

  Iterable<int> _visibleRowIndices() sync* {
    for (var i = 0; i < _rows.length; i++) {
      if (_peerRowMatchesTab(_rows[i])) yield i;
    }
  }

  PortalSettings _buildPortalSettingsFromUi(PortalSettings base) {
    final peers = <PeerDto>[];
    for (final r in _rows) {
      final ip = r.ip.text.trim();
      if (ip.isEmpty) continue;
      final nm = r.name.text.trim();
      peers.add(PeerDto(
        ip: ip,
        name: nm.isEmpty ? ip : nm,
        send: true,
        networkKind: r.networkKind,
        peerSecret: r.peerSecret.text.trim(),
      ));
    }
    final groups = <PeerGroupDto>[];
    for (final g in _groups) {
      groups.add(PeerGroupDto(
        id: g.id,
        name: g.name.text.trim().isEmpty ? 'Группа' : g.name.text.trim(),
        memberIps: List<String>.from(g.memberIps),
        sendToGroup: false,
      ));
    }
    return PortalSettings(
      peers: peers,
      secret: base.secret,
      receiveDir: base.receiveDir,
      portalAnimPreset: base.portalAnimPreset,
      peerGroups: groups,
      lanScanMode: lanScanScopeStorageValue(_lanScope),
      lanSeedHintIp: _lanSeed.text.trim(),
      mdnsDisplayName: base.mdnsDisplayName,
    );
  }

  Future<void> _persist({bool showSnack = true}) async {
    final st0 = await SettingsRepository.load();
    final next = _buildPortalSettingsFromUi(st0);
    await SettingsRepository.save(next);
    if (!mounted) return;
    setState(() {
      _applyFromSettings(next);
    });
    if (!mounted) return;
    if (showSnack) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Сохранено')),
      );
    }
  }

  Future<void> _saveNow() async => _persist(showSnack: true);

  Future<void> _ping(int index) async {
    if (index < 0 || index >= _rows.length) return;
    final r = _rows[index];
    final ip = r.ip.text.trim();
    if (ip.isEmpty) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Введи IP')),
      );
      return;
    }
    final st = await SettingsRepository.load();
    final rowSecret = r.peerSecret.text.trim();
    final secrets = <String>[
      if (rowSecret.isNotEmpty) rowSecret,
      ...PortalSecrets.orderedCandidateSecrets(st)
          .where((s) => s != rowSecret),
    ];
    final ok = await pingPortalTrySecrets(ip, secrets: secrets);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          ok
              ? 'Pong: $ip'
              : 'Нет ответа: $ip. ПК: «Запустить портал», :12345; пароль — общий в «Настроить» '
                  'или свой в строке пира (как в config.json); файрвол / mesh-VPN.',
        ),
        duration: const Duration(seconds: 6),
      ),
    );
  }

  Future<void> _pingDraft() async {
    final ip = _draftIp.text.trim();
    if (ip.isEmpty) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Введи IP')),
      );
      return;
    }
    final st = await SettingsRepository.load();
    final rowSecret = _draftSecret.text.trim();
    final secrets = <String>[
      if (rowSecret.isNotEmpty) rowSecret,
      ...PortalSecrets.orderedCandidateSecrets(st)
          .where((s) => s != rowSecret),
    ];
    final ok = await pingPortalTrySecrets(ip, secrets: secrets);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          ok
              ? 'Pong: $ip'
              : 'Нет ответа: $ip. ПК: «Запустить портал», :12345; пароль — общий или в поле ниже.',
        ),
        duration: const Duration(seconds: 5),
      ),
    );
  }

  Future<void> _commitDraft() async {
    final ip = _draftIp.text.trim();
    if (ip.isEmpty) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Введи IP')),
      );
      return;
    }
    if (_rows.any((r) => r.ip.text.trim() == ip)) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Уже есть: $ip')),
      );
      return;
    }
    setState(() {
      _rows.insert(
        0,
        _PeerRow(
          ip: TextEditingController(text: ip),
          name: TextEditingController(text: _draftName.text.trim()),
          peerSecret: TextEditingController(text: _draftSecret.text.trim()),
          send: true,
          networkKind: _draftKind == 'lan' || _draftKind == 'tailscale'
              ? _draftKind
              : _defaultKindForTab(),
        ),
      );
      _draftIp.clear();
      _draftName.clear();
      _draftSecret.clear();
      _draftKind = _defaultKindForTab();
    });
    await _persist(showSnack: false);
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Добавлено: $ip')),
      );
    }
  }

  Future<void> _lanScan() async {
    final st = await SettingsRepository.load();
    if (!mounted) return;

    final hintCtrl = TextEditingController(
      text: _lanSeed.text.trim().isNotEmpty
          ? _lanSeed.text.trim()
          : st.lanSeedHintIp.trim(),
    );

    final go = await showDialog<bool>(
      context: context,
      builder: (ctx) {
        return AlertDialog(
          title: const Text('Поиск в локальной сети'),
          content: SingleChildScrollView(
            keyboardDismissBehavior:
                ScrollViewKeyboardDismissBehavior.onDrag,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Сначала mDNS (как на ПК «Найти локально»): имена и IP за пару секунд в одной Wi‑Fi. '
                  'Параллельно — перебор адресов .1–.254 по сегментам (mesh + домашняя LAN при необходимости).\n\n'
                  'Подсказка IPv4 (необязательно): как в «Настройки → Сеть» или IP пира — усиливает TCP-скан. '
                  'Пусто — берём адреса с интерфейсов ОС и из списка пиров.',
                  style: Theme.of(ctx).textTheme.bodySmall,
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: hintCtrl,
                  decoration: const InputDecoration(
                    labelText: 'IP в твоей Wi‑Fi сети (необязательно)',
                    hintText: '192.168.0.105',
                    border: OutlineInputBorder(),
                  ),
                  keyboardType: TextInputType.url,
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx, false),
              child: const Text('Отмена'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(ctx, true),
              child: const Text('Сканировать'),
            ),
          ],
        );
      },
    );

    if (go != true) {
      hintCtrl.dispose();
      return;
    }

    _lanSeed.text = hintCtrl.text.trim();
    hintCtrl.dispose();

    final peerHints = _rows
        .map((r) => r.ip.text.trim())
        .where((s) => s.isNotEmpty)
        .toList();

    final manual = _lanSeed.text.trim();
    final bundle = await collectLanSeedBundle();
    final seeds = effectiveLanScanSeeds(
      bundle,
      _lanScope,
      extraHints: peerHints,
      manualWifiHints: manual.isNotEmpty ? [manual] : const [],
    );
    if (seeds.isEmpty) {
      final w = bundle.wifiIp ?? '—';
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'Нет IPv4 для режима «${lanScanScopeLabel(_lanScope)}». '
            'Wi‑Fi IP (система): $w. '
            'Заполни поле «IP в твоей Wi‑Fi сети» в диалоге скана или добавь LAN‑пира вручную.',
          ),
          duration: const Duration(seconds: 9),
        ),
      );
      return;
    }
    if (!mounted) return;
    showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        content: Row(
          children: [
            const CircularProgressIndicator(),
            const SizedBox(width: 20),
            Expanded(
              child: Text(
                'Ищем Portal: mDNS + скан (${lanScanScopeLabel(_lanScope)})…',
              ),
            ),
          ],
        ),
      ),
    );
    final results = await Future.wait([
      discoverPortalMdnsPeers()
          .catchError((Object _, StackTrace __) => <PortalMdnsPeer>[]),
      scanLanForPortalHosts(
        candidateSecrets: PortalSecrets.orderedCandidateSecrets(st),
        scope: _lanScope,
        peerHints: peerHints,
        manualLanSeedIp: manual,
      ).catchError((Object _, StackTrace __) => <String>[]),
    ]);
    if (!mounted) return;
    Navigator.of(context).pop();

    final mdnsPeers = results[0] as List<PortalMdnsPeer>;
    final scanIps = results[1] as List<String>;
    final mdnsNames = <String, String>{};
    for (final p in mdnsPeers) {
      mdnsNames[p.ipv4] = p.displayName.trim().isEmpty ? p.ipv4 : p.displayName.trim();
    }
    final foundIps = <String>{...scanIps, ...mdnsNames.keys};
    final found = foundIps.toList()
      ..sort((a, b) {
        final ta = mdnsNames.containsKey(a) ? '${mdnsNames[a]} ($a)' : a;
        final tb = mdnsNames.containsKey(b) ? '${mdnsNames[b]} ($b)' : b;
        return ta.toLowerCase().compareTo(tb.toLowerCase());
      });

    if (found.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Никого не нашли. mDNS — только в одной локальной сети с ПК (zeroconf); '
            'TCP-скан: :12345 и пароль как в config.json. '
            'Чистый mesh без LAN часто не виден по mDNS; iPhone без открытого Portal может не ответить на ping.',
          ),
          duration: Duration(seconds: 7),
        ),
      );
      return;
    }
    final pick = await showDialog<Set<String>>(
      context: context,
      builder: (ctx) {
        final sel = <String>{...found};
        return StatefulBuilder(
          builder: (ctx, setLocal) {
            return AlertDialog(
              title: const Text('Найдены Portal'),
              content: SizedBox(
                width: double.maxFinite,
                height: 320,
                child: ListView(
                  keyboardDismissBehavior:
                      ScrollViewKeyboardDismissBehavior.onDrag,
                  children: found.map((ip) {
                    final fromMdns = mdnsNames.containsKey(ip);
                    final title = fromMdns ? '${mdnsNames[ip]} ($ip)' : ip;
                    return CheckboxListTile(
                      title: Text(title),
                      subtitle: fromMdns
                          ? const Text('mDNS', style: TextStyle(fontSize: 12))
                          : const Text('ping :12345', style: TextStyle(fontSize: 12)),
                      value: sel.contains(ip),
                      onChanged: (v) {
                        setLocal(() {
                          if (v == true) {
                            sel.add(ip);
                          } else {
                            sel.remove(ip);
                          }
                        });
                      },
                    );
                  }).toList(),
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(ctx),
                  child: const Text('Отмена'),
                ),
                FilledButton(
                  onPressed: () => Navigator.pop(ctx, sel),
                  child: const Text('Добавить'),
                ),
              ],
            );
          },
        );
      },
    );
    if (pick == null || pick.isEmpty || !mounted) return;

    final secretForNew = await showDialog<String?>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) {
        final c = TextEditingController(text: st.secret);
        return AlertDialog(
          title: const Text('Пароль для новых Portal'),
          content: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Пароль с этого ПК/телефона (как в config.json). Сохранится у каждого выбранного IP — '
                  'так можно дать доступ только к одной машине, не раскрывая пароли остальных.\n\n'
                  'Оставь поле пустым и нажми «Только общий» — тогда сработает пароль из «Настроить» '
                  '(удобно, но шаринг общего пароля открывает все пиры без своего поля).',
                  style: Theme.of(ctx).textTheme.bodySmall,
                ),
                const SizedBox(height: 12),
                TextField(
                  controller: c,
                  obscureText: true,
                  decoration: const InputDecoration(
                    labelText: 'Пароль Portal для этих адресов',
                    border: OutlineInputBorder(),
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(ctx),
              child: const Text('Отмена'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(ctx, ''),
              child: const Text('Только общий'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(ctx, c.text.trim()),
              child: const Text('Добавить'),
            ),
          ],
        );
      },
    );
    // null = отмена; '' = только общий пароль из «Настроить».
    if (secretForNew == null || !mounted) return;

    final have = _rows.map((r) => r.ip.text.trim()).toSet();
    for (final ip in pick) {
      if (have.contains(ip)) continue;
      final kind = isTailscaleCgNatIpv4(ip) ? 'tailscale' : 'lan';
      final row = _PeerRow(
        ip: TextEditingController(text: ip),
        name: TextEditingController(),
        peerSecret: TextEditingController(text: secretForNew),
        send: true,
        networkKind: kind,
      );
      _rows.insert(0, row);
      have.add(ip);
    }
    setState(() {});
    await _persist(showSnack: false);
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Добавлено: ${pick.length}')),
      );
    }
  }

  @override
  void dispose() {
    _disposeRows();
    _disposeGroups();
    _lanSeed.dispose();
    _draftIp.dispose();
    _draftName.dispose();
    _draftSecret.dispose();
    super.dispose();
  }

  static const _kindLabels = <String, String>{
    'auto': 'Авто (по IP)',
    'lan': 'Домашняя сеть',
    'tailscale': 'mesh-VPN',
  };

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    final visible = _visibleRowIndices().toList();
    return SafeArea(
      child: Column(
        children: [
          Padding(
            padding: const EdgeInsets.all(16),
            child: Row(
              children: [
                Text('Пиры', style: Theme.of(context).textTheme.titleLarge),
                const Spacer(),
                IconButton(
                  tooltip: 'Найти в LAN',
                  onPressed: _lanScan,
                  icon: const Icon(Icons.wifi_find),
                ),
                FilledButton(onPressed: _saveNow, child: const Text('Сохранить')),
              ],
            ),
          ),
          Expanded(
            child: ListView(
              keyboardDismissBehavior:
                  ScrollViewKeyboardDismissBehavior.onDrag,
              padding: const EdgeInsets.symmetric(horizontal: 12),
              children: [
                Text(
                  'Фильтр Wi‑Fi / mesh / Все. Куда слать — только вкладка «Отправить» (группы и галки). '
                  '«Сохранить» — записать список и группы.',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 8),
                SegmentedButton<LanScanScope>(
                  segments: const <ButtonSegment<LanScanScope>>[
                    ButtonSegment<LanScanScope>(
                      value: LanScanScope.wifi,
                      label: Text('Wi‑Fi'),
                      icon: Icon(Icons.wifi, size: 18),
                    ),
                    ButtonSegment<LanScanScope>(
                      value: LanScanScope.tailscale,
                      label: Text('mesh'),
                      icon: Icon(Icons.hub_outlined, size: 18),
                    ),
                    ButtonSegment<LanScanScope>(
                      value: LanScanScope.all,
                      label: Text('Все'),
                      icon: Icon(Icons.device_hub_outlined, size: 18),
                    ),
                  ],
                  selected: <LanScanScope>{_lanScope},
                  onSelectionChanged: (Set<LanScanScope> next) {
                    setState(() {
                      _lanScope = next.first;
                      _draftKind = _defaultKindForTab();
                    });
                  },
                ),
                const SizedBox(height: 10),
                Card(
                  margin: EdgeInsets.zero,
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(10, 10, 10, 10),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text(
                          'Новый адрес',
                          style: Theme.of(context).textTheme.titleSmall,
                        ),
                        const SizedBox(height: 8),
                        Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Expanded(
                              flex: 3,
                              child: TextField(
                                controller: _draftIp,
                                decoration: const InputDecoration(
                                  labelText: 'IP',
                                  isDense: true,
                                  border: OutlineInputBorder(),
                                ),
                                keyboardType: TextInputType.url,
                              ),
                            ),
                            const SizedBox(width: 8),
                            Expanded(
                              flex: 2,
                              child: TextField(
                                controller: _draftName,
                                decoration: const InputDecoration(
                                  labelText: 'Подпись',
                                  isDense: true,
                                  border: OutlineInputBorder(),
                                ),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 8),
                        TextField(
                          controller: _draftSecret,
                          obscureText: true,
                          decoration: const InputDecoration(
                            labelText: 'Пароль устройства (пусто = общий)',
                            isDense: true,
                            border: OutlineInputBorder(),
                          ),
                        ),
                        const SizedBox(height: 8),
                        Row(
                          children: [
                            Expanded(
                              child: DropdownButtonFormField<String>(
                                value: _draftKind == 'lan' ||
                                        _draftKind == 'tailscale' ||
                                        _draftKind == 'auto'
                                    ? _draftKind
                                    : 'auto',
                                isDense: true,
                                decoration: const InputDecoration(
                                  labelText: 'Сеть',
                                  isDense: true,
                                  border: OutlineInputBorder(),
                                  contentPadding: EdgeInsets.symmetric(
                                    horizontal: 8,
                                    vertical: 8,
                                  ),
                                ),
                                items: _kindLabels.entries
                                    .map(
                                      (e) => DropdownMenuItem(
                                        value: e.key,
                                        child: Text(
                                          e.value,
                                          overflow: TextOverflow.ellipsis,
                                        ),
                                      ),
                                    )
                                    .toList(),
                                onChanged: (v) {
                                  if (v == null) return;
                                  setState(() => _draftKind = v);
                                },
                              ),
                            ),
                            IconButton(
                              tooltip: 'Ping',
                              onPressed: _pingDraft,
                              icon: const Icon(Icons.radar, size: 22),
                            ),
                            FilledButton.tonal(
                              onPressed: _commitDraft,
                              child: const Text('Добавить'),
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                if (visible.isEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 20),
                    child: Card(
                      child: Padding(
                        padding: const EdgeInsets.all(20),
                        child: Column(
                          children: [
                            Icon(
                              Icons.person_off_outlined,
                              size: 40,
                              color: Theme.of(context).colorScheme.outline,
                            ),
                            const SizedBox(height: 12),
                            Text(
                              _rows.isEmpty
                                  ? 'Адресов пока нет'
                                  : 'В этой вкладке нет пиров с IP',
                              textAlign: TextAlign.center,
                              style: Theme.of(context).textTheme.titleSmall,
                            ),
                            const SizedBox(height: 8),
                            Text(
                              _rows.isEmpty
                                  ? 'Заполни форму «Новый адрес» сверху и нажми «Добавить», '
                                      'потом «Сохранить».'
                                  : 'Переключи Wi‑Fi / mesh / «Все» или добавь IP '
                                      'для этого режима.',
                              textAlign: TextAlign.center,
                              style: Theme.of(context).textTheme.bodyMedium,
                            ),
                          ],
                        ),
                      ),
                    ),
                  ),
                ...visible.map((i) {
                  final r = _rows[i];
                  final ip = r.ip.text.trim();
                  final nm = r.name.text.trim();
                  final title = nm.isEmpty ? ip : '$nm · $ip';
                  final sub = _kindLabels[r.networkKind] ?? r.networkKind;
                  return Card(
                    margin: const EdgeInsets.only(bottom: 6),
                    child: ExpansionTile(
                      tilePadding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: -2,
                      ),
                      childrenPadding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
                      title: Text(
                        title.isEmpty ? '…' : title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: Theme.of(context).textTheme.bodyLarge,
                      ),
                      subtitle: Text(
                        sub,
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                      children: [
                        TextField(
                          controller: r.ip,
                          decoration: const InputDecoration(
                            labelText: 'IP',
                            isDense: true,
                            border: OutlineInputBorder(),
                          ),
                          keyboardType: TextInputType.url,
                          onChanged: (_) => setState(() {}),
                        ),
                        const SizedBox(height: 6),
                        TextField(
                          controller: r.peerSecret,
                          obscureText: true,
                          decoration: const InputDecoration(
                            labelText: 'Пароль устройства',
                            isDense: true,
                            border: OutlineInputBorder(),
                          ),
                        ),
                        const SizedBox(height: 6),
                        TextField(
                          controller: r.name,
                          decoration: const InputDecoration(
                            labelText: 'Подпись',
                            isDense: true,
                            border: OutlineInputBorder(),
                          ),
                        ),
                        const SizedBox(height: 6),
                        DropdownButtonFormField<String>(
                          value: r.networkKind == 'lan' ||
                                  r.networkKind == 'tailscale' ||
                                  r.networkKind == 'auto'
                              ? r.networkKind
                              : 'auto',
                          isDense: true,
                          decoration: const InputDecoration(
                            labelText: 'Сеть',
                            isDense: true,
                            border: OutlineInputBorder(),
                          ),
                          items: _kindLabels.entries
                              .map(
                                (e) => DropdownMenuItem(
                                  value: e.key,
                                  child: Text(e.value),
                                ),
                              )
                              .toList(),
                          onChanged: (v) {
                            if (v == null) return;
                            setState(() => r.networkKind = v);
                          },
                        ),
                        Row(
                          mainAxisAlignment: MainAxisAlignment.end,
                          children: [
                            TextButton.icon(
                              onPressed: () => _ping(i),
                              icon: const Icon(Icons.radar, size: 18),
                              label: const Text('Ping'),
                            ),
                            TextButton.icon(
                              onPressed: () {
                                setState(() {
                                  _rows[i].dispose();
                                  _rows.removeAt(i);
                                });
                              },
                              icon: const Icon(Icons.delete_outline, size: 18),
                              label: const Text('Удалить'),
                            ),
                          ],
                        ),
                      ],
                    ),
                  );
                }),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Text(
                      'Группы',
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                    const Spacer(),
                    TextButton.icon(
                      onPressed: () {
                        setState(() {
                          _groups.add(_GroupEdit(
                            id: _newId(),
                            name: TextEditingController(text: 'Дом'),
                            memberIps: [],
                            sendToGroup: false,
                          ));
                        });
                      },
                      icon: const Icon(Icons.group_add, size: 20),
                      label: const Text('Группа'),
                    ),
                  ],
                ),
                Text(
                  'Группы нужны для вкладки «Отправить»: там чипами выбираешь, на кого слать. '
                  'Здесь только состав группы (IP из списка выше).',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                if (_groups.isEmpty)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 16),
                    child: Text(
                      'Групп пока нет. Нажми «Группа», выбери участников из списка пиров '
                      '(сначала сохрани пиров с IP).',
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                  ),
                const SizedBox(height: 8),
                ..._groups.map((g) {
                  return Card(
                    margin: const EdgeInsets.only(bottom: 6),
                    child: ExpansionTile(
                      tilePadding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: -2,
                      ),
                      childrenPadding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
                      title: Text(
                        g.name.text.trim().isEmpty
                            ? 'Группа'
                            : g.name.text.trim(),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      subtitle: Text(
                        '${g.memberIps.length} адр.',
                        style: Theme.of(context).textTheme.bodySmall,
                      ),
                      children: [
                        TextField(
                          controller: g.name,
                          decoration: const InputDecoration(
                            labelText: 'Название',
                            isDense: true,
                            border: OutlineInputBorder(),
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          'Участники',
                          style: Theme.of(context).textTheme.labelSmall,
                        ),
                        const SizedBox(height: 4),
                        _GroupMemberPicker(
                          group: g,
                          peerIps: _rows
                              .map((r) => r.ip.text.trim())
                              .where((s) => s.isNotEmpty)
                              .toList(),
                          onChanged: () => setState(() {}),
                        ),
                        Align(
                          alignment: Alignment.centerRight,
                          child: TextButton.icon(
                            onPressed: () {
                              setState(() {
                                g.dispose();
                                _groups.remove(g);
                              });
                            },
                            icon: const Icon(Icons.delete_outline, size: 18),
                            label: const Text('Удалить группу'),
                          ),
                        ),
                      ],
                    ),
                  );
                }),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _PeerRow {
  _PeerRow({
    required this.ip,
    required this.name,
    required this.peerSecret,
    required this.send,
    this.networkKind = 'auto',
  });
  final TextEditingController ip;
  final TextEditingController name;
  final TextEditingController peerSecret;
  bool send;
  String networkKind;

  void dispose() {
    ip.dispose();
    name.dispose();
    peerSecret.dispose();
  }
}

class _GroupEdit {
  _GroupEdit({
    required this.id,
    required this.name,
    required List<String> memberIps,
    required this.sendToGroup,
  }) : memberIps = List<String>.from(memberIps);
  final String id;
  final TextEditingController name;
  final List<String> memberIps;
  bool sendToGroup;

  void dispose() {
    name.dispose();
  }
}

class _GroupMemberPicker extends StatelessWidget {
  const _GroupMemberPicker({
    required this.group,
    required this.peerIps,
    required this.onChanged,
  });

  final _GroupEdit group;
  final List<String> peerIps;
  final VoidCallback onChanged;

  @override
  Widget build(BuildContext context) {
    if (peerIps.isEmpty) {
      return Text(
        'Нет IP в списке пиров — добавь и сохрани пиров, затем выбери участников.',
        style: Theme.of(context).textTheme.bodySmall?.copyWith(
              color: Theme.of(context).colorScheme.error,
            ),
      );
    }
    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: peerIps.map((ip) {
        final sel = group.memberIps.contains(ip);
        return FilterChip(
          label: Text(ip),
          selected: sel,
          onSelected: (_) {
            if (sel) {
              group.memberIps.remove(ip);
            } else {
              group.memberIps.add(ip);
            }
            onChanged();
          },
        );
      }).toList(),
    );
  }
}
