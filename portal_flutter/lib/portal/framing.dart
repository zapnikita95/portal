import 'dart:convert';
import 'dart:typed_data';

/// Результат: JSON-заголовок и индекс первого байта тела (после \\n и пробелов).
/// Десктоп шлёт `json\\n` + байты файла.
class HeaderParseResult {
  HeaderParseResult(this.header, this.bodyStart);
  final Map<String, dynamic> header;
  final int bodyStart;
}

HeaderParseResult? parsePortalHeader(Uint8List buf) {
  if (buf.isEmpty) return null;
  var i = 0;
  if (buf.length >= 3 && buf[0] == 0xef && buf[1] == 0xbb && buf[2] == 0xbf) {
    i = 3;
  }
  while (i < buf.length && (buf[i] == 9 || buf[i] == 10 || buf[i] == 13 || buf[i] == 32)) {
    i++;
  }
  final nl = buf.indexOf(0x0a, i);
  if (nl < 0) return null;
  try {
    final line = utf8.decode(buf.sublist(i, nl), allowMalformed: false);
    final raw = jsonDecode(line);
    if (raw is! Map) return null;
    final header = Map<String, dynamic>.from(raw);
    var j = nl + 1;
    while (j < buf.length &&
        (buf[j] == 9 || buf[j] == 10 || buf[j] == 13 || buf[j] == 32)) {
      j++;
    }
    return HeaderParseResult(header, j);
  } catch (_) {
    return null;
  }
}

/// Первый полный JSON-объект в строке (как `parse_first_json` на десктопе).
Map<String, dynamic>? parseFirstJsonObjectFromString(String s) {
  final i = s.indexOf('{');
  if (i < 0) return null;
  var depth = 0;
  for (var j = i; j < s.length; j++) {
    final c = s[j];
    if (c == '{') {
      depth++;
    } else if (c == '}') {
      depth--;
      if (depth == 0) {
        try {
          final o = jsonDecode(s.substring(i, j + 1));
          if (o is Map<String, dynamic>) return o;
          if (o is Map) {
            return o.map((k, v) => MapEntry(k.toString(), v));
          }
        } catch (_) {
          return null;
        }
      }
    }
  }
  return null;
}

/// Сначала строка `json\\n` + тело (файлы с ПК), иначе первый JSON в буфере
/// (десктопный `ping` идёт **без** `\\n` — старый парсер вечно ждал заголовок).
HeaderParseResult? parsePortalHeaderFlexible(Uint8List buf) {
  final strict = parsePortalHeader(buf);
  if (strict != null) return strict;
  if (buf.isEmpty) return null;
  final text = utf8.decode(buf, allowMalformed: true);
  final header = parseFirstJsonObjectFromString(text);
  if (header == null) return null;
  final i = text.indexOf('{');
  if (i < 0) return null;
  var depth = 0;
  var j = i;
  for (; j < text.length; j++) {
    final c = text[j];
    if (c == '{') {
      depth++;
    } else if (c == '}') {
      depth--;
      if (depth == 0) break;
    }
  }
  if (depth != 0) return null;
  final byteAfterJson = utf8.encode(text.substring(0, j + 1)).length;
  var bodyStart = byteAfterJson;
  while (bodyStart < buf.length &&
      (buf[bodyStart] == 9 ||
          buf[bodyStart] == 10 ||
          buf[bodyStart] == 13 ||
          buf[bodyStart] == 32)) {
    bodyStart++;
  }
  return HeaderParseResult(header, bodyStart);
}
