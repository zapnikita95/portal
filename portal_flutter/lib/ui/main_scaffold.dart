import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:receive_sharing_intent/receive_sharing_intent.dart';
import 'package:portal_flutter/services/portal_service_controller.dart';

import 'pending_share.dart';
import 'screens/history_screen.dart';
import 'screens/home_receive_screen.dart';
import 'screens/peers_screen.dart';
import 'screens/send_screen.dart';
import 'screens/settings_screen.dart';
import 'widgets/portal_tab_icons.dart';
import 'package:portal_flutter/services/app_update_hint.dart';

class MainScaffold extends StatefulWidget {
  const MainScaffold({super.key});

  @override
  State<MainScaffold> createState() => _MainScaffoldState();
}

class _MainScaffoldState extends State<MainScaffold>
    with WidgetsBindingObserver {
  int _index = 0;
  StreamSubscription<List<SharedMediaFile>>? _shareSub;
  bool _iosResumeHintShown = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _initShare();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    super.didChangeAppLifecycleState(state);
    if (state != AppLifecycleState.resumed) return;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      maybeShowUpdateHint(context);
    });
    if (!Platform.isIOS || !PortalServiceController.iosRunning) return;
    if (_iosResumeHintShown || !mounted) return;
    _iosResumeHintShown = true;
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'iOS: для приёма с ПК держи Portal открытым на экране. '
            'В фоне система обычно не принимает TCP.',
          ),
          duration: Duration(seconds: 6),
        ),
      );
    });
  }

  Future<void> _initShare() async {
    try {
      final initial = await ReceiveSharingIntent.instance.getInitialMedia();
      _applyShare(initial);
      await ReceiveSharingIntent.instance.reset();
    } catch (_) {}
    _shareSub =
        ReceiveSharingIntent.instance.getMediaStream().listen(_applyShare);
  }

  void _applyShare(List<SharedMediaFile> files) {
    final paths = <String>[];
    for (final f in files) {
      final p = f.path;
      if (p.isNotEmpty && File(p).existsSync()) paths.add(p);
    }
    if (paths.isEmpty) return;
    pendingSharePaths.value = paths;
    setState(() => _index = 2);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    _shareSub?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      const HomeReceiveScreen(),
      const PeersScreen(),
      const SendScreen(),
      const HistoryScreen(),
      const SettingsScreen(),
    ];
    return Scaffold(
      body: pages[_index],
      bottomNavigationBar: NavigationBar(
        selectedIndex: _index,
        onDestinationSelected: (i) => setState(() => _index = i),
        destinations: const <NavigationDestination>[
          NavigationDestination(
            icon: PortalTabIcon(
                kind: PortalTabKind.receive, selected: false),
            selectedIcon: PortalTabIcon(
                kind: PortalTabKind.receive, selected: true),
            label: 'Приём',
          ),
          NavigationDestination(
            icon: PortalTabIcon(
                kind: PortalTabKind.peers, selected: false),
            selectedIcon: PortalTabIcon(
                kind: PortalTabKind.peers, selected: true),
            label: 'Пиры',
          ),
          NavigationDestination(
            icon: PortalTabIcon(
                kind: PortalTabKind.send, selected: false),
            selectedIcon: PortalTabIcon(
                kind: PortalTabKind.send, selected: true),
            label: 'Отпр.',
          ),
          NavigationDestination(
            icon: PortalTabIcon(
                kind: PortalTabKind.history, selected: false),
            selectedIcon: PortalTabIcon(
                kind: PortalTabKind.history, selected: true),
            label: 'История',
          ),
          NavigationDestination(
            icon: PortalTabIcon(
                kind: PortalTabKind.settings, selected: false),
            selectedIcon: PortalTabIcon(
                kind: PortalTabKind.settings, selected: true),
            label: 'Настр.',
          ),
        ],
      ),
    );
  }
}
