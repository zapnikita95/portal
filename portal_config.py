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
