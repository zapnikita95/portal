import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:portal_flutter/data/history_repository.dart';
import 'package:portal_flutter/portal/protocol_client.dart';
import 'package:portal_flutter/data/settings_repository.dart';

class HistoryScreen extends StatefulWidget {
  const HistoryScreen({super.key});

  @override
  State<HistoryScreen> createState() => _HistoryScreenState();
}

class _HistoryScreenState extends State<HistoryScreen> {
  List<Map<String, Object?>> _rows = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final r = await HistoryRepository.list(limit: 200);
    if (mounted) {
      setState(() {
        _rows = r;
        _loading = false;
      });
    }
  }

  Future<void> _resend(int id) async {
    final row = await HistoryRepository.getRow(id);
    if (row == null) return;
    if (row['kind'] != 'file') {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Повтор только для файлов')),
        );
      }
      return;
    }
    final path = (row['stored_path'] ?? '').toString();
    if (path.isEmpty || !await File(path).exists()) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Файл не найден на устройстве')),
        );
      }
      return;
    }
    final raw = (row['route_json'] ?? '').toString();
    List<String> ips = [];
    try {
      final j = jsonDecode(raw);
      if (j is List) {
        ips = j.map((e) => e.toString()).where((e) => e.isNotEmpty).toList();
      }
    } catch (_) {}
    if (ips.isEmpty) {
      final ip = (row['peer_ip'] ?? '').toString();
      if (ip.isNotEmpty) ips = [ip];
    }
    if (ips.isEmpty) return;
    final st = await SettingsRepository.load();
    for (final ip in ips) {
      await sendFileToPeer(ip, path, secret: st.secret);
    }
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Повтор отправлен')),
      );
    }
  }

  Future<void> _copyPath(int id) async {
    final row = await HistoryRepository.getRow(id);
    if (row == null) return;
    final path = (row['stored_path'] ?? '').toString();
    final snip = (row['snippet'] ?? '').toString();
    final t = path.isNotEmpty ? path : snip;
    if (t.isEmpty) return;
    await Clipboard.setData(ClipboardData(text: t));
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Скопировано')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    if (_rows.isEmpty) {
      return const Center(child: Text('История пуста'));
    }
    return RefreshIndicator(
      onRefresh: _load,
      child: ListView.builder(
        itemCount: _rows.length,
        itemBuilder: (ctx, i) {
          final r = _rows[i];
          final id = r['id'] as int?;
          final ts = r['ts'] as int? ?? 0;
          final dir = r['direction'] ?? '';
          final kind = r['kind'] ?? '';
          final nameStr = (r['name'] ?? '').toString();
          final dt = DateTime.fromMillisecondsSinceEpoch(ts * 1000);
          final titleSuffix =
              nameStr.isNotEmpty ? ' · $nameStr' : '';
          return ListTile(
            title: Text('$dir / $kind$titleSuffix'),
            subtitle: Text('$dt'),
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                if (kind == 'file')
                  IconButton(
                    icon: const Icon(Icons.repeat),
                    onPressed: id == null ? null : () => _resend(id),
                  ),
                IconButton(
                  icon: const Icon(Icons.copy),
                  onPressed: id == null ? null : () => _copyPath(id),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}
