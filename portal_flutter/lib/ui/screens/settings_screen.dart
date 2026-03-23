import 'package:file_picker/file_picker.dart';
import 'package:flutter/material.dart';
import 'package:portal_flutter/data/settings_repository.dart';
import 'package:portal_flutter/services/portal_service_controller.dart';
import 'package:portal_flutter/ui/portal_onboarding.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _secret = TextEditingController();
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
    final st = await SettingsRepository.load();
    await SettingsRepository.save(PortalSettings(
      peers: st.peers,
      secret: _secret.text.trim(),
      receiveDir: _recvDir.text.trim(),
      portalAnimPreset: _animPreset,
      peerGroups: st.peerGroups,
      lanScanMode: st.lanScanMode,
      lanSeedHintIp: st.lanSeedHintIp,
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
              labelText: 'Пароль сети (как на ПК, config.json)',
              border: OutlineInputBorder(),
              helperText:
                  'Должен совпадать с паролем настольного Portal — иначе ping и приём отклонятся.',
            ),
            obscureText: true,
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _recvDir,
            decoration: const InputDecoration(
              labelText: 'Папка приёма',
              border: OutlineInputBorder(),
              helperText:
                  'Пусто: Android — Android/data/…/files/PortalReceive; iOS — Documents/PortalReceive',
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
          const SizedBox(height: 20),
          ListTile(
            leading: const Icon(Icons.help_outline),
            title: const Text('Быстрый старт'),
            subtitle: const Text('Установка, Wi‑Fi / mesh-VPN, пароль, LAN-скан'),
            onTap: () => showPortalQuickStartSheet(context),
          ),
          const SizedBox(height: 8),
          Text(
            'Flutter-версия — основной мобильный клиент Portal.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}
