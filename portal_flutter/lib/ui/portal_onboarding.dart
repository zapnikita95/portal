import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

const _kOnboardingDismissedKey = 'portal_onboarding_v1_dismissed';

/// Совпадает с portal_config.DEFAULT_GITHUB_REPO по умолчанию.
const String kPortalReleasesUrl = 'https://github.com/zapnikita95/portal/releases';

/// Однократная подсказка для новых пользователей (сбрасывается только переустановкой / очисткой данных).
Future<void> showPortalOnboardingIfNeeded(BuildContext context) async {
  final prefs = await SharedPreferences.getInstance();
  if (prefs.getBool(_kOnboardingDismissedKey) == true) return;
  if (!context.mounted) return;

  await showDialog<void>(
    context: context,
    barrierDismissible: true,
    builder: (ctx) {
      return AlertDialog(
        title: const Text('Быстрый старт'),
        content: const SingleChildScrollView(
          child: Text(
            '• Установи Портал на компьютере и телефоне — сборки в релизах на GitHub.\n'
            '• Задай один и тот же «пароль сети» в приложении и на ПК.\n'
            '• Устройства должны видеть друг друга: одна Wi‑Fi сеть или Tailscale.\n'
            '• Включи приём/фоновый сервис, добавь IP пира (как на ПК в настройках).\n\n'
            'На iOS для приёма с ПК часто нужно держать приложение открытым — система режет фоновый TCP.',
          ),
        ),
        actions: [
          TextButton(
            onPressed: () async {
              final uri = Uri.parse(kPortalReleasesUrl);
              if (await canLaunchUrl(uri)) {
                await launchUrl(uri, mode: LaunchMode.externalApplication);
              }
            },
            child: const Text('Открыть релизы'),
          ),
          FilledButton(
            onPressed: () async {
              await prefs.setBool(_kOnboardingDismissedKey, true);
              if (ctx.mounted) Navigator.of(ctx).pop();
            },
            child: const Text('Понятно'),
          ),
        ],
      );
    },
  );
}
