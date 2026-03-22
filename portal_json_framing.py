"""
Общий разбор первого JSON-объекта в TCP-потоке Portal (заголовок файла / ping / clipboard).

Критично для бинарного тела после JSON: нельзя декодировать весь буфер как UTF-8.
Используется на десктопе (portal.py) и на Android (portal-android).
"""

from __future__ import annotations

import json
from typing import Optional, Tuple

__all__ = ("parse_first_json_object_bytes", "strip_leading_tcp_json_delimiter")


def strip_leading_tcp_json_delimiter(prefix: bytes) -> bytes:
    """
    Убрать ведущие \\n/\\r с начала *тела* файла после JSON-заголовка.

    Клиенты шлют ``json.dumps(...).encode() + b\"\\\\n\"`` и затем байты файла.
    Если TCP разрезал поток так, что parse_first_json_object_bytes (ветка raw_decode)
    закончил ровно на ``}``, а ``\\\\n`` пришёл уже в первом recv тела, этот байт
    нельзя записывать в файл — для ZIP/docx первый байт 0x0a ломает формат.
    """
    return prefix.lstrip(b"\n\r")


def parse_first_json_object_bytes(buf: bytes) -> Tuple[Optional[dict], int]:
    """
    Первый полный JSON-объект в буфере + индекс первого байта *после* JSON (и пробелов).

    После JSON может идти бинарное тело файла. Ошибки UTF-8 decode с replace
    сдвигают длину — поэтому только инкрементальные префиксы и raw_decode.
    """
    if not buf:
        return None, 0
    lead = 3 if buf.startswith(b"\xef\xbb\xbf") else 0
    start = lead
    n = len(buf)
    while start < n and buf[start] in (9, 10, 13, 32):
        start += 1
    if start >= n:
        return None, 0
    if buf[start] != ord("{"):
        j = buf.find(b"{", start)
        if j < 0:
            return None, 0
        start = j

    decoder = json.JSONDecoder()
    max_scan = min(n, start + 262144)

    nl = buf.find(b"\n", start, max_scan)
    if nl > start:
        line = buf[start:nl]
        if line[:1] == b"{" or line.lstrip(b" \t\r\n").startswith(b"{"):
            try:
                obj = json.loads(line.decode("utf-8"))
                if isinstance(obj, dict):
                    j = nl + 1
                    while j < n and buf[j] in (9, 10, 13, 32):
                        j += 1
                    return obj, j
            except json.JSONDecodeError:
                pass

    for mid in range(start + 2, max_scan + 1):
        try:
            s = buf[start:mid].decode("utf-8")
        except UnicodeDecodeError:
            continue
        try:
            obj, ec = decoder.raw_decode(s)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict) or ec != len(s):
            continue
        j = mid
        while j < n and buf[j] in (9, 10, 13, 32):
            j += 1
        return obj, j
    return None, 0
