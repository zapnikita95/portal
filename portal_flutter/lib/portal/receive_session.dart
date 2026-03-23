import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:typed_data';

import 'package:path/path.dart' as p;
import 'package:portal_android_downloads/portal_android_downloads.dart';
import 'package:portal_flutter/data/history_repository.dart';

import 'framing.dart';

/// Сохраняем кириллицу и пробелы (Android нормально держит UTF‑8 имена).
/// Раньше `[^\w]` превращал «тест снимок.png» в мусор вроде `__123.png`.
String _safeName(String name) {
  var n = name.trim().isEmpty ? 'file' : name.trim();
  n = n.replaceAll('\\', '/');
  final parts = n.split('/');
  n = parts.isNotEmpty ? parts.last : n;
  n = n.replaceAll(RegExp(r'[\x00\r\n]'), '');
  n = n.replaceAll(RegExp(r'[<>:"|?*]'), '_');
  n = n.trim();
  if (n.isEmpty || n == '.' || n == '..') {
    n = 'file_${DateTime.now().millisecondsSinceEpoch}';
  }
  return n.length > 200 ? n.substring(0, 200) : n;
}

/// Убрать ведущие \\n/\\r у тела файла (как portal_json_framing.strip_leading_tcp_json_delimiter).
Uint8List _stripLeadingBodyNoise(Uint8List raw) {
  var i = 0;
  while (i < raw.length &&
      (raw[i] == 9 || raw[i] == 10 || raw[i] == 13 || raw[i] == 32)) {
    i++;
  }
  if (i == 0) return raw;
  if (i >= raw.length) return Uint8List(0);
  return Uint8List.sublistView(raw, i);
}

