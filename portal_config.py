"""
Постоянные настройки (IP пиров, папка приёма) — config.json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


def config_path() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or str(Path.home())
        d = Path(base) / "Portal"
    elif sys.platform == "darwin":
        d = Path.home() / "Library" / "Application Support" / "Portal"
    else:
        d = Path.home() / ".config" / "portal"
    d.mkdir(parents=True, exist_ok=True)
    return d / "config.json"


def activity_log_path() -> Path:
    """Копия журнала из UI (удобно открыть / grep). Рядом с config.json."""
    return config_path().parent / "portal_activity.log"


def _load_all() -> Dict[str, Any]:
    p = config_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_all(data: Dict[str, Any]) -> bool:
    try:
        p = config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False


def receive_dir_path() -> Path:
    """Куда сохранять входящие файлы. По умолчанию — рабочий стол."""
    data = _load_all()
    raw = data.get("receive_dir")
    if raw and str(raw).strip():
        p = Path(str(raw).strip()).expanduser()
        try:
            p.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        if p.is_dir():
            return p.resolve()
    return (Path.home() / "Desktop").resolve()


def save_receive_dir(path_str: Optional[str]) -> bool:
    """Пустая строка — сброс на рабочий стол по умолчанию."""
    try:
        p = (path_str or "").strip()
        data = _load_all()
        if not p:
            data.pop("receive_dir", None)
        else:
            path = Path(p).expanduser()
            path.mkdir(parents=True, exist_ok=True)
            if not path.is_dir():
                return False
            data["receive_dir"] = str(path.resolve())
        return _write_all(data)
    except Exception:
        return False


def receive_files_mode() -> str:
    """
    Как обрабатывать входящие файлы (обычная отправка и файл, забранный Cmd+Ctrl+V):
    both — папка приёма + буфер ОС; disk_only — только папка; clipboard_only — в буфер (+ файл в папке).
    Отправка «как из буфера» (portal_clipboard) по-прежнему всегда кладёт в буфер на приёме.
    """
    data = _load_all()
    v = data.get("receive_files_mode")
    if v in ("both", "disk_only", "clipboard_only"):
        return str(v)
    if data.get("receive_copy_to_clipboard") is False:
        return "disk_only"
    return "both"


def save_receive_files_mode(mode: str) -> bool:
    if mode not in ("both", "disk_only", "clipboard_only"):
        return False
    data = _load_all()
    data["receive_files_mode"] = mode
    data["receive_copy_to_clipboard"] = mode != "disk_only"
    return _write_all(data)


def receive_copy_to_clipboard_enabled() -> bool:
    """Совместимость: True, если нужно класть обычный приём в буфер."""
    return receive_files_mode() in ("both", "clipboard_only")


def save_receive_copy_to_clipboard(enabled: bool) -> bool:
    """Совместимость со старым чекбоксом."""
    return save_receive_files_mode("both" if enabled else "disk_only")


# ── Несколько IP ───────────────────────────────────────────────


def load_peer_ips() -> List[str]:
    """Все сохранённые IP (порядок сохраняется, дубликаты убираем)."""
    data = _load_all()
    raw = data.get("peer_ips")
    out: List[str] = []
    seen = set()
    if isinstance(raw, list):
        for x in raw:
            s = str(x).strip()
            if s and s not in seen:
                seen.add(s)
                out.append(s)
    if out:
        return out
    legacy = data.get("remote_ip")
    if legacy and str(legacy).strip():
        return [str(legacy).strip()]
    return []


def save_peer_ips(ips: List[str]) -> bool:
    seen = set()
    clean: List[str] = []
    for x in ips:
        s = str(x).strip()
        if s and s not in seen:
            seen.add(s)
            clean.append(s)
    data = _load_all()
    data["peer_ips"] = clean
    if clean:
        data["remote_ip"] = clean[0]
    else:
        data.pop("remote_ip", None)
        data.pop("peer_send_targets", None)
    return _write_all(data)


def load_peer_send_targets() -> List[str]:
    """
    IP, на которые идёт одновременная отправка.
    Пустой список в конфиге или все невалидны → все из peer_ips.
    """
    all_ips = load_peer_ips()
    if not all_ips:
        return []
    data = _load_all()
    sel = data.get("peer_send_targets")
    if not isinstance(sel, list) or not sel:
        return list(all_ips)
    allowed = set(all_ips)
    seen = set()
    out: List[str] = []
    for x in sel:
        s = str(x).strip()
        if s in allowed and s not in seen:
            seen.add(s)
            out.append(s)
    return out if out else list(all_ips)


def save_peer_send_targets(targets: List[str]) -> bool:
    all_ips = load_peer_ips()
    allowed = set(all_ips)
    clean = [str(x).strip() for x in targets if str(x).strip() in allowed]
    data = _load_all()
    if not clean or set(clean) == allowed:
        data.pop("peer_send_targets", None)
    else:
        data["peer_send_targets"] = clean
    return _write_all(data)


# Совместимость со старым кодом (один IP)


def load_remote_ip() -> Optional[str]:
    ips = load_peer_ips()
    return ips[0] if ips else None


def save_remote_ip(ip: Optional[str]) -> bool:
    """Один IP: добавить в список, если ещё нет; иначе очистить."""
    ip_clean = str(ip).strip() if ip and str(ip).strip() else None
    if not ip_clean:
        return save_peer_ips([])
    ips = load_peer_ips()
    if ip_clean not in ips:
        ips.append(ip_clean)
    else:
        ips = [ip_clean] + [x for x in ips if x != ip_clean]
    return save_peer_ips(ips)
