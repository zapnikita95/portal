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
    final header = Map<String, dynamic>.from(raw as Map);
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
