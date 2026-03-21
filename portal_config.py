"""
Постоянные настройки (IP второго ПК) — один раз указал, больше не спрашиваем.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

IncomingClipboardFilesMode = Literal["disk", "clipboard", "both"]

INCOMING_CLIPBOARD_FILES_MODES: tuple[str, ...] = ("disk", "clipboard", "both")

# Подписи для UI (главное окно + контекстное меню виджета)
INCOMING_CLIPBOARD_FILES_MODE_LABELS_RU: Dict[str, str] = {
    "both": "Папка приёма + буфер (вставка файлов)",
    "disk": "Только папка приёма (без буфера)",
    "clipboard": "Только буфер (временная папка)",
}


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
    """Файл журнала (дублирует UI, можно открыть и скопировать вручную)."""
    return config_path().parent / "portal_activity.log"


def _load_all() -> Dict[str, Any]:
    p = config_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def default_receive_dir() -> Path:
    """
    Папка «Рабочий стол» по умолчанию.
    На Windows часто Desktop в OneDrive — C:\\Users\\...\\Desktop может не существовать.
    """
    home = Path.home()
    if sys.platform == "win32":
        prof = Path(os.environ.get("USERPROFILE", str(home)))
        candidates = [
            prof / "OneDrive" / "Desktop",
            prof / "OneDriveDesktop",  # редкий вариант
            prof / "Desktop",
            home / "Desktop",
        ]
        for p in candidates:
            try:
                if p.exists() and p.is_dir():
                    return p
            except OSError:
                continue
        # Создаём наиболее вероятный путь
        target = prof / "Desktop"
        target.mkdir(parents=True, exist_ok=True)
        return target
    d = home / "Desktop"
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def load_receive_dir() -> Path:
    data = _load_all()
    raw = data.get("receive_dir")
    if raw and str(raw).strip():
        p = Path(str(raw).strip()).expanduser()
        return p
    return default_receive_dir()


def load_incoming_clipboard_files_mode() -> IncomingClipboardFilesMode:
    """
    Как обрабатывать файлы, пришедшие из буфера другого ПК (clipboard_files):
    disk — только сохранить в папку приёма; clipboard — только в системный буфер
    (файлы пишутся во временную папку); both — и папка, и буфер.
    """
    data = _load_all()
    m = data.get("incoming_clipboard_files_mode", "both")
    if m in INCOMING_CLIPBOARD_FILES_MODES:
        return m  # type: ignore[return-value]
    return "both"


def save_incoming_clipboard_files_mode(mode: str) -> bool:
    if mode not in INCOMING_CLIPBOARD_FILES_MODES:
        return False
    try:
        data = _load_all()
        data["incoming_clipboard_files_mode"] = mode
        p = config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False


def incoming_clipboard_files_save_dir() -> Path:
    """Куда сохранять байты при приёме clipboard_files (зависит от режима)."""
    if load_incoming_clipboard_files_mode() == "clipboard":
        d = Path(tempfile.gettempdir()) / "PortalIncoming"
        d.mkdir(parents=True, exist_ok=True)
        return d
    return load_receive_dir()


def save_receive_dir(path: Path) -> bool:
    try:
        p = Path(path).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        try:
            p = p.resolve()
        except OSError:
            pass
        data = _load_all()
        data["receive_dir"] = str(p)
        cp = config_path()
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[Portal] Ошибка сохранения receive_dir: {e}")
        return False


def load_remote_ip() -> Optional[str]:
    """Один IP (для обратной совместимости) — первый из списка."""
    ips = load_remote_ips()
    return ips[0] if ips else _load_all().get("remote_ip") or None


def load_remote_ips() -> List[str]:
    """Список IP для отправки (множественные получатели)."""
    data = _load_all()
    raw = data.get("remote_ips")
    if isinstance(raw, list) and raw:
        out = []
        for x in raw:
            s = str(x).strip()
            if s and s not in out:
                out.append(s)
        return out
    # Обратная совместимость
    one = data.get("remote_ip")
    if one and str(one).strip():
        return [str(one).strip()]
    return []


def save_remote_ips(ips: List[str]) -> bool:
    """Сохранить список IP."""
    try:
        clean = []
        for ip in ips:
            s = str(ip).strip()
            if s and s not in clean:
                clean.append(s)
        data = _load_all()
        data["remote_ips"] = clean
        if clean:
            data["remote_ip"] = clean[0]
        else:
            data.pop("remote_ips", None)
            data.pop("remote_ip", None)
        p = config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:
        print(f"[Portal] Ошибка сохранения IP: {e}")
        return False


def load_auto_clipboard_enabled() -> bool:
    """Включена ли авто-отправка буфера при копировании."""
    return bool(_load_all().get("auto_clipboard_enabled", False))


def save_auto_clipboard_enabled(enabled: bool) -> bool:
    try:
        data = _load_all()
        data["auto_clipboard_enabled"] = enabled
        p = config_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False


def save_remote_ip(ip: Optional[str]) -> bool:
    """Сохранить один IP (для обратной совместимости — перезаписывает список)."""
    if ip and str(ip).strip():
        return save_remote_ips([ip.strip()])
    return save_remote_ips([])
