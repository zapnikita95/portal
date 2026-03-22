"""
Копия логики из ../portal_json_framing.py — держите синхронно при правках.
"""

from __future__ import annotations

import json
from typing import Optional, Tuple

__all__ = ("parse_first_json_object_bytes", "strip_leading_tcp_json_delimiter")


def strip_leading_tcp_json_delimiter(prefix: bytes) -> bytes:
    """Копия ../portal_json_framing.py — см. докстринг там."""
    return prefix.lstrip(b"\n\r")


def parse_first_json_object_bytes(buf: bytes) -> Tuple[Optional[dict], int]:
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
