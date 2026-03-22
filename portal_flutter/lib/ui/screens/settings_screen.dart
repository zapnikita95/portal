import 'package:flutter/material.dart';
import 'package:portal_flutter/data/settings_repository.dart';
import 'package:portal_flutter/services/portal_service_controller.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  final _secret = TextEditingController();
  final _recvDir = TextEditingController();
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final st = await SettingsRepository.load();
    _secret.text = st.secret;
    _recvDir.text = st.receiveDir;
    if (mounted) setState(() => _loading = false);
  }

  Future<void> _save() async {
    final st = await SettingsRepository.load();
    await SettingsRepository.save(PortalSettings(
      peers: st.peers,
      secret: _secret.text.trim(),
      receiveDir: _recvDir.text.trim(),
    ));
    await PortalServiceController.reloadAndroidReceive();
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(content: Text('Сохранено. Приём на Android перезапущен, если был вкл.')),
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
        padding: const EdgeInsets.all(20),
        children: [
          Text('Настройки', style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: 16),
          TextField(
            controller: _secret,
            decoration: const InputDecoration(
              labelText: 'Пароль сети (как на ПК)',
              border: OutlineInputBorder(),
            ),
            obscureText: true,
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _recvDir,
            decoration: const InputDecoration(
              labelText: 'Папка приёма (пусто = Documents/PortalReceive)',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 24),
          FilledButton(onPressed: _save, child: const Text('Сохранить')),
          const SizedBox(height: 16),
          Text(
            'Flutter-версия — основной мобильный клиент Portal. Kivy APK можно не ставить.',
            style: Theme.of(context).textTheme.bodySmall,
          ),
        ],
      ),
    );
  }
}
