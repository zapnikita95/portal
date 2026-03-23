import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:portal_flutter/data/history_repository.dart';
import 'package:portal_flutter/data/settings_repository.dart';
import 'package:portal_flutter/portal/protocol_client.dart';
import 'package:portal_flutter/ui/pending_share.dart';
import 'package:portal_flutter/util/send_errors.dart';

class SendScreen extends StatefulWidget {
  const SendScreen({super.key, this.onOpenSettings});

  /// Переключить нижнюю вкладку на «Настроить» (из диалога про пароль).
  final VoidCallback? onOpenSettings;

  @override
  State<SendScreen> createState() => _SendScreenState();
}

class _SendScreenState extends State<SendScreen> {
  final _text = TextEditingController();
  String? _filePath;
  bool _busy = false;
  String _status = '';
  PortalSettings? _settingsSnap;

  /// Кому слать в этом сеансе (подмножество пиров с галочкой «Отправка» / группы).
  final Set<String> _selectedSendIps = {};
  bool _sendSelectionTouched = false;

  @override
  void initState() {
    super.initState();
    pendingSharePaths.addListener(_onShare);
    final sh = pendingSharePaths.value;
    if (sh.isNotEmpty) {
      _filePath = sh.first;
    }
    _reloadSettings();
  }

  Future<void> _reloadSettings() async {
    final st = await SettingsRepository.load();
    if (!mounted) return;
    setState(() {
      _settingsSnap = st;
      _mergeSendSelectionFromPool(_poolIps(st));
    });
  }

  Set<String> _poolIps(PortalSettings st) {
    return st
        .peersForSending()
        .map((p) => p.ip.trim())
        .where((s) => s.isNotEmpty)
        .toSet();
  }

