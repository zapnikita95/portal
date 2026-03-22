import 'dart:async';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:receive_sharing_intent/receive_sharing_intent.dart';

import 'pending_share.dart';
import 'screens/history_screen.dart';
import 'screens/home_receive_screen.dart';
import 'screens/peers_screen.dart';
import 'screens/send_screen.dart';
import 'screens/settings_screen.dart';

class MainScaffold extends StatefulWidget {
  const MainScaffold({super.key});

  @override
  State<MainScaffold> createState() => _MainScaffoldState();
}

class _MainScaffoldState extends State<MainScaffold> {
  int _index = 0;
  StreamSubscription<List<SharedMediaFile>>? _shareSub;

  @override
  void initState() {
    super.initState();
    _initShare();
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
        destinations: const [
          NavigationDestination(icon: Icon(Icons.download), label: 'Приём'),
          NavigationDestination(icon: Icon(Icons.people), label: 'Пиры'),
          NavigationDestination(icon: Icon(Icons.upload), label: 'Отпр.'),
          NavigationDestination(icon: Icon(Icons.history), label: 'История'),
          NavigationDestination(icon: Icon(Icons.settings), label: 'Настр.'),
        ],
      ),
    );
  }
}
