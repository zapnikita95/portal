import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_background_service/flutter_background_service.dart';
import 'package:portal_flutter/config.dart';
import 'package:portal_flutter/services/portal_service_controller.dart';

class HomeReceiveScreen extends StatefulWidget {
  const HomeReceiveScreen({super.key});

  @override
  State<HomeReceiveScreen> createState() => _HomeReceiveScreenState();
}

class _HomeReceiveScreenState extends State<HomeReceiveScreen> {
  bool _on = false;
  bool _busy = false;
  String _log = '';
  StreamSubscription? _sub;

  @override
  void initState() {
    super.initState();
    _refresh();
    if (Platform.isAndroid) {
      _sub = FlutterBackgroundService().on('log').listen((Object? ev) {
        if (!mounted) return;
        if (ev is! Map) return;
        final m = Map<String, dynamic>.from(ev);
        final t = m['t'];
        if (t != null) {
          setState(() => _log = t.toString());
        }
      });
    }
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  Future<void> _refresh() async {
    if (Platform.isAndroid) {
      final r = await PortalServiceController.androidRunning();
      if (mounted) setState(() => _on = r);
    } else {
      if (mounted) {
        setState(() => _on = PortalServiceController.iosRunning);
      }
    }
  }

  Future<void> _toggle(bool v) async {
    setState(() => _busy = true);
    try {
      if (v) {
        await PortalServiceController.startReceiveForPlatform();
      } else {
        await PortalServiceController.stopReceiveForPlatform();
      }
      await _refresh();
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
            Text(
              'Portal',
              style: Theme.of(context).textTheme.headlineMedium,
            ),
            const SizedBox(height: 8),
            Text(
              Platform.isIOS
                  ? 'iOS: приём :$portalPort, пока Portal на экране. Уведомление при каждом приёме. '
                      'В фоне TCP недоступен (ограничение ОС) — для постоянного приёма используй Android.'
                  : 'Android: foreground service держит приём в фоне; уведомление обновляется при каждом файле/тексте.',
              style: Theme.of(context).textTheme.bodyMedium,
            ),
            const SizedBox(height: 24),
            SwitchListTile(
              title: const Text('Принимать файлы с ПК'),
              subtitle: const Text('Порт $portalPort'),
              value: _on,
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
