import 'dart:convert';
import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:portal_flutter/data/history_repository.dart';
import 'package:portal_flutter/data/settings_repository.dart';
import 'package:portal_flutter/portal/portal_secrets.dart';
import 'package:portal_flutter/portal/protocol_client.dart';
import 'package:portal_flutter/ui/pending_share.dart';
import 'package:portal_flutter/util/send_errors.dart';
import 'package:shared_preferences/shared_preferences.dart';

class SendScreen extends StatefulWidget {
  const SendScreen({super.key, this.onOpenSettings});

  /// Переключить нижнюю вкладку на «Настроить» (из диалога про пароль).
  final VoidCallback? onOpenSettings;

  @override
  State<SendScreen> createState() => _SendScreenState();
}

class _SendScreenState extends State<SendScreen> {
  static const _kDefaultSendGroupId = 'portal_flutter_default_send_group_id';

  final _text = TextEditingController();
  String? _filePath;
  bool _busy = false;
  String _status = '';
  PortalSettings? _settingsSnap;

  /// Активные группы (чипы): при снятии группы IP убираются, если их не покрывает другая активная группа.
  final Set<String> _activeGroupIds = <String>{};

  /// Итоговые IP для отправки (чекбоксы + члены активных групп).
  final Set<String> _selectedSendIps = <String>{};

