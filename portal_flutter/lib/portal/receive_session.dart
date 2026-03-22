import 'dart:async';
import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:path/path.dart' as p;
import 'package:portal_flutter/data/history_repository.dart';

import 'framing.dart';

String _safeName(String name) {
  var n = p.basename(name.trim().isEmpty ? 'file' : name.trim());
  n = n.replaceAll(RegExp(r'[^\w.\-]+', unicode: true), '_');
  if (n.isEmpty || n.startsWith('.')) n = 'file_$n';
  return n.length > 180 ? n.substring(0, 180) : n;
}

Future<void> handlePortalSocket(
  Socket socket, {
  required String receiveDir,
  required String secret,
  required Future<void> Function(String kind, String message, String? localPath)
      onEvent,
}) async {
  final peer = socket.remoteAddress.address;
  try {
    final buf = BytesBuilder(copy: false);
    HeaderParseResult? hdr;
    while (hdr == null) {
      final chunk = await socket.timeout(const Duration(seconds: 60)).first;
      if (chunk.isEmpty) {
        await socket.close();
        return;
      }
      buf.add(chunk);
      if (buf.length > 262144) {
        await socket.close();
        return;
      }
      hdr = parsePortalHeader(Uint8List.fromList(buf.toBytes()));
    }

    final full = buf.toBytes();
    final bodyStart = hdr.bodyStart;
    if (bodyStart > full.length) return;

    final h = hdr.header;
    final msgSecret = (h['secret'] ?? '').toString().trim();
    if (secret.trim().isNotEmpty && msgSecret != secret.trim()) {
      try {
        socket.add(utf8.encode(jsonEncode({'type': 'portal_auth_failed'})));
        await socket.flush();
      } catch (_) {}
      await socket.close();
      return;
    }

    final type = (h['type'] ?? '').toString().trim();
    if (type == 'ping') {
      try {
        socket.add(utf8.encode(jsonEncode({'type': 'pong'})));
        await socket.flush();
      } catch (_) {}
      await socket.close();
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
      await socket.close();
      return;
    }

    if (type == 'file') {
      final fname = _safeName((h['filename'] ?? 'file').toString());
      final filesize = int.tryParse((h['filesize'] ?? 0).toString()) ?? 0;
      if (filesize < 0) {
        await socket.close();
        return;
      }

      await Directory(receiveDir).create(recursive: true);
      final ts = DateTime.now().millisecondsSinceEpoch ~/ 1000;
      final outPath = p.join(receiveDir, '${ts}_$fname');
      final sink = File(outPath).openWrite();

      var got = full.length - bodyStart;
      try {
        if (got > 0) {
          sink.add(full.sublist(bodyStart));
        }
        while (got < filesize) {
          final part = await socket.timeout(const Duration(seconds: 120)).first;
          if (part.isEmpty) break;
          final take = part.length > filesize - got ? filesize - got : part.length;
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
        await socket.close();
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
        await socket.close();
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
        await socket.close();
        return;
      }

      try {
        socket.add(utf8.encode('OK'));
        await socket.flush();
      } catch (_) {}
      final kb = (filesize / 1024).ceil().clamp(1, 1 << 30);
      await onEvent(
        'receive_file',
        '[+] Файл от $peer: $fname ($kb КБ)',
        outPath,
      );
      await HistoryRepository.insertInBackground(
        direction: 'receive',
        kind: 'file',
        peerIp: peer,
        peerLabel: peer,
        name: fname,
        storedPath: outPath,
        filesize: filesize,
      );
      await socket.close();
      return;
    }

    await socket.close();
  } catch (_) {
    try {
      await socket.close();
    } catch (_) {}
  }
}
