import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';
import 'package:package_info_plus/package_info_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

import 'package:portal_flutter/ui/portal_onboarding.dart';

const _kLastCheckMs = 'portal_update_last_check_ms';
const _kDismissedTag = 'portal_update_dismissed_tag';

/// Раз в ~3 суток: сравнить semver с тегом latest GitHub release (общий репозиторий).
Future<void> maybeShowUpdateHint(BuildContext context) async {
  if (!context.mounted) return;
  final prefs = await SharedPreferences.getInstance();
  final now = DateTime.now().millisecondsSinceEpoch;
  final last = prefs.getInt(_kLastCheckMs) ?? 0;
  if (now - last < const Duration(days: 3).inMilliseconds) return;

  await prefs.setInt(_kLastCheckMs, now);

  final info = await PackageInfo.fromPlatform();
  final current = info.version;

  Map<String, dynamic>? rel;
  try {
    final uri = Uri.parse(
      'https://api.github.com/repos/zapnikita95/portal/releases/latest',
    );
    final client = HttpClient();
    final req = await client.getUrl(uri);
    req.headers.set('Accept', 'application/vnd.github+json');
    req.headers.set('User-Agent', 'PortalFlutter/${info.version}');
    final res = await req.close();
    final body = await res.transform(utf8.decoder).join();
    client.close();
    if (res.statusCode != 200) return;
    final j = jsonDecode(body);
    if (j is Map<String, dynamic>) rel = j;
  } catch (_) {
    return;
  }
  if (rel == null || !context.mounted) return;

  final tag = (rel['tag_name'] as String?)?.trim() ?? '';
  if (tag.isEmpty) return;
  if (prefs.getString(_kDismissedTag) == tag) return;

  if (!_semverNewer(tag, current)) return;

  if (!context.mounted) return;
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(
        'На GitHub новее: $tag (у тебя $current). Открыть страницу загрузки?',
      ),
      duration: const Duration(seconds: 12),
      action: SnackBarAction(
        label: 'Релизы',
        onPressed: () async {
          final u = Uri.parse(kPortalReleasesUrl);
          if (await canLaunchUrl(u)) {
            await launchUrl(u, mode: LaunchMode.externalApplication);
          }
          await prefs.setString(_kDismissedTag, tag);
        },
      ),
    ),
  );
}

bool _semverNewer(String tagA, String plainB) {
  List<int> p(String s) {
    final t = s.replaceFirst(RegExp(r'^[vV]'), '');
    return t
        .split('.')
        .map((x) => int.tryParse(RegExp(r'\d+').stringMatch(x) ?? '') ?? 0)
        .toList();
  }

  final a = p(tagA);
  final b = p(plainB);
  final n = a.length > b.length ? a.length : b.length;
  for (var i = 0; i < n; i++) {
    final av = i < a.length ? a[i] : 0;
    final bv = i < b.length ? b[i] : 0;
    if (av > bv) return true;
    if (av < bv) return false;
  }
  return false;
}