/// Один последовательный читатель сокета — нельзя многократно вешать `.first` на Socket.
Future<void> handlePortalSocket(
  Socket socket, {
  required String receiveDir,
  required String secret,
  required Future<void> Function(String kind, String message, String? localPath)
      onEvent,
}) async {
  final peer = socket.remoteAddress.address;
  StreamIterator<List<int>>? it;
  try {
    it = StreamIterator(socket.timeout(const Duration(seconds: 180)));
    final buf = BytesBuilder(copy: false);
    HeaderParseResult? hdr;

    while (hdr == null) {
      bool more;
      try {
        more = await it.moveNext();
      } catch (_) {
        return;
      }
      if (!more) return;

      final chunk = it.current;
      if (chunk.isEmpty) continue;

      buf.add(chunk);
      if (buf.length > 262144) {
        return;
      }
      hdr = parsePortalHeaderFlexible(Uint8List.fromList(buf.toBytes()));
    }

    final full = Uint8List.fromList(buf.toBytes());
    var bodyStart = hdr.bodyStart;
    if (bodyStart > full.length) return;

    final h = hdr.header;
    final msgSecret = (h['secret'] ?? '').toString().trim();
    if (secret.trim().isNotEmpty && msgSecret != secret.trim()) {
      try {
        socket.add(utf8.encode(jsonEncode({'type': 'portal_auth_failed'})));
        await socket.flush();
      } catch (_) {}
      await onEvent(
        'auth_failed',
        'Отклонено: неверный пароль сети. На ПК и в приложении должен быть один и тот же пароль (config.json / Настройки).',
        null,
      );
      return;
    }

    final type = (h['type'] ?? '').toString().trim();
    if (type == 'ping') {
      try {
        // Как десктоп: поля + \\n (часть клиентов читает построчно).
        socket.add(
          utf8.encode(
            '${jsonEncode({'type': 'pong', 'ok': true, 'version': 1})}\n',
          ),
        );
        await socket.flush();
      } catch (_) {}
      return;
    }

    if (type == 'clipboard') {
      final text = (h['text'] ?? '').toString();
      final snip = text.length > 80 ? '${text.substring(0, 80)}...' : text;
      await onEvent('receive_text', 'Текст от $peer: $snip', null);
      await HistoryRepository.insertInBackground(
        direction: 'receive',
        kind: 'text',
        peerIp: peer,
        peerLabel: peer,
        name: 'clipboard',
        snippet: text.length > 500 ? text.substring(0, 500) : text,
      );
      return;
    }

    if (type == 'file') {
      final rawFileLabel =
          h['filename'] ?? h['name'] ?? h['file'] ?? 'file';
      final fname = _safeName(rawFileLabel.toString());
      final filesize = int.tryParse((h['filesize'] ?? 0).toString()) ?? 0;
      if (filesize < 0) {
        return;
      }

      await Directory(receiveDir).create(recursive: true);
      var outPath = p.join(receiveDir, fname);
      if (await File(outPath).exists()) {
        final stem = p.basenameWithoutExtension(fname);
        final suf = p.extension(fname);
        final ts = DateTime.now().millisecondsSinceEpoch ~/ 1000;
        outPath = p.join(receiveDir, '${stem}_$ts$suf');
      }

      final sink = File(outPath).openWrite();

      var body = _stripLeadingBodyNoise(
        Uint8List.sublistView(full, bodyStart),
      );
      var got = 0;

      try {
        if (body.isNotEmpty) {
          final take = math.min(body.length, filesize);
          sink.add(body.sublist(0, take));
          got = take;
        }
        while (got < filesize) {
          bool more;
          try {
            more = await it.moveNext();
          } catch (_) {
            break;
          }
          if (!more) break;
          final part = it.current;
          if (part.isEmpty) continue;
          final need = filesize - got;
          final take = part.length > need ? need : part.length;
          sink.add(part.sublist(0, take));
          got += take;
        }
        await sink.flush();
        await sink.close();
      } catch (_) {
        await sink.close();
        try {
          await File(outPath).delete();
        } catch (_) {}
        await onEvent(
          'receive_fail',
          'Файл от $peer не сохранён: ошибка записи на диск.',
          null,
        );
        return;
      }

      if (got < filesize) {
        try {
          socket.add(utf8.encode('ERR'));
          await socket.flush();
        } catch (_) {}
        try {
          await File(outPath).delete();
        } catch (_) {}
        await onEvent(
          'receive_fail',
          'Файл от $peer не сохранён: обрыв передачи ($got из $filesize байт). '
              'Проверь Wi‑Fi / VPN и попробуй снова.',
          null,
        );
        return;
      }

      final stat = await File(outPath).length();
      if (stat != filesize) {
        try {
          socket.add(utf8.encode('ERR'));
          await socket.flush();
        } catch (_) {}
        try {
          await File(outPath).delete();
        } catch (_) {}
        await onEvent(
          'receive_fail',
          'Файл от $peer не сохранён: размер на диске ($stat) не совпадает с заголовком ($filesize).',
          null,
        );
        return;
      }

      try {
        socket.add(utf8.encode('OK'));
        await socket.flush();
      } catch (_) {}

      final kb = (stat / 1024).ceil().clamp(1, 1 << 30);
      final parts = <String>[
        '[+] Файл от $peer: $fname ($kb КБ)',
      ];
      if (Platform.isAndroid) {
        final okDl =
            await PortalAndroidDownloads.copyToDownloadsPortal(outPath, fname);
        if (okDl) {
          parts.add('копия: Загрузки → Portal');
        } else {
          parts.add('в «Загрузки/Portal» не скопировалось (смотри папку приёма в настройках)');
        }
      }
      final histOk = await HistoryRepository.insertInBackground(
        direction: 'receive',
        kind: 'file',
        peerIp: peer,
        peerLabel: peer,
        name: fname,
        storedPath: outPath,
        filesize: stat,
      );
      if (!histOk) {
        parts.add('история не записалась (перезапусти приложение)');
      }
      await onEvent(
        'receive_file',
        parts.join(' · '),
        outPath,
      );
      return;
    }
  } catch (_) {
    // ignore
  } finally {
    try {
      await it?.cancel();
    } catch (_) {}
    try {
      await socket.close();
    } catch (_) {}
  }
}
