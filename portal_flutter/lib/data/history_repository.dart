import 'package:flutter/foundation.dart';
import 'package:path/path.dart' as p;
import 'package:path_provider/path_provider.dart';
import 'package:sqflite/sqflite.dart';

class HistoryRepository {
  static Database? _db;

  static Future<Database> _open() async {
    if (_db != null) return _db!;
    final dir = await getApplicationDocumentsDirectory();
    final path = p.join(dir.path, 'portal_history.db');
    _db = await openDatabase(
      path,
      version: 1,
      onConfigure: (db) async {
        await db.rawQuery('PRAGMA journal_mode=WAL');
      },
      onCreate: (db, v) async {
        await db.execute('''
CREATE TABLE portal_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  direction TEXT NOT NULL,
  kind TEXT NOT NULL,
  peer_ip TEXT,
  peer_label TEXT,
  name TEXT,
  snippet TEXT,
  stored_path TEXT,
  route_json TEXT,
  filesize INTEGER
)
''');
      },
    );
    return _db!;
  }

  static Future<bool> insert({
    required String direction,
    required String kind,
    String peerIp = '',
    String peerLabel = '',
    String name = '',
    String snippet = '',
    String storedPath = '',
    String routeJson = '',
    int? filesize,
  }) async {
    try {
      final db = await _open();
      await db.insert('portal_events', {
        'ts': DateTime.now().millisecondsSinceEpoch ~/ 1000,
        'direction': direction,
        'kind': kind,
        'peer_ip': peerIp,
        'peer_label': peerLabel,
        'name': name,
        'snippet': snippet,
        'stored_path': storedPath,
        'route_json': routeJson,
        'filesize': filesize,
      });
      return true;
    } catch (e, st) {
      debugPrint('HistoryRepository.insert failed: $e\n$st');
      return false;
    }
  }

  static Future<List<Map<String, Object?>>> list({int limit = 150}) async {
    final db = await _open();
    return db.query(
      'portal_events',
      orderBy: 'id DESC',
      limit: limit,
    );
  }

  static Future<Map<String, Object?>?> getRow(int id) async {
    final db = await _open();
    final rows = await db.query(
      'portal_events',
      where: 'id = ?',
      whereArgs: [id],
      limit: 1,
    );
    if (rows.isEmpty) return null;
    return rows.first;
  }

  /// Вызов из фонового изолята (отдельное открытие БД).
  static Future<bool> insertInBackground({
    required String direction,
    required String kind,
    String peerIp = '',
    String peerLabel = '',
    String name = '',
    String snippet = '',
    String storedPath = '',
    String routeJson = '',
    int? filesize,
  }) async {
    return insert(
      direction: direction,
      kind: kind,
      peerIp: peerIp,
      peerLabel: peerLabel,
      name: name,
      snippet: snippet,
      storedPath: storedPath,
      routeJson: routeJson,
      filesize: filesize,
    );
  }
}
