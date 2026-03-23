import 'package:portal_flutter/data/settings_repository.dart';

/// Логика нескольких паролей: общий в настройках + свой у каждого пира.
class PortalSecrets {
  PortalSecrets._();

  /// Уникальные непустые секреты в стабильном порядке: сначала общий, затем по списку пиров.
  static List<String> orderedCandidateSecrets(PortalSettings st) {
    final out = <String>[];
    final seen = <String>{};
    void add(String s) {
      final t = s.trim();
      if (t.isEmpty || seen.contains(t)) return;
      seen.add(t);
      out.add(t);
    }

    add(st.secret);
    for (final p in st.peers) {
      add(p.peerSecret);
    }
    return out;
  }

  /// Для приёма на телефоне: **пустой набор** = не проверять secret (как раньше при пустом общем пароле).
  static Set<String> acceptedSecretsForReceive(PortalSettings st) {
    final out = <String>{};
    final g = st.secret.trim();
    if (g.isNotEmpty) out.add(g);
    for (final p in st.peers) {
      final s = p.peerSecret.trim();
      if (s.isNotEmpty) out.add(s);
    }
    return out;
  }

  /// Секрет для отправки на конкретный IP: свой у пира или общий.
  static String effectiveSecretForPeerIp(String ip, PortalSettings st) {
    final want = ip.trim();
    for (final p in st.peers) {
      if (p.ip.trim() == want) {
        final ps = p.peerSecret.trim();
        if (ps.isNotEmpty) return ps;
        break;
      }
    }
    return st.secret.trim();
  }

  /// Достаточно ли данных для отправки на выбранных пиров (без общего пароля).
  static bool sendSecretsLookConfigured(
    PortalSettings st,
    List<PeerDto> targets,
  ) {
    if (st.secret.trim().isNotEmpty) return true;
    if (targets.isEmpty) return false;
    for (final p in targets) {
      if (p.peerSecret.trim().isEmpty) return false;
    }
    return true;
  }
}
