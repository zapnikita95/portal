import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

/// Совпадает с portal_config.DEFAULT_GITHUB_REPO по умолчанию.
const String kPortalReleasesUrl = 'https://github.com/zapnikita95/portal/releases';

/// Справка «Быстрый старт» — только из ⚙️ Настройки (не всплывает на главной).
Future<void> showPortalQuickStartSheet(BuildContext context) async {
  final cs = Theme.of(context).colorScheme;
  await showModalBottomSheet<void>(
    context: context,
    isScrollControlled: true,
    showDragHandle: true,
    backgroundColor: cs.surfaceContainerHighest,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
    ),
    builder: (ctx) {
      return Padding(
        padding: EdgeInsets.only(
          left: 20,
          right: 20,
          top: 8,
          bottom: MediaQuery.paddingOf(ctx).bottom + 20,
        ),
        child: SingleChildScrollView(
          keyboardDismissBehavior:
              ScrollViewKeyboardDismissBehavior.onDrag,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                'Быстрый старт',
                style: Theme.of(ctx).textTheme.titleLarge?.copyWith(
                      color: cs.onSurface,
                      fontWeight: FontWeight.w600,
                    ),
              ),
              const SizedBox(height: 12),
              Text(
                '• Установи Портал на компьютере и телефоне — сборки в релизах на GitHub.\n'
                '• Задай один и тот же «пароль сети» в приложении и на ПК (config.json).\n'
                '• Устройства должны видеть друг друга: одна Wi‑Fi сеть и/или Tailscale.\n'
                '• На вкладке «Пиры» выбери режим LAN-скана: Wi‑Fi (192.168.x) или Tailscale (100.x).\n'
                '• Включи приём / фоновый сервис, добавь IP пира.\n\n'
                'На iOS для приёма с ПК часто нужно держать приложение на экране — система режет фоновый TCP.',
                style: Theme.of(ctx).textTheme.bodyMedium?.copyWith(
                      color: cs.onSurface,
                      height: 1.45,
                    ),
              ),
              const SizedBox(height: 20),
              FilledButton.icon(
                onPressed: () async {
                  final uri = Uri.parse(kPortalReleasesUrl);
                  if (await canLaunchUrl(uri)) {
                    await launchUrl(uri, mode: LaunchMode.externalApplication);
                  }
                },
                icon: const Icon(Icons.download_outlined),
                label: const Text('Открыть релизы (скачать)'),
              ),
              const SizedBox(height: 10),
              TextButton(
                onPressed: () => Navigator.of(ctx).pop(),
                child: const Text('Закрыть'),
              ),
            ],
          ),
        ),
      );
    },
  );
}
