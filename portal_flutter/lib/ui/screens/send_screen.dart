import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:portal_flutter/data/history_repository.dart';
import 'package:portal_flutter/data/settings_repository.dart';
import 'package:portal_flutter/portal/protocol_client.dart';
import 'package:portal_flutter/ui/pending_share.dart';

class SendScreen extends StatefulWidget {
  const SendScreen({super.key});

  @override
  State<SendScreen> createState() => _SendScreenState();
}

class _SendScreenState extends State<SendScreen> {
  final _text = TextEditingController();
  String? _filePath;
  bool _busy = false;
  String _status = '';

  @override
  void initState() {
    super.initState();
    pendingSharePaths.addListener(_onShare);
    final sh = pendingSharePaths.value;
    if (sh.isNotEmpty) {
      _filePath = sh.first;
    }
  }

  void _onShare() {
    final sh = pendingSharePaths.value;
    if (sh.isNotEmpty && mounted) {
      setState(() => _filePath = sh.first);
    }
  }

  @override
  void dispose() {
    pendingSharePaths.removeListener(_onShare);
    _text.dispose();
    super.dispose();
  }

  Future<List<PeerDto>> _targets() async {
    final st = await SettingsRepository.load();
    return st.peersForSending();
  }

  Future<void> _pickFile() async {
    final r = await FilePicker.platform.pickFiles();
    if (r != null && r.files.single.path != null) {
      setState(() => _filePath = r.files.single.path);
    }
  }

  Future<void> _sendFile() async {
    final path = _filePath;
    if (path == null || !await File(path).exists()) {
      setState(() => _status = 'Выбери файл');
      return;
    }
    final tg = await _targets();
    if (tg.isEmpty) {
      setState(() => _status = 'Нет получателей: пиры с галочкой или группа с «Отправка на группу»');
      return;
    }
    setState(() {
      _busy = true;
      _status = 'Отправка...';
    });
    final st = await SettingsRepository.load();
    final ips = <String>[];
    for (final p in tg) {
      ips.add(p.ip.trim());
    }
    final errs = <String>[];
    for (final p in tg) {
      final r = await sendFileToPeer(p.ip.trim(), path, secret: st.secret);
      if (!r.$1) errs.add('${p.ip}: ${r.$2}');
    }
    if (errs.isEmpty) {
      await HistoryRepository.insert(
        direction: 'send',
        kind: 'file',
        peerIp: ips.first,
        peerLabel: tg.first.name,
        name: path.split(Platform.pathSeparator).last,
        storedPath: path,
        routeJson: jsonEncode(ips),
        filesize: await File(path).length(),
      );
    }
    if (mounted) {
      setState(() {
        _busy = false;
        _status = errs.isEmpty
            ? 'Готово'
            : 'Ошибки: ${errs.take(2).join('; ')}';
      });
    }
  }

  Future<void> _sendText() async {
    final t = _text.text;
    if (t.trim().isEmpty) {
      setState(() => _status = 'Введи текст');
      return;
    }
    final tg = await _targets();
    if (tg.isEmpty) {
      setState(() => _status = 'Нет получателей: пиры / группы');
      return;
    }
    setState(() {
      _busy = true;
      _status = 'Отправка текста...';
    });
    final st = await SettingsRepository.load();
    final ips = tg.map((e) => e.ip.trim()).toList();
    final errs = <String>[];
    for (final p in tg) {
      final r = await sendTextToPeer(p.ip.trim(), t, secret: st.secret);
      if (!r.$1) errs.add('${p.ip}: ${r.$2}');
    }
    if (errs.isEmpty) {
      await HistoryRepository.insert(
        direction: 'send',
        kind: 'text',
        peerIp: ips.first,
        peerLabel: tg.first.name,
        name: 'clipboard',
        snippet: t.length > 500 ? t.substring(0, 500) : t,
        routeJson: jsonEncode(ips),
      );
    }
    if (mounted) {
      setState(() {
        _busy = false;
        _status = errs.isEmpty ? 'Текст отправлен' : errs.join('; ');
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: ListView(
        keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
        padding: const EdgeInsets.all(16),
        children: [
          Text('Отправить', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 12),
          ListTile(
            title: Text(_filePath ?? 'Файл не выбран'),
            subtitle: const Text('Из Share или кнопка ниже'),
            trailing: IconButton(
              onPressed: _busy ? null : _pickFile,
              icon: const Icon(Icons.attach_file),
            ),
          ),
          FilledButton(
            onPressed: _busy ? null : _sendFile,
            child: const Text('Отправить файл'),
          ),
          const Divider(height: 32),
          TextField(
            controller: _text,
            maxLines: 4,
            decoration: const InputDecoration(
              labelText: 'Текст на ПК (буфер)',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 12),
          FilledButton.tonal(
            onPressed: _busy ? null : _sendText,
            child: const Text('Отправить текст'),
          ),
          if (_busy) const Padding(
            padding: EdgeInsets.all(16),
            child: LinearProgressIndicator(),
          ),
          if (_status.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(top: 16),
              child: Text(_status),
            ),
        ],
      ),
    );
  }
}
