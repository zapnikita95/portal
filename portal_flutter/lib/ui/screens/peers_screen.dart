import 'package:flutter/material.dart';
import 'package:portal_flutter/data/settings_repository.dart';
import 'package:portal_flutter/portal/lan_scan.dart';
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

  /// Строка-черновик в конце списка (пустой IP).
  _PeerRow _newDraftRow() {
    return _PeerRow(
      ip: TextEditingController(),
      name: TextEditingController(),
      peerSecret: TextEditingController(),
      send: true,
      networkKind: _defaultKindForTab(),
    );
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
        send: p.send,
        networkKind: p.networkKind,
      ));
    }

    _lanScope = lanScanScopeFromStorage(st.lanScanMode);
    _lanSeed.text = st.lanSeedHintIp;

    for (final g in st.peerGroups) {
      _groups.add(_GroupEdit(
        id: g.id.isNotEmpty ? g.id : _newId(),
        name: TextEditingController(text: g.name),
        memberIps: List<String>.from(g.memberIps),
        sendToGroup: g.sendToGroup,
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
        send: r.send,
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
        sendToGroup: g.sendToGroup,
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
                  'Укажи IPv4 в нужной сети (как в «Настройки → Сеть» или адрес пира). '
                  'По нему и другим известным адресам строятся диапазоны поиска (хосты .1–.254 '
                  'в той же «третьей части» IPv4). Пусто — берём IP с интерфейсов ОС и из списка пиров.',
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
    final seeds = seedsForScope(
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
                'Ищем Portal (${lanScanScopeLabel(_lanScope)})…',
              ),
            ),
          ],
        ),
      ),
    );
    List<String> found;
    try {
      found = await scanLanForPortalHosts(
        candidateSecrets: PortalSecrets.orderedCandidateSecrets(st),
        scope: _lanScope,
        peerHints: peerHints,
        manualLanSeedIp: manual,
      );
    } catch (e) {
      found = [];
      if (mounted) {
        Navigator.of(context).pop();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Скан: $e')),
        );
      }
      return;
    }
    if (!mounted) return;
    Navigator.of(context).pop();
    if (found.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Никого не нашли. Wi‑Fi/mesh, ПК слушает :12345, пароль (общий или у пира) совпадает с ПК.',
          ),
          duration: Duration(seconds: 5),
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
                    return CheckboxListTile(
                      title: Text(ip),
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
                  'Введи пароль как на ПК (config.json). Сохранится у каждого добавленного IP. '
                  'Пусто — использовать только общий пароль из «Настроить». '
                  'Разные пароли у разных машин можно задать потом в строке пира.',
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
            FilledButton(
              onPressed: () => Navigator.pop(ctx, c.text.trim()),
              child: const Text('Добавить'),
            ),
          ],
        );
      },
    );
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
      _rows.add(row);
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
                IconButton(
                  tooltip: 'Добавить пира',
                  onPressed: () {
                    setState(() {
                      _rows.add(_newDraftRow());
                    });
                  },
                  icon: const Icon(Icons.add),
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
                  'Вкладки Wi‑Fi / mesh / Все фильтруют список. Тип сети у строки задаётся вручную. '
                  'Нажми «Сохранить», чтобы записать пиров, группы и подсказку для LAN-скана.',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 12),
                Text(
                  'Вкладка = фильтр списка и режим сканирования',
                  style: Theme.of(context).textTheme.titleSmall,
                ),
                const SizedBox(height: 6),
                Text(
                  'Wi‑Fi — только пиры с типом «домашняя» или авто с LAN-IP. '
                  'mesh — только mesh-VPN (100.64–127.x) или явно помеченные. '
                  '«Все» — весь список.',
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
                    setState(() => _lanScope = next.first);
                  },
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
                                  ? 'Нажми «+» (Добавить пира), введи IP и подпись, '
                                      'затем «Сохранить».'
                                  : 'Переключи Wi‑Fi / mesh / «Все» или добавь пира с IP '
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
                  return Card(
                    margin: const EdgeInsets.only(bottom: 10),
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          TextField(
                            controller: r.ip,
                            decoration: const InputDecoration(
                              labelText: 'IP',
                              border: OutlineInputBorder(),
                            ),
                            keyboardType: TextInputType.url,
                            onChanged: (_) => setState(() {}),
                          ),
                          const SizedBox(height: 8),
                          TextField(
                            controller: r.name,
                            decoration: const InputDecoration(
                              labelText: 'Подпись',
                              border: OutlineInputBorder(),
                            ),
                          ),
                          const SizedBox(height: 8),
                          TextField(
                            controller: r.peerSecret,
                            obscureText: true,
                            decoration: const InputDecoration(
                              labelText: 'Пароль этого Portal (необязательно)',
                              helperText:
                                  'Пусто = общий из «Настроить». Свой — если на этом ПК другой пароль.',
                              border: OutlineInputBorder(),
                            ),
                          ),
                          const SizedBox(height: 8),
                          DropdownButtonFormField<String>(
                            value: r.networkKind == 'lan' ||
                                    r.networkKind == 'tailscale' ||
                                    r.networkKind == 'auto'
                                ? r.networkKind
                                : 'auto',
                            decoration: const InputDecoration(
                              labelText: 'Сеть',
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
                            children: [
                              Checkbox(
                                value: r.send,
                                onChanged: (v) {
                                  setState(() => r.send = v ?? true);
                                },
                              ),
                              const Expanded(
                                child: Text('Отправка на этот адрес'),
                              ),
                              IconButton(
                                tooltip: 'Ping (pong с ПК)',
                                onPressed: () => _ping(i),
                                icon: const Icon(Icons.radar),
                              ),
                              IconButton(
                                onPressed: () {
                                  setState(() {
                                    _rows[i].dispose();
                                    _rows.removeAt(i);
                                  });
                                },
                                icon: const Icon(Icons.delete_outline),
                              ),
                            ],
                          ),
                        ],
                      ),
                    ),
                  );
                }),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Text(
                      'Группы для отправки',
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
                  'Если у группы включена «Отправка на группу», в «Отправить» берутся только IP из отмеченных групп (и только те, что есть в списке пиров выше). Иначе — по галочке у каждого пира.',
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
                    margin: const EdgeInsets.only(bottom: 10),
                    child: Padding(
                      padding: const EdgeInsets.all(12),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          TextField(
                            controller: g.name,
                            decoration: const InputDecoration(
                              labelText: 'Название группы',
                              border: OutlineInputBorder(),
                            ),
                          ),
                          const SizedBox(height: 8),
                          Text(
                            'Участники (выбери IP из сохранённых пиров выше)',
                            style: Theme.of(context).textTheme.labelLarge,
                          ),
                          const SizedBox(height: 6),
                          _GroupMemberPicker(
                            group: g,
                            peerIps: _rows
                                .map((r) => r.ip.text.trim())
                                .where((s) => s.isNotEmpty)
                                .toList(),
                            onChanged: () => setState(() {}),
                          ),
                          CheckboxListTile(
                            contentPadding: EdgeInsets.zero,
                            title: const Text('Отправка на эту группу'),
                            value: g.sendToGroup,
                            onChanged: (v) {
                              setState(() => g.sendToGroup = v ?? false);
                            },
                          ),
                          Align(
                            alignment: Alignment.centerRight,
                            child: IconButton(
                              onPressed: () {
                                setState(() {
                                  g.dispose();
                                  _groups.remove(g);
                                });
                              },
                              icon: const Icon(Icons.delete_outline),
                            ),
                          ),
                        ],
                      ),
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
