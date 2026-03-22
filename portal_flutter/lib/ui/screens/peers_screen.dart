import 'dart:async';

import 'package:flutter/material.dart';
import 'package:portal_flutter/data/settings_repository.dart';
import 'package:portal_flutter/portal/lan_scan.dart';
import 'package:portal_flutter/portal/protocol_client.dart';

class PeersScreen extends StatefulWidget {
  const PeersScreen({super.key});

  @override
  State<PeersScreen> createState() => _PeersScreenState();
}

class _PeersScreenState extends State<PeersScreen> {
  final _rows = <_PeerRow>[];
  final _groups = <_GroupEdit>[];
  bool _loading = true;
  Timer? _debounce;
  bool _saving = false;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final st = await SettingsRepository.load();
    for (final r in _rows) {
      r.ip.removeListener(_scheduleAutosave);
      r.name.removeListener(_scheduleAutosave);
      r.ip.dispose();
      r.name.dispose();
    }
    _rows.clear();
    for (final g in _groups) {
      g.name.removeListener(_scheduleAutosave);
      g.ipsCsv.removeListener(_scheduleAutosave);
      g.name.dispose();
      g.ipsCsv.dispose();
    }
    _groups.clear();

    for (final p in st.peers) {
      final row = _PeerRow(
        ip: TextEditingController(text: p.ip),
        name: TextEditingController(text: p.name),
        send: p.send,
      );
      _wireRow(row);
      _rows.add(row);
    }
    if (_rows.isEmpty) {
      final row = _PeerRow(
        ip: TextEditingController(text: '100.'),
        name: TextEditingController(),
        send: true,
      );
      _wireRow(row);
      _rows.add(row);
    }

    for (final g in st.peerGroups) {
      final ge = _GroupEdit(
        id: g.id.isNotEmpty ? g.id : _newId(),
        name: TextEditingController(text: g.name),
        ipsCsv: TextEditingController(text: g.memberIps.join(', ')),
        sendToGroup: g.sendToGroup,
      );
      ge.name.addListener(_scheduleAutosave);
      ge.ipsCsv.addListener(_scheduleAutosave);
      _groups.add(ge);
    }

