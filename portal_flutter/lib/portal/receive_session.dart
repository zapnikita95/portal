import 'dart:async';
import 'dart:convert';
import 'dart:io';
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

/// Чтение ровно [n] байт из первого чанка после JSON и дальше из [it] (как ПК: clipboard_files).
class _PendingTcpReader {
  _PendingTcpReader(Uint8List initialAfterHeader)
      : _pend = _stripLeadingBodyNoise(initialAfterHeader),
        _pendOff = 0;

  Uint8List? _pend;
  int _pendOff;

  Future<int> writeExactly(IOSink sink, int n, StreamIterator<List<int>> it) async {
    var got = 0;
    while (got < n) {
      final need = n - got;
      if (_pend != null && _pendOff < _pend!.length) {
        final avail = _pend!.length - _pendOff;
        final take = avail < need ? avail : need;
        sink.add(_pend!.sublist(_pendOff, _pendOff + take));
        _pendOff += take;
        got += take;
        if (_pendOff >= _pend!.length) {
          _pend = null;
          _pendOff = 0;
        }
        continue;
      }
      bool more;
      try {
        more = await it.moveNext();
      } catch (_) {
        break;
      }
      if (!more) break;
      final part = it.current;
      if (part.isEmpty) continue;
      _pend = Uint8List.fromList(part);
      _pendOff = 0;
    }
    return got;
  }
}

const _maxClipboardRichImageBytes = 48 * 1024 * 1024;

Future<void> _finalizeSavedFile({
  required Socket socket,
  required String peer,
  required String outPath,
  required String fname,
  required Future<void> Function(String kind, String message, String? localPath)
      onEvent,
  String historyKind = 'file',
}) async {
  try {
    socket.add(utf8.encode('OK'));
    await socket.flush();
  } catch (_) {}

  final stat = await File(outPath).length();
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
    kind: historyKind,
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
}

