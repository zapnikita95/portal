import 'dart:io';

import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:portal_flutter/data/settings_repository.dart';
import 'package:portal_flutter/services/portal_service_controller.dart';
import 'package:portal_flutter/util/receive_paths.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _secret = TextEditingController();
  final _mdnsDisplay = TextEditingController();
  final _recvDir = TextEditingController();
  bool _loading = true;
  String _animPreset = 'pulse';

  static const _animLabels = <String, String>{
    'branding': 'GIF portal_main (как на ПК)',
    'pulse': 'Пульс (вектор)',
    'static': 'Статичный портал',
    'rings': 'Кольца / орбита',
  };

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final st = await SettingsRepository.load();
    _secret.text = st.secret;
    _mdnsDisplay.text = st.mdnsDisplayName;
    _recvDir.text = st.receiveDir;
    final a = st.portalAnimPreset.trim().toLowerCase();
    _animPreset = _animLabels.containsKey(a) ? a : 'branding';
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _pickFolder() async {
    try {
      final d = await FilePicker.platform.getDirectoryPath();
      if (d != null && mounted) {
        setState(() => _recvDir.text = d);
      }
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Папка: $e')),
      );
    }
  }

  Future<void> _save() async {
    final dir = _recvDir.text.trim();
    if (Platform.isAndroid && dir.isNotEmpty) {
      final v = await validateReceiveDirWritable(dir);
      if (!v.$1) {
        if (!mounted) return;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Папка приёма: ${v.$2}\n'
              'С фона Android часто нельзя писать в выбранную папку. '
              'Оставь поле пустым — файл попадёт в приложение и копию в «Загрузки/Portal».',
            ),
            duration: const Duration(seconds: 10),
          ),
        );
        return;
      }
    }
    final st = await SettingsRepository.load();
    await SettingsRepository.save(PortalSettings(
      peers: st.peers,
      secret: _secret.text.trim(),
      receiveDir: _recvDir.text.trim(),
      portalAnimPreset: _animPreset,
      peerGroups: st.peerGroups,
      lanScanMode: st.lanScanMode,
      lanSeedHintIp: st.lanSeedHintIp,
      mdnsDisplayName: _mdnsDisplay.text.trim(),
    ));
    await PortalServiceController.reloadReceiveIfRunning();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text(
          'Сохранено. Приём перезапущен, если был включён (Android / iOS).',
        ),
      ),
    );
  }

  @override
  void dispose() {
    _secret.dispose();
    _mdnsDisplay.dispose();
    _recvDir.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return const Center(child: CircularProgressIndicator());
    }
    return SafeArea(
      child: ListView(
        keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
        padding: const EdgeInsets.all(20),
        children: [
          Text('Настроить', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 16),
          TextField(
            controller: _secret,
            decoration: const InputDecoration(
              labelText: 'Общий пароль Portal (как на ПК, config.json)',
              border: OutlineInputBorder(),
              helperText:
                  'Подставляется для пиров без своего пароля. Чтобы не «делиться одной сетью»: '
                  'оставь здесь пусто и задай пароль у каждого IP в «Пиры» (или при добавлении со скана). '
                  'Приём принимает любой из заданных паролей.',
            ),
            obscureText: true,
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _mdnsDisplay,
            decoration: const InputDecoration(
              labelText: 'Имя телефона в LAN (mDNS)',
              border: OutlineInputBorder(),
              helperText:
                  'Видно другим в «Найти в LAN», пока включён приём. Пусто — «Portal-iPhone» / «Portal-Android». '
                  'Тот же смысл, что «Имя в LAN» на ПК (config.json: portal_mdns_display_name).',
            ),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _recvDir,
            decoration: const InputDecoration(
              labelText: 'Папка приёма',
              border: OutlineInputBorder(),
              helperText:
                  'Пусто: приём в папку приложения + копия в «Загрузки/Portal» (Android). '
                  'Своя папка: не всегда работает из фона — проверяется при сохранении.',
            ),
          ),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              onPressed: _pickFolder,
              icon: const Icon(Icons.folder_open),
              label: const Text('Выбрать папку…'),
            ),
          ),
          const SizedBox(height: 20),
          Text(
            'Анимация на экране «Приём»',
            style: Theme.of(context).textTheme.titleSmall,
          ),
          const SizedBox(height: 8),
          DropdownButtonFormField<String>(
            value: _animPreset,
            decoration: const InputDecoration(
              border: OutlineInputBorder(),
            ),
            items: _animLabels.entries
                .map(
                  (e) => DropdownMenuItem(value: e.key, child: Text(e.value)),
                )
                .toList(),
            onChanged: (v) {
              if (v != null) setState(() => _animPreset = v);
            },
          ),
          const SizedBox(height: 24),
          FilledButton(onPressed: _save, child: const Text('Сохранить')),
          const SizedBox(height: 16),
          Text(
            'Flutter-версия — основной мобильный клиент Portal.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}