  void _mergeSendSelectionFromPool(Set<String> pool) {
    _selectedSendIps.removeWhere((ip) => !pool.contains(ip));
    if (!_sendSelectionTouched) {
      _selectedSendIps
        ..clear()
        ..addAll(pool);
      return;
    }
    for (final ip in pool) {
      if (!_selectedSendIps.contains(ip)) {
        _selectedSendIps.add(ip);
      }
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

  List<PeerDto> _selectedTargets(PortalSettings st) {
    final pool = st.peersForSending();
    return pool.where((p) => _selectedSendIps.contains(p.ip.trim())).toList();
  }

  Future<bool> _ensureSecretAllowsSend() async {
    final st = await SettingsRepository.load();
    if (st.secret.trim().isNotEmpty) return true;
    if (!mounted) return false;
    final r = await showDialog<String>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        title: const Text('Пароль сети не указан'),
        content: const Text(
          'Без пароля Portal на компьютере с заданным паролем отклонит передачу.\n\n'
          'Укажи тот же пароль во вкладке «Настроить», что в настройках Portal на ПК.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx, 'cancel'),
            child: const Text('Отмена'),
          ),
          TextButton(
            onPressed: () => Navigator.pop(ctx, 'settings'),
            child: const Text('Настроить'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, 'proceed'),
            child: const Text('Всё равно отправить'),
          ),
        ],
      ),
    );
    if (r == 'settings') {
      widget.onOpenSettings?.call();
      return false;
    }
    return r == 'proceed';
  }

  Future<void> _pickFile() async {
    final r = await FilePicker.platform.pickFiles();
    if (r != null && r.files.single.path != null) {
      setState(() => _filePath = r.files.single.path);
    }
  }

  Future<void> _sendFile() async {
    if (!await _ensureSecretAllowsSend()) return;

    final path = _filePath;
    if (path == null || !await File(path).exists()) {
      setState(() => _status = 'Выбери файл');
      return;
    }
    final st = await SettingsRepository.load();
    final tg = _selectedTargets(st);
    if (st.peersForSending().isEmpty) {
      setState(() => _status =
          'Нет получателей в списке: добавь пиров во вкладке «Пиры» и включи «Отправка» или группу.');
      return;
    }
    if (tg.isEmpty) {
      setState(() =>
          _status = 'Отметь хотя бы одного получателя внизу («Кому отправить»).');
      return;
    }

    setState(() {
      _busy = true;
      _status = 'Отправка...';
    });
    final secret = st.secret;
    final ips = tg.map((e) => e.ip.trim()).toList();
    final errs = <String>[];
    for (final p in tg) {
      final r = await sendFileToPeer(p.ip.trim(), path, secret: secret);
      if (!r.$1) {
        errs.add(humanizePortalSendError(r.$2, host: p.ip.trim()));
      }
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
    await _reloadSettings();
    if (mounted) {
      setState(() {
        _busy = false;
        _status = errs.isEmpty
            ? 'Готово'
            : errs.length == 1
                ? errs.first
                : 'Ошибки:\n${errs.take(4).join('\n')}';
      });
    }
  }

  Future<void> _sendText() async {
    if (!await _ensureSecretAllowsSend()) return;

    final t = _text.text;
    if (t.trim().isEmpty) {
      setState(() => _status = 'Введи текст');
      return;
    }
    final st = await SettingsRepository.load();
    final tg = _selectedTargets(st);
    if (st.peersForSending().isEmpty) {
      setState(() => _status = 'Нет получателей — настрой пиров во вкладке «Пиры».');
      return;
    }
    if (tg.isEmpty) {
      setState(() =>
          _status = 'Отметь хотя бы одного получателя внизу («Кому отправить»).');
      return;
    }

    setState(() {
      _busy = true;
      _status = 'Отправка текста...';
    });
    final secret = st.secret;
    final ips = tg.map((e) => e.ip.trim()).toList();
    final errs = <String>[];
    for (final p in tg) {
      final r = await sendTextToPeer(p.ip.trim(), t, secret: secret);
      if (!r.$1) {
        errs.add(humanizePortalSendError(r.$2, host: p.ip.trim()));
      }
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
    await _reloadSettings();
    if (mounted) {
      setState(() {
        _busy = false;
        _status = errs.isEmpty
            ? 'Текст отправлен'
            : errs.length == 1
                ? errs.first
                : 'Ошибки:\n${errs.take(4).join('\n')}';
      });
    }
  }

  Widget _buildTargetsCard(PortalSettings st) {
    final tg = st.peersForSending();
    final anyGroup = st.peerGroups.any((g) => g.sendToGroup);

    if (tg.isEmpty) {
      return Card(
        margin: EdgeInsets.zero,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Кому отправить',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 8),
              Text(
                anyGroup
                    ? 'Нет пиров с IP из отмеченных групп (или группы пустые). '
                        'Настрой во вкладке «Пиры».'
                    : 'Нет пиров с галочкой «Отправка». Добавь адреса во вкладке «Пиры».',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
            ],
          ),
        ),
      );
    }

    final groupNames = <String>{};
    if (anyGroup) {
      for (final g in st.peerGroups.where((x) => x.sendToGroup)) {
        groupNames.add(g.name);
      }
    }

    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(8, 8, 8, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    'Кому отправить',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                TextButton(
                  onPressed: _busy
                      ? null
                      : () {
                          setState(() {
                            _sendSelectionTouched = true;
                            final pool = _poolIps(st);
                            if (_selectedSendIps.length == pool.length) {
                              _selectedSendIps.clear();
                            } else {
                              _selectedSendIps
                                ..clear()
                                ..addAll(pool);
                            }
                          });
                        },
                  child: Text(
                    _selectedSendIps.length == _poolIps(st).length
                        ? 'Снять все'
                        : 'Выбрать все',
                  ),
                ),
                IconButton(
                  tooltip: 'Обновить список',
                  onPressed: _busy ? null : _reloadSettings,
                  icon: const Icon(Icons.refresh, size: 20),
                ),
              ],
            ),
            if (groupNames.isNotEmpty) ...[
              Padding(
                padding: const EdgeInsets.only(left: 8, bottom: 4),
                child: Text(
                  'Группы: ${groupNames.join(', ')}',
                  style: Theme.of(context).textTheme.bodySmall,
                ),
              ),
            ],
            ConstrainedBox(
              constraints: BoxConstraints(
                maxHeight: (tg.length * 52.0).clamp(120.0, 280.0),
              ),
              child: ListView(
                shrinkWrap: true,
                children: tg.map((p) {
                  final ip = p.ip.trim();
                  final checked = _selectedSendIps.contains(ip);
                  return CheckboxListTile(
                    value: checked,
                    onChanged: _busy
                        ? null
                        : (v) {
                            setState(() {
                              _sendSelectionTouched = true;
                              if (v == true) {
                                _selectedSendIps.add(ip);
                              } else {
                                _selectedSendIps.remove(ip);
                              }
                            });
                          },
                    secondary: Icon(
                      p.networkKind == 'tailscale'
                          ? Icons.vpn_key_outlined
                          : Icons.lan_outlined,
                      size: 22,
                    ),
                    title: Text(
                      p.name.isNotEmpty ? p.name : ip,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                    ),
                    subtitle: Text(ip, maxLines: 1, overflow: TextOverflow.ellipsis),
                    controlAffinity: ListTileControlAffinity.leading,
                    dense: true,
                  );
                }).toList(),
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final st = _settingsSnap;
    return SafeArea(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Expanded(
            child: ListView(
              keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
              children: [
                Text('Отправить', style: Theme.of(context).textTheme.titleLarge),
                const SizedBox(height: 12),
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  title: Text(_filePath ?? 'Файл не выбран'),
                  subtitle: const Text('Из «Поделиться» или кнопка справа'),
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
                if (_busy)
                  const Padding(
                    padding: EdgeInsets.only(top: 16),
                    child: LinearProgressIndicator(),
                  ),
                if (_status.isNotEmpty)
                  Padding(
                    padding: const EdgeInsets.only(top: 16),
                    child: SelectableText(
                      _status,
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                  ),
              ],
            ),
          ),
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
            child: st != null
                ? _buildTargetsCard(st)
                : const LinearProgressIndicator(),
          ),
        ],
      ),
    );
  }
}
