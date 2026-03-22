import 'package:flutter/material.dart';
import 'package:portal_flutter/data/settings_repository.dart';

class PeersScreen extends StatefulWidget {
  const PeersScreen({super.key});

  @override
  State<PeersScreen> createState() => _PeersScreenState();
}

class _PeersScreenState extends State<PeersScreen> {
  final _rows = <_PeerRow>[];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final st = await SettingsRepository.load();
    _rows.clear();
    for (final p in st.peers) {
      _rows.add(_PeerRow(
        ip: TextEditingController(text: p.ip),
        name: TextEditingController(text: p.name),
        send: p.send,
      ));
    }
    if (_rows.isEmpty) {
      _rows.add(_PeerRow(
        ip: TextEditingController(text: '100.'),
        name: TextEditingController(),
        send: true,
      ));
    }
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _save() async {
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
    if (peers.isEmpty) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Добавь хотя бы один IP')),
      );
      return;
    }
    final st = await SettingsRepository.load();
    await SettingsRepository.save(PortalSettings(
      peers: peers,
      secret: st.secret,
      receiveDir: st.receiveDir,
    ));
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Сохранено')),
    );
  }

  @override
  void dispose() {
    for (final r in _rows) {
      r.ip.dispose();
      r.name.dispose();
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
                  onPressed: () {
                    setState(() {
                      _rows.add(_PeerRow(
                        ip: TextEditingController(),
                        name: TextEditingController(),
                        send: true,
                      ));
                    });
                  },
                  icon: const Icon(Icons.add),
                ),
                FilledButton(onPressed: _save, child: const Text('Сохранить')),
              ],
            ),
          ),
          Expanded(
            child: ListView.builder(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              itemCount: _rows.length,
              itemBuilder: (ctx, i) {
                final r = _rows[i];
                return Card(
                  child: Padding(
                    padding: const EdgeInsets.all(12),
                    child: Column(
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
                              onChanged: (v) =>
                                  setState(() => r.send = v ?? true),
                            ),
                            const Text('Отправка на этот адрес'),
                            const Spacer(),
                            IconButton(
                              onPressed: () {
                                setState(() {
                                  r.ip.dispose();
                                  r.name.dispose();
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
              },
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
