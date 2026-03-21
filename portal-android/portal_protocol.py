"""
Клиент протокола Портала (TCP JSON + поток байт) для Android / Kivy.
Совместимо с desktop portal.py: порт 12345, поле secret в первом JSON.
"""

from __future__ import annotations

import json
import os
import socket
import struct
from typing import Any, Dict, Optional, Tuple


PORTAL_PORT = 12345


def _sendall(sock: socket.socket, data: bytes) -> None:
    if data:
        sock.sendall(data)


def _merge_secret(msg: Dict[str, Any], secret: str) -> Dict[str, Any]:
    s = (secret or "").strip()
    if not s:
        return msg
    out = dict(msg)
    out["secret"] = s
    return out


def send_file_to_peer(
    host: str,
    filepath: str,
    *,
    port: int = PORTAL_PORT,
    secret: str = "",
    timeout: float = 120.0,
    portal_source: str = "",
) -> Tuple[bool, str]:
    """Отправить один файл (type file)."""
    host = (host or "").strip()
    if not host or not os.path.isfile(filepath):
        return False, "bad_args"
    try:
        size = os.path.getsize(filepath)
        name = os.path.basename(filepath)
        payload: Dict[str, Any] = {"type": "file", "filename": name, "filesize": size}
        ps = (portal_source or "").strip()
        if ps:
            payload["portal_source"] = ps
        msg = _merge_secret(payload, secret)
        raw = json.dumps(msg, ensure_ascii=False).encode("utf-8") + b"\n"
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        _sendall(sock, raw)
        with open(filepath, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                _sendall(sock, chunk)
        sock.settimeout(30.0)
        buf = sock.recv(64)
        sock.close()
        if buf.startswith(b"OK"):
            return True, "ok"
        return False, buf[:32].decode("utf-8", errors="replace")
    except OSError as e:
        return False, str(e)


def send_text_clipboard(
    host: str,
    text: str,
    *,
    port: int = PORTAL_PORT,
    secret: str = "",
    timeout: float = 30.0,
    portal_source: str = "",
) -> Tuple[bool, str]:
    """Отправить текст в буфер удалённого ПК (type clipboard). Ждём ответ: clipboard_ok или portal_auth_failed."""
    host = (host or "").strip()
    if not host:
        return False, "bad_host"
    sock: Optional[socket.socket] = None
    try:
        clip: Dict[str, Any] = {"type": "clipboard", "text": text or ""}
        ps = (portal_source or "").strip()
        if ps:
            clip["portal_source"] = ps
        msg = _merge_secret(clip, secret)
        raw = json.dumps(msg, ensure_ascii=False).encode("utf-8") + b"\n"
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        _sendall(sock, raw)
        # Настольный Portal после приёма шлёт JSON clipboard_ok; при ошибке пароля — portal_auth_failed
        sock.settimeout(min(12.0, max(4.0, timeout)))
        try:
            data = sock.recv(16384)
        except OSError as e:
            es = str(e).lower()
            # Старый настольный Portal не присылал ответ — только таймаут чтения
            if "timed out" in es or "timeout" in es or "resource temporarily unavailable" in es:
                return True, "ok"
            return False, str(e)
        if not data:
            return True, "ok"
        if b"portal_auth_failed" in data:
            return False, "неверный пароль сети"
        return True, "ok"
    except OSError as e:
        return False, str(e)
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass


def ping_peer(
    host: str,
    *,
    port: int = PORTAL_PORT,
    secret: str = "",
    timeout: float = 5.0,
) -> bool:
    try:
        msg = _merge_secret({"type": "ping"}, secret)
        raw = json.dumps(msg, ensure_ascii=False).encode("utf-8") + b"\n"
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        _sendall(s, raw)
        data = s.recv(4096)
        s.close()
        if not data:
            return False
        # первый JSON
        i = 0
        depth = 0
        in_str = False
        esc = False
        while i < len(data):
            c = data[i : i + 1]
            ch = chr(c[0]) if c else ""
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            else:
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        try:
                            obj = json.loads(data[: i + 1].decode("utf-8"))
                            return obj.get("type") == "pong"
                        except Exception:
                            return False
            i += 1
        return False
    except OSError:
        return False
