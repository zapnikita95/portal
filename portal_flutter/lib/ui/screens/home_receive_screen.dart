import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_background_service/flutter_background_service.dart';
import 'package:portal_flutter/config.dart';
import 'package:portal_flutter/data/settings_repository.dart';
import 'package:portal_flutter/portal/protocol_client.dart';
import 'package:portal_flutter/services/portal_service_controller.dart';
import 'package:portal_flutter/ui/widgets/portal_receive_animation.dart';

class HomeReceiveScreen extends StatefulWidget {
  const HomeReceiveScreen({super.key});

  @override
  State<HomeReceiveScreen> createState() => _HomeReceiveScreenState();
}

class _HomeReceiveScreenState extends State<HomeReceiveScreen>
    with WidgetsBindingObserver {
  bool _localReceiveOn = false;
  bool _busy = false;
  String _log = '';
  StreamSubscription? _sub;
  String _animPreset = 'branding';
  Timer? _heartbeat;
  String _pcReachability = '—';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _loadAnim();
    _refreshAll();
    _heartbeat = Timer.periodic(const Duration(seconds: 6), (_) {
      if (!mounted) return;
      _refreshAll();
    });
    if (Platform.isAndroid) {
      try {
        _sub = FlutterBackgroundService().on('log').listen((Object? ev) {
          if (!mounted) return;
          if (ev is! Map) return;
          final m = Map<String, dynamic>.from(ev);
          final t = m['t'];
          if (t != null) {
            setState(() => _log = t.toString());
          }
        });
      } catch (_) {}
    }
  }

  Future<void> _loadAnim() async {
    final st = await SettingsRepository.load();
    if (!mounted) return;
    setState(() => _animPreset = st.portalAnimPreset);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      _loadAnim();
      _refreshAll();
    }
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _heartbeat?.cancel();
    _sub?.cancel();
    super.dispose();
  }

  Future<void> _refreshLocalReceive() async {
    if (Platform.isAndroid) {
      final r = await PortalServiceController.androidRunning();
      if (mounted) setState(() => _localReceiveOn = r);
    } else {
      if (mounted) {
        setState(() => _localReceiveOn = PortalServiceController.iosRunning);
      }
    }
  }

  /// Проверка ПК по сохранённым IP (в т.ч. Tailscale 100.x) — не путать с локальным FGS.
  Future<void> _probePeersReachability() async {
    final st = await SettingsRepository.load();
    final ips = st.peers.map((p) => p.ip.trim()).where((s) => s.isNotEmpty).toList();
    if (ips.isEmpty) {
      if (mounted) {
        setState(() => _pcReachability = 'Нет IP в «Пиры» — добавь адрес ПК.');
      }
      return;
    }
    ips.sort((a, b) {
      final ta = a.startsWith('100.') ? 0 : 1;
      final tb = b.startsWith('100.') ? 0 : 1;
      if (ta != tb) return ta.compareTo(tb);
      return a.compareTo(b);
    });
    // Не ддосим десятки IP каждые 6 с — проверяем приоритетные (Tailscale первыми).
    for (final ip in ips.take(6)) {
      final ok = await pingPortal(ip, secret: st.secret);
      if (!mounted) return;
      if (ok) {
        setState(() => _pcReachability = 'ПК $ip отвечает (pong по :$portalPort)');
        return;
      }
    }
    if (mounted) {
      setState(() {
        _pcReachability =
            'Нет pong (${ips.take(3).join(', ')}…). ПК: «Запустить портал», пароль, mesh-VPN/файрвол.';
      });
    }
  }

  Future<void> _refreshAll() async {
    await _refreshLocalReceive();
    await _probePeersReachability();
  }

  Future<void> _toggle(bool v) async {
    if (v) {
      final st = await SettingsRepository.load();
      if (st.secret.trim().isEmpty && mounted) {
        final go = await showDialog<bool>(
          context: context,
          barrierDismissible: false,
          builder: (ctx) => AlertDialog(
            icon: const Icon(Icons.warning_amber_rounded, size: 40),
            title: const Text('Пароль сети не задан'),
            content: const SingleChildScrollView(
              child: Text(
                'В настройках приложения поле «Пароль сети» пустое.\n\n'
                'Если на компьютере в config.json указан пароль — приём будет '
                'молча отклоняться (ПК считает соединение неавторизованным), '
                'и отдельного уведомления может не быть.\n\n'
                'Задай тот же пароль, что на ПК, или оставь пустым везде.',
              ),
            ),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(ctx, false),
                child: const Text('Отмена'),
              ),
              FilledButton(
                onPressed: () => Navigator.pop(ctx, true),
                child: const Text('Всё равно включить приём'),
              ),
            ],
          ),
        );
        if (go != true) return;
      }
    }
    setState(() => _busy = true);
    try {
      if (v) {
        await PortalServiceController.startReceiveForPlatform();
      } else {
        await PortalServiceController.stopReceiveForPlatform();
      }
      await Future<void>.delayed(const Duration(milliseconds: 200));
      await _refreshAll();
    } catch (e, st) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(
              'Не удалось ${v ? 'включить' : 'выключить'} приём: $e',
            ),
            duration: const Duration(seconds: 8),
          ),
        );
        assert(() {
          // ignore: avoid_print
          print('Portal receive toggle: $e\n$st');
          return true;
        }());
      }
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        'Portal',
                        style: Theme.of(context).textTheme.headlineMedium,
                      ),
                      const SizedBox(height: 8),
                      Text(
                        Platform.isIOS
                            ? 'Приём на этом телефоне :$portalPort (пока приложение на экране). '
                                'Статус «ПК отвечает» ниже — отдельная проверка до Mac по IP из «Пиры».'
                            : 'Приём на этом телефоне в фоне (FGS). '
                                '«ПК отвечает» — ping по IP из «Пиры» (LAN или mesh-VPN 100.x).',
                        style: Theme.of(context).textTheme.bodyMedium,
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 12),
                PortalReceiveAnimation(
                  active: _localReceiveOn,
                  preset: _animPreset,
                  size: 100,
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              'ПК в сети',
              style: Theme.of(context).textTheme.titleSmall,
            ),
            const SizedBox(height: 4),
            Text(
              _pcReachability,
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 16),
            SwitchListTile(
              title: const Text('Принимать файлы с ПК на этом устройстве'),
              subtitle: Text(
                'Локальный сервер :$portalPort — ${_localReceiveOn ? 'вкл' : 'выкл'}',
              ),
              value: _localReceiveOn,
              onChanged: _busy ? null : _toggle,
            ),
            if (_busy) const LinearProgressIndicator(),
            const SizedBox(height: 24),
            Text(
              'Последнее событие',
              style: Theme.of(context).textTheme.titleSmall,
            ),
            const SizedBox(height: 8),
            Expanded(
              child: SingleChildScrollView(
                keyboardDismissBehavior:
                    ScrollViewKeyboardDismissBehavior.onDrag,
                child: Text(
                  _log.isEmpty ? '—' : _log,
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
