"""
Постоянные настройки (IP второго ПК) — один раз указал, больше не спрашиваем.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional


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
    ip = _load_all().get("remote_ip")
    if not ip or not str(ip).strip():
        return None
    return str(ip).strip()


def save_remote_ip(ip: Optional[str]) -> bool:
    """Сохранить IP в файл. Возвращает True если успешно."""
    try:
        ip_clean = str(ip).strip() if ip and str(ip).strip() else None
        data = _load_all()
        if ip_clean:
            data["remote_ip"] = ip_clean
        else:
            data.pop("remote_ip", None)
        p = config_path()
        # Убеждаемся что папка существует
        p.parent.mkdir(parents=True, exist_ok=True)
        # Записываем файл
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        # Проверяем что записалось (читаем сразу после записи)
        if ip_clean:
            saved = load_remote_ip()
            if saved != ip_clean:
                print(f"[Portal] ВНИМАНИЕ: IP не сохранился! Введено: {ip_clean}, прочитано: {saved}")
                print(f"[Portal] Файл: {p}")
                print(f"[Portal] Содержимое файла: {p.read_text(encoding='utf-8') if p.exists() else 'не существует'}")
                return False
        return True
    except Exception as e:
        import traceback
        print(f"[Portal] Ошибка сохранения IP: {e}")
        print(f"[Portal] Traceback: {traceback.format_exc()}")
        return False