  bool _sendSelectionTouched = false;
  bool _appliedDefaultGroupOnce = false;

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
    final prefs = await SharedPreferences.getInstance();
    var defId = prefs.getString(_kDefaultSendGroupId) ?? '';
    if (defId.isNotEmpty && !st.peerGroups.any((g) => g.id == defId)) {
      await prefs.remove(_kDefaultSendGroupId);
      defId = '';
    }
    if (!mounted) return;
    setState(() {
      _settingsSnap = st;
      _pruneSelection(st);
      if (!_sendSelectionTouched && !_appliedDefaultGroupOnce) {
        _appliedDefaultGroupOnce = true;
        if (defId.isNotEmpty) {
          PeerGroupDto? g;
          for (final x in st.peerGroups) {
            if (x.id == defId) {
              g = x;
              break;
            }
          }
          if (g != null && _validMemberIps(st, g).isNotEmpty) {
            _activeGroupIds
              ..clear()
              ..add(defId);
            _selectedSendIps
              ..clear()
              ..addAll(_validMemberIps(st, g));
          }
        }
      }
    });
  }

  void _pruneSelection(PortalSettings st) {
    final pool =
        st.peersWithIpForSendUi().map((p) => p.ip.trim()).where((s) => s.isNotEmpty).toSet();
    _selectedSendIps.removeWhere((ip) => !pool.contains(ip));
    _activeGroupIds.removeWhere(
      (id) => !st.peerGroups.any((g) => g.id == id),
    );
  }

  Set<String> _validMemberIps(PortalSettings st, PeerGroupDto g) {
    final have = st.peers.map((p) => p.ip.trim()).where((x) => x.isNotEmpty).toSet();
    return g.memberIps.map((e) => e.trim()).where((e) => e.isNotEmpty && have.contains(e)).toSet();
  }

  void _activateGroup(PortalSettings st, PeerGroupDto g) {
    _activeGroupIds.add(g.id);
    _selectedSendIps.addAll(_validMemberIps(st, g));
  }

  void _deactivateGroup(PortalSettings st, PeerGroupDto g) {
    _activeGroupIds.remove(g.id);
    final mine = _validMemberIps(st, g);
    for (final ip in mine) {
      var inOther = false;
      for (final og in st.peerGroups) {
        if (og.id == g.id) continue;
        if (!_activeGroupIds.contains(og.id)) continue;
        if (_validMemberIps(st, og).contains(ip)) inOther = true;
      }
      if (!inOther) {
        _selectedSendIps.remove(ip);
      }
    }
  }

  Future<void> _setPinnedDefaultGroup(String? groupId) async {
    final prefs = await SharedPreferences.getInstance();
    if (groupId == null || groupId.isEmpty) {
      await prefs.remove(_kDefaultSendGroupId);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Сброшена основная группа для отправки')),
        );
      }
      return;
    }
    await prefs.setString(_kDefaultSendGroupId, groupId);
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Эта группа будет выбрана при следующем открытии «Отправить» (долгое нажатие снова — сменить)',
          ),
        ),
      );
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
    final pool = st.peersWithIpForSendUi();
    return pool.where((p) => _selectedSendIps.contains(p.ip.trim())).toList();
  }

  Future<bool> _ensureSecretAllowsSend(List<PeerDto> targets) async {
    final st = await SettingsRepository.load();
    if (PortalSecrets.sendSecretsLookConfigured(st, targets)) return true;
    if (!mounted) return false;
    final r = await showDialog<String>(
      context: context,
      barrierDismissible: false,
      builder: (ctx) => AlertDialog(
        title: const Text('Нужен пароль для отправки'),
        content: const Text(
          'Общий пароль пустой, а у выбранных пиров нет своего пароля в строке — '
          'ПК с паролем отклонит передачу.\n\n'
          'Укажи общий пароль в «Настроить» или свой у каждого пира в «Пиры».',
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
    final st0 = await SettingsRepository.load();
    final tg0 = _selectedTargets(st0);
    if (!await _ensureSecretAllowsSend(tg0)) return;

    final path = _filePath;
    if (path == null || !await File(path).exists()) {
      setState(() => _status = 'Выбери файл');
      return;
    }
    final st = await SettingsRepository.load();
    final tg = _selectedTargets(st);
    if (st.peersWithIpForSendUi().isEmpty) {
      setState(() => _status =
          'Нет адресов: добавь пиров во вкладке «Пиры».');
      return;
    }
    if (tg.isEmpty) {
      setState(() => _status =
          'Выбери группу (чип сверху) или отметь адреса в списке.');
      return;
    }

    setState(() {
      _busy = true;
      _status = 'Отправка...';
    });
    final ips = tg.map((e) => e.ip.trim()).toList();
    final errs = <String>[];
    for (final p in tg) {
      final sec = PortalSecrets.effectiveSecretForPeerIp(p.ip, st);
      final r = await sendFileToPeer(p.ip.trim(), path, secret: sec);
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
    final st0 = await SettingsRepository.load();
    final tg0 = _selectedTargets(st0);
    if (!await _ensureSecretAllowsSend(tg0)) return;

    final t = _text.text;
    if (t.trim().isEmpty) {
      setState(() => _status = 'Введи текст');
      return;
    }
    final st = await SettingsRepository.load();
    final tg = _selectedTargets(st);
    if (st.peersWithIpForSendUi().isEmpty) {
      setState(() => _status = 'Нет адресов — добавь пиров во вкладке «Пиры».');
      return;
    }
    if (tg.isEmpty) {
      setState(() => _status =
          'Выбери группу или отметь адреса в списке «Кому отправить».');
      return;
    }

    setState(() {
      _busy = true;
      _status = 'Отправка текста...';
    });
    final ips = tg.map((e) => e.ip.trim()).toList();
    final errs = <String>[];
    for (final p in tg) {
      final sec = PortalSecrets.effectiveSecretForPeerIp(p.ip, st);
      final r = await sendTextToPeer(p.ip.trim(), t, secret: sec);
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
    final tg = st.peersWithIpForSendUi();
    final groups = st.peerGroups;

    if (tg.isEmpty) {
      return Card(
        margin: EdgeInsets.zero,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Кому отправить',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: 6),
              Text(
                'Нет сохранённых адресов. Добавь их во вкладке «Пиры».',
                style: Theme.of(context).textTheme.bodyMedium,
              ),
            ],
          ),
        ),
      );
    }

    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.fromLTRB(8, 8, 8, 10),
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
                            final all =
                                tg.map((p) => p.ip.trim()).where((s) => s.isNotEmpty).toSet();
                            if (_selectedSendIps.length == all.length &&
                                all.isNotEmpty) {
                              _selectedSendIps.clear();
                              _activeGroupIds.clear();
                            } else {
                              _selectedSendIps
                                ..clear()
                                ..addAll(all);
                              _activeGroupIds.clear();
                            }
                          });
                        },
                  child: Text(
                    () {
                      final all = tg.map((p) => p.ip.trim()).where((s) => s.isNotEmpty).toSet();
                      return _selectedSendIps.length == all.length && all.isNotEmpty
                          ? 'Снять все'
                          : 'Все адреса';
                    }(),
                  ),
                ),
                IconButton(
                  tooltip: 'Обновить список',
                  onPressed: _busy ? null : _reloadSettings,
                  icon: const Icon(Icons.refresh, size: 20),
                ),
              ],
            ),
            if (groups.isNotEmpty) ...[
              Text(
                'Группы (нажми — включить/выключить все адреса группы). Долгое нажатие — сделать основной при следующем входе.',
                style: Theme.of(context).textTheme.bodySmall,
              ),
              const SizedBox(height: 6),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: groups.map((g) {
                  final active = _activeGroupIds.contains(g.id);
                  final label = g.name.trim().isEmpty ? 'Группа' : g.name.trim();
                  return GestureDetector(
                    onLongPress: _busy
                        ? null
                        : () => _setPinnedDefaultGroup(g.id),
                    child: FilterChip(
                      label: Text(label),
                      selected: active,
                      showCheckmark: true,
                      visualDensity: VisualDensity.compact,
                      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      onSelected: _busy
                          ? null
                          : (v) {
                              setState(() {
                                _sendSelectionTouched = true;
                                if (v) {
                                  _activateGroup(st, g);
                                } else {
                                  _deactivateGroup(st, g);
                                }
                              });
                            },
                    ),
                  );
                }).toList(),
              ),
              TextButton(
                onPressed: _busy
                    ? null
                    : () => _setPinnedDefaultGroup(null),
                child: const Text('Сбросить «основную группу»'),
              ),
              const SizedBox(height: 4),
            ],
            Text(
              'Адреса',
              style: Theme.of(context).textTheme.labelLarge,
            ),
            const SizedBox(height: 2),
            ConstrainedBox(
              constraints: BoxConstraints(
                maxHeight: (tg.length * 40.0).clamp(96.0, 200.0),
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
                      size: 20,
                    ),
                    title: Text(
                      p.name.isNotEmpty ? p.name : ip,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodyMedium,
                    ),
                    subtitle: Text(
                      ip,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: Theme.of(context).textTheme.bodySmall,
                    ),
                    controlAffinity: ListTileControlAffinity.leading,
                    dense: true,
                    visualDensity: VisualDensity.compact,
                    contentPadding: const EdgeInsets.symmetric(horizontal: 4),
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
                const SizedBox(height: 10),
                if (st != null)
                  _buildTargetsCard(st)
                else
                  const LinearProgressIndicator(),
                const SizedBox(height: 16),
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
        ],
      ),
    );
  }
}