    if (mounted) setState(() => _loading = false);
  }

  void _wireRow(_PeerRow row) {
    row.ip.addListener(_scheduleAutosave);
    row.name.addListener(_scheduleAutosave);
  }

  String _newId() =>
      'g_${DateTime.now().microsecondsSinceEpoch}_${UniqueKey().hashCode}';

  void _scheduleAutosave() {
    _debounce?.cancel();
    _debounce = Timer(const Duration(milliseconds: 450), _flushSave);
  }

  Future<void> _flushSave() async {
    if (!mounted || _saving) return;
    _saving = true;
    try {
      final st0 = await SettingsRepository.load();
      final peers = <PeerDto>[];
      for (final r in _rows) {
        final ip = r.ip.text.trim();
        if (ip.isEmpty) continue;
        final nm = r.name.text.trim();
        peers.add(PeerDto(
          ip: ip,
          name: nm.isEmpty ? ip : nm,
          send: r.send,
        ));
      }
      final groups = <PeerGroupDto>[];
      for (final g in _groups) {
        final raw = g.ipsCsv.text.split(RegExp(r'[,\s;]+'));
        final ips = raw.map((s) => s.trim()).where((s) => s.isNotEmpty).toList();
        groups.add(PeerGroupDto(
          id: g.id,
          name: g.name.text.trim().isEmpty ? 'Группа' : g.name.text.trim(),
          memberIps: ips,
          sendToGroup: g.sendToGroup,
        ));
      }
      await SettingsRepository.save(PortalSettings(
        peers: peers,
        secret: st0.secret,
        receiveDir: st0.receiveDir,
        portalAnimPreset: st0.portalAnimPreset,
        peerGroups: groups,
      ));
    } finally {
      _saving = false;
    }
  }

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
    final ok = await pingPortal(ip, secret: st.secret);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          ok
              ? 'Pong: $ip'
              : 'Нет ответа: $ip. На ПК «Запустить портал», порт 12345; пароль как в config.json '
                  '(если на ПК пароль пустой — очисти поле в приложении); файрвол / Tailscale.',
        ),
        duration: const Duration(seconds: 6),
      ),
    );
  }

  Future<void> _lanScan() async {
    final st = await SettingsRepository.load();
    if (!mounted) return;
    final seeds = await collectLocalIpv4Seeds();
    if (seeds.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Нет локального IPv4 (Wi‑Fi выкл или нет прав). Включи сеть и попробуй снова.',
          ),
        ),
      );
      return;
    }
    showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => const AlertDialog(
        content: Row(
          children: [
            CircularProgressIndicator(),
            SizedBox(width: 20),
            Expanded(child: Text('Скан локальной сети…')),
          ],
        ),
      ),
    );
    List<String> found;
    try {
      found = await scanLanForPortalHosts(secret: st.secret);
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
            'Никого не нашли. Проверь Wi‑Fi, что ПК слушает :12345 и пароль совпадает.',
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
    final have = _rows.map((r) => r.ip.text.trim()).toSet();
    for (final ip in pick) {
      if (have.contains(ip)) continue;
      final row = _PeerRow(
        ip: TextEditingController(text: ip),
        name: TextEditingController(),
        send: true,
      );
      _wireRow(row);
      _rows.add(row);
      have.add(ip);
    }
    setState(() {});
    await _flushSave();
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Добавлено: ${pick.length}')),
      );
    }
  }

  Future<void> _saveNow() async {
    await _flushSave();
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Сохранено')),
      );
    }
  }

  @override
  void dispose() {
    _debounce?.cancel();
    for (final r in _rows) {
      r.ip.removeListener(_scheduleAutosave);
      r.name.removeListener(_scheduleAutosave);
      r.ip.dispose();
      r.name.dispose();
    }
    for (final g in _groups) {
      g.name.removeListener(_scheduleAutosave);
      g.ipsCsv.removeListener(_scheduleAutosave);
      g.name.dispose();
      g.ipsCsv.dispose();
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
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
                  onPressed: () {
                    setState(() {
                      final row = _PeerRow(
                        ip: TextEditingController(),
                        name: TextEditingController(),
                        send: true,
                      );
                      _wireRow(row);
                      _rows.add(row);
                    });
                    _scheduleAutosave();
                  },
                  icon: const Icon(Icons.add),
                ),
                FilledButton(onPressed: _saveNow, child: const Text('Сохранить')),
              ],
            ),
          ),
          Expanded(
            child: ListView(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              children: [
                Text(
                  'Изменения подтягиваются в хранилище автоматически; «Сохранить» — явное подтверждение.',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
                const SizedBox(height: 8),
                ...List.generate(_rows.length, (i) {
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
                          ),
                          const SizedBox(height: 8),
                          TextField(
                            controller: r.name,
                            decoration: const InputDecoration(
                              labelText: 'Подпись',
                              border: OutlineInputBorder(),
                            ),
                          ),
                          Row(
                            children: [
                              Checkbox(
                                value: r.send,
                                onChanged: (v) {
                                  setState(() => r.send = v ?? true);
                                  _scheduleAutosave();
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
                                    r.ip.removeListener(_scheduleAutosave);
                                    r.name.removeListener(_scheduleAutosave);
                                    r.ip.dispose();
                                    r.name.dispose();
                                    _rows.removeAt(i);
                                  });
                                  _scheduleAutosave();
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
                          final ge = _GroupEdit(
                            id: _newId(),
                            name: TextEditingController(text: 'Дом'),
                            ipsCsv: TextEditingController(),
                            sendToGroup: false,
                          );
                          ge.name.addListener(_scheduleAutosave);
                          ge.ipsCsv.addListener(_scheduleAutosave);
                          _groups.add(ge);
                        });
                        _scheduleAutosave();
                      },
                      icon: const Icon(Icons.group_add, size: 20),
                      label: const Text('Группа'),
                    ),
                  ],
                ),
                Text(
                  'Если у группы включена «Отправка на группу», в «Отпр.» берутся только IP из отмеченных групп (и только те, что есть в списке пиров выше). Иначе — как раньше, по галочке у каждого пира.',
                  style: Theme.of(context).textTheme.bodySmall,
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
                          TextField(
                            controller: g.ipsCsv,
                            decoration: const InputDecoration(
                              labelText: 'IP через запятую',
                              border: OutlineInputBorder(),
                              hintText: '100.1.2.3, 192.168.0.10',
                            ),
                          ),
                          CheckboxListTile(
                            contentPadding: EdgeInsets.zero,
                            title: const Text('Отправка на эту группу'),
                            value: g.sendToGroup,
                            onChanged: (v) {
                              setState(() => g.sendToGroup = v ?? false);
                              _scheduleAutosave();
                            },
                          ),
                          Align(
                            alignment: Alignment.centerRight,
                            child: IconButton(
                              onPressed: () {
                                setState(() {
                                  g.name.removeListener(_scheduleAutosave);
                                  g.ipsCsv.removeListener(_scheduleAutosave);
                                  g.name.dispose();
                                  g.ipsCsv.dispose();
                                  _groups.remove(g);
                                });
                                _scheduleAutosave();
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
    required this.send,
  });
  final TextEditingController ip;
  final TextEditingController name;
  bool send;
}

class _GroupEdit {
  _GroupEdit({
    required this.id,
    required this.name,
    required this.ipsCsv,
    required this.sendToGroup,
  });
  final String id;
  final TextEditingController name;
  final TextEditingController ipsCsv;
  bool sendToGroup;
}