/// Один последовательный читатель сокета — нельзя многократно вешать `.first` на Socket.
Future<void> handlePortalSocket(
  Socket socket, {
  required String receiveDir,
  required Set<String> acceptedSecrets,
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
    // Пустой acceptedSecrets = не проверять (как раньше при пустом общем пароле).
    if (acceptedSecrets.isNotEmpty && !acceptedSecrets.contains(msgSecret)) {
      try {
        socket.add(utf8.encode(jsonEncode({'type': 'portal_auth_failed'})));
        await socket.flush();
      } catch (_) {}
      await onEvent(
        'auth_failed',
        'Отклонено: неверный пароль. На устройстве-приёмнике в настройках и у пира должен быть '
            'тот же пароль, что в config.json на ПК (общий или свой у строки пира).',
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

    // Обычный файл и один файл из буфера ПК (Ctrl+Alt+C / «Отправить буфер») — одно и то же тело TCP.
    if (type == 'file' || type == 'clipboard_file') {
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
      final reader = _PendingTcpReader(Uint8List.sublistView(full, bodyStart));
      var got = 0;
      try {
        got = await reader.writeExactly(sink, filesize, it);
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

      await _finalizeSavedFile(
        socket: socket,
        peer: peer,
        outPath: outPath,
        fname: fname,
        onEvent: onEvent,
      );
      return;
    }

    if (type == 'clipboard_files') {
      final rawList = h['files'];
      if (rawList is! List || rawList.isEmpty) {
        try {
          socket.add(utf8.encode('ERR'));
          await socket.flush();
        } catch (_) {}
        return;
      }
      final specs = <({String name, int size})>[];
      for (final x in rawList) {
        if (x is! Map) continue;
        final m = Map<String, dynamic>.from(x);
        final nm = _safeName((m['filename'] ?? 'file').toString());
        final sz = int.tryParse((m['filesize'] ?? 0).toString()) ?? 0;
        if (sz < 0) continue;
        specs.add((name: nm, size: sz));
      }
      if (specs.isEmpty) {
        try {
          socket.add(utf8.encode('ERR'));
          await socket.flush();
        } catch (_) {}
        return;
      }

      await Directory(receiveDir).create(recursive: true);
      final reader = _PendingTcpReader(Uint8List.sublistView(full, bodyStart));
      final saved = <String>[];
      final savedNames = <String>[];

      try {
        for (final spec in specs) {
          var fname = spec.name;
          var outPath = p.join(receiveDir, fname);
          if (await File(outPath).exists()) {
            final stem = p.basenameWithoutExtension(fname);
            final suf = p.extension(fname);
            final ts = DateTime.now().millisecondsSinceEpoch ~/ 1000;
            fname = '${stem}_$ts$suf';
            outPath = p.join(receiveDir, fname);
          }
          final sink = File(outPath).openWrite();
          final got = await reader.writeExactly(sink, spec.size, it);
          await sink.flush();
          await sink.close();
          if (got < spec.size) {
            throw StateError('truncated $got/${spec.size}');
          }
          final st = await File(outPath).length();
          if (st != spec.size) {
            throw StateError('size mismatch');
          }
          saved.add(outPath);
          savedNames.add(fname);
          if (Platform.isAndroid) {
            await PortalAndroidDownloads.copyToDownloadsPortal(outPath, fname);
          }
          await HistoryRepository.insertInBackground(
            direction: 'receive',
            kind: 'file',
            peerIp: peer,
            peerLabel: peer,
            name: fname,
            storedPath: outPath,
            filesize: st,
          );
        }
        try {
          socket.add(utf8.encode('OK'));
          await socket.flush();
        } catch (_) {}
        final summary =
            '[+] От $peer из буфера ПК: ${saved.length} файл(ов) — ${savedNames.join(', ')}';
        await onEvent('receive_file', summary, saved.isNotEmpty ? saved.last : null);
      } catch (_) {
        for (final pth in saved) {
          try {
            await File(pth).delete();
          } catch (_) {}
        }
        try {
          socket.add(utf8.encode('ERR'));
          await socket.flush();
        } catch (_) {}
        await onEvent(
          'receive_fail',
          'Несколько файлов из буфера ПК не сохранены (обрыв или ошибка диска).',
          null,
        );
      }
      return;
    }

    if (type == 'clipboard_rich') {
      final clipKind = (h['clip_kind'] ?? '').toString().trim();
      final size = int.tryParse((h['size'] ?? 0).toString()) ?? 0;
      if (clipKind != 'image' ||
          size <= 0 ||
          size > _maxClipboardRichImageBytes) {
        try {
          socket.add(utf8.encode('ERR'));
          await socket.flush();
        } catch (_) {}
        return;
      }

      await Directory(receiveDir).create(recursive: true);
      final ts = DateTime.now().millisecondsSinceEpoch;
      final fname = 'portal_clipboard_$ts.png';
      var outPath = p.join(receiveDir, fname);
      if (await File(outPath).exists()) {
        outPath = p.join(receiveDir, 'portal_clipboard_${ts}_2.png');
      }

      final sink = File(outPath).openWrite();
      final reader = _PendingTcpReader(Uint8List.sublistView(full, bodyStart));
      var got = 0;
      try {
        got = await reader.writeExactly(sink, size, it);
        await sink.flush();
        await sink.close();
      } catch (_) {
        await sink.close();
        try {
          await File(outPath).delete();
        } catch (_) {}
        try {
          socket.add(utf8.encode('ERR'));
          await socket.flush();
        } catch (_) {}
        return;
      }

      if (got < size) {
        try {
          await File(outPath).delete();
        } catch (_) {}
        try {
          socket.add(utf8.encode('ERR'));
          await socket.flush();
        } catch (_) {}
        return;
      }

      final stat = await File(outPath).length();
      if (stat != size) {
        try {
          await File(outPath).delete();
        } catch (_) {}
        try {
          socket.add(utf8.encode('ERR'));
          await socket.flush();
        } catch (_) {}
        return;
      }

      await _finalizeSavedFile(
        socket: socket,
        peer: peer,
        outPath: outPath,
        fname: fname,
        onEvent: onEvent,
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
