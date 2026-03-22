import 'package:flutter/material.dart';
import 'package:portal_flutter/services/portal_notifications.dart';
import 'package:portal_flutter/services/portal_service_controller.dart';
import 'package:portal_flutter/ui/main_scaffold.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await PortalNotifications.init();
  await PortalServiceController.initialize();
  runApp(const PortalApp());
}

class PortalApp extends StatelessWidget {
  const PortalApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Portal',
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(seedColor: Colors.deepPurple),
        useMaterial3: true,
      ),
      home: const MainScaffold(),
    );
  }
}
