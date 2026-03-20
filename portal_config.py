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


def load_remote_ip() -> Optional[str]:
    ip = _load_all().get("remote_ip")
    if not ip or not str(ip).strip():
        return None
    return str(ip).strip()


def save_remote_ip(ip: Optional[str]) -> None:
    """Сохранить IP в файл. Возвращает True если успешно."""
    try:
        data = _load_all()
        if ip and str(ip).strip():
            data["remote_ip"] = str(ip).strip()
        else:
            data.pop("remote_ip", None)
        p = config_path()
        p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        # Проверяем что записалось
        if ip and str(ip).strip():
            saved = load_remote_ip()
            if saved != str(ip).strip():
                print(f"[Portal] ВНИМАНИЕ: IP не сохранился! Введено: {ip}, прочитано: {saved}")
                return False
        return True
    except Exception as e:
        print(f"[Portal] Ошибка сохранения IP: {e}")
        return False
