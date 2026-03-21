import 'package:flutter/material.dart';
import 'package:portal_flutter/config.dart';
import 'package:portal_flutter/services/portal_client.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  final _ip = TextEditingController(text: '100.');
  final _secret = TextEditingController();
  String _status = 'Введи IP и нажми Ping';
  bool _busy = false;

  @override
  void dispose() {
    _ip.dispose();
    _secret.dispose();
    super.dispose();
  }

  Future<void> _doPing() async {
    setState(() {
      _busy = true;
      _status = 'Проверка...';
    });
    final ok = await pingPortal(
      _ip.text,
      secret: _secret.text,
    );
    if (!mounted) return;
    setState(() {
      _busy = false;
      _status = ok
          ? 'Ответ Portal (pong) на :$portalPort'
          : 'Нет ответа или не Portal. Проверь IP, VPN, пароль.';
    });
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Portal'),
        backgroundColor: Theme.of(context).colorScheme.inversePrimary,
      ),
      body: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'Flutter-клиент (MVP): проверка связи с ПК по протоколу Portal.',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 16),
            TextField(
              controller: _ip,
              decoration: const InputDecoration(
                labelText: 'IP компьютера (Tailscale / LAN)',
                border: OutlineInputBorder(),
              ),
              keyboardType: TextInputType.url,
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _secret,
              decoration: const InputDecoration(
                labelText: 'Пароль сети (если задан на ПК)',
                border: OutlineInputBorder(),
              ),
              obscureText: true,
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: _busy ? null : _doPing,
              icon: _busy
                  ? const SizedBox(
                      width: 20,
                      height: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Icon(Icons.wifi_tethering),
              label: const Text('Ping Portal'),
            ),
            const SizedBox(height: 20),
            Text(
              _status,
              style: Theme.of(context).textTheme.bodyLarge,
            ),
            const Spacer(),
            Text(
              'Дальше: отправка файла/текста (JSON + поток байт), список пиров, история.',
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: Theme.of(context).colorScheme.outline,
                  ),
            ),
          ],
        ),
      ),
    );
  }
}
