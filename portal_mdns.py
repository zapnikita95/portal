"""
mDNS (Bonjour / Zeroconf): объявление и поиск Portal в LAN (_portal._tcp).

Нужен пакет: pip install zeroconf (см. requirements.txt).
"""
from __future__ import annotations

import re
import socket
import threading
import time
from typing import Dict, List, Optional, Tuple

# Стандартный суффикс mDNS для TCP-сервиса
SERVICE_TYPE = "_portal._tcp.local."

_zc_lock = threading.Lock()
_zc_instance: object | None = None
_service_info: object | None = None


def _zeroconf_mod():
    try:
        from zeroconf import ServiceBrowser, ServiceInfo, Zeroconf
    except ImportError:
        return None
    return Zeroconf, ServiceInfo, ServiceBrowser


def _primary_ipv4() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.4)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith("127."):
            return ip
    except Exception:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except Exception:
        return "127.0.0.1"


def _safe_instance_name(display: str) -> str:
    s = re.sub(r"[^\w\-.]+", "-", (display or "portal").strip(), flags=re.UNICODE)
    s = s.strip("-_.") or "portal"
    return s[:40]


def start_advertise(port: int) -> None:
    """Зарегистрировать сервис в LAN (пока работает приём на порту)."""
    mods = _zeroconf_mod()
    if not mods:
        return
    Zeroconf, ServiceInfo, _Browser = mods
    import portal_config

    global _zc_instance, _service_info
    display = portal_config.load_portal_mdns_display_name()
    inst = _safe_instance_name(display)
    host_short = _safe_instance_name(socket.gethostname().split(".")[0])
    full_name = f"{inst}-{host_short}._portal._tcp.local."
    ip = _primary_ipv4()
    if ip.startswith("127."):
        return
    try:
        addr = socket.inet_aton(ip)
    except OSError:
        return
    props = {b"display": display.encode("utf-8", errors="ignore")[:255]}
    info = ServiceInfo(
        SERVICE_TYPE,
        full_name,
        addresses=[addr],
        port=int(port),
        properties=props,
    )
    with _zc_lock:
        stop_advertise()
        try:
            zc = Zeroconf()
            zc.register_service(info)
            _zc_instance = zc
            _service_info = info
        except Exception:
            try:
                zc.close()
            except Exception:
                pass


def stop_advertise() -> None:
    global _zc_instance, _service_info
    zc = _zc_instance
    info = _service_info
    _zc_instance = None
    _service_info = None
    if zc is None:
        return
    try:
        if info is not None:
            zc.unregister_service(info)
    except Exception:
        pass
    try:
        zc.close()
    except Exception:
        pass


class _BrowseListener:
    def __init__(self) -> None:
        self.by_ip: Dict[str, str] = {}

    def add_service(self, zc, type_: str, name: str) -> None:  # type: ignore[no-untyped-def]
        try:
            info = zc.get_service_info(type_, name, timeout=2000)
            if info is None:
                return
            disp = ""
            if info.properties:
                raw = info.properties.get(b"display") or info.properties.get(b"name")
                if raw:
                    disp = raw.decode("utf-8", errors="ignore").strip()
            if not disp:
                disp = name.replace("._portal._tcp.local.", "").replace("._portal._tcp.", "")
            for a in info.parsed_addresses():
                if a and a not in self.by_ip:
                    self.by_ip[a] = disp or a
        except Exception:
            pass

    def remove_service(self, zc, type_: str, name: str) -> None:  # type: ignore[no-untyped-def]
        pass

    def update_service(self, zc, type_: str, name: str) -> None:  # type: ignore[no-untyped-def]
        self.add_service(zc, type_, name)


def browse_peers(timeout: float = 2.8) -> List[Tuple[str, str]]:
    """
    Вернуть список (ipv4, отображаемое_имя) соседей с Portal в LAN.
    """
    mods = _zeroconf_mod()
    if not mods:
        return []
    Zeroconf, _Info, ServiceBrowser = mods
    zc: Optional[Zeroconf] = None
    try:
        zc = Zeroconf()
        listener = _BrowseListener()
        ServiceBrowser(zc, SERVICE_TYPE, listener)
        time.sleep(max(0.5, timeout))
        out = [(ip, nm) for ip, nm in listener.by_ip.items()]
        out.sort(key=lambda x: (x[1].lower(), x[0]))
        return out
    except Exception:
        return []
    finally:
        if zc is not None:
            try:
                zc.close()
            except Exception:
                pass
