"""
Список IPv4 этого хоста (без 127.0.0.1) — для скрытия «своих» адресов в LAN-скане и пирах.
Windows: GetAdaptersAddresses; macOS/Linux: getifaddrs (ctypes).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import socket
import sys
from typing import Set


def _is_plausible_host_ipv4(s: str) -> bool:
    parts = s.split(".")
    if len(parts) != 4:
        return False
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return False
    if nums[0] == 127:
        return False
    if nums[0] == 0 and nums[1] == 0 and nums[2] == 0 and nums[3] == 0:
        return False
    return all(0 <= n <= 255 for n in nums)


def _windows_ipv4_addresses() -> Set[str]:
    out: Set[str] = set()
    try:
        iphlpapi = ctypes.windll.iphlpapi  # type: ignore[attr-defined]
    except Exception:
        return out

    AF_INET = 2
    GAA_FLAG_INCLUDE_PREFIX = 0x0010
    ERROR_BUFFER_OVERFLOW = 111
    ERROR_SUCCESS = 0

    class IN_ADDR(ctypes.Structure):
        _fields_ = [("S_un", ctypes.c_byte * 4)]

    class SOCKADDR_IN(ctypes.Structure):
        _fields_ = [
            ("sin_family", ctypes.c_short),
            ("sin_port", ctypes.c_ushort),
            ("sin_addr", IN_ADDR),
            ("sin_zero", ctypes.c_byte * 8),
        ]

    class SOCKET_ADDRESS(ctypes.Structure):
        _fields_ = [("lpSockaddr", ctypes.c_void_p), ("iSockaddrLength", ctypes.c_int)]

    class IP_ADAPTER_UNICAST_ADDRESS(ctypes.Structure):
        pass

    IP_ADAPTER_UNICAST_ADDRESS._fields_ = [
        ("Length", ctypes.c_ulong),
        ("Flags", ctypes.c_ulong),
        ("Next", ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS)),
        ("Address", SOCKET_ADDRESS),
    ]

    class IP_ADAPTER_ADDRESSES(ctypes.Structure):
        pass

    IP_ADAPTER_ADDRESSES._fields_ = [
        ("Length", ctypes.c_ulong),
        ("IfIndex", ctypes.c_ulong),
        ("Next", ctypes.POINTER(IP_ADAPTER_ADDRESSES)),
        ("AdapterName", ctypes.c_char_p),
        ("FirstUnicastAddress", ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS)),
        ("FirstAnycastAddress", ctypes.c_void_p),
        ("FirstMulticastAddress", ctypes.c_void_p),
        ("FirstDnsServerAddress", ctypes.c_void_p),
        ("DnsSuffix", ctypes.c_wchar_p),
        ("Description", ctypes.c_wchar_p),
        ("FriendlyName", ctypes.c_wchar_p),
    ]

    size = ctypes.c_ulong(15_000)
    buf = ctypes.create_string_buffer(size.value)
    ret = iphlpapi.GetAdaptersAddresses(
        AF_INET,
        GAA_FLAG_INCLUDE_PREFIX,
        None,
        ctypes.cast(buf, ctypes.POINTER(IP_ADAPTER_ADDRESSES)),
        ctypes.byref(size),
    )
    if ret == ERROR_BUFFER_OVERFLOW:
        buf = ctypes.create_string_buffer(size.value)
        ret = iphlpapi.GetAdaptersAddresses(
            AF_INET,
            GAA_FLAG_INCLUDE_PREFIX,
            None,
            ctypes.cast(buf, ctypes.POINTER(IP_ADAPTER_ADDRESSES)),
            ctypes.byref(size),
        )
    if ret != ERROR_SUCCESS:
        return out

    p = ctypes.cast(buf, ctypes.POINTER(IP_ADAPTER_ADDRESSES))
    while p:
        a = p.contents
        u = a.FirstUnicastAddress
        while u:
            p = u.contents.Address.lpSockaddr
            if p:
                sin = ctypes.cast(p, ctypes.POINTER(SOCKADDR_IN)).contents
                if sin.sin_family == AF_INET:
                    data = bytes(sin.sin_addr.S_un)
                    ip = socket.inet_ntoa(data)
                    if _is_plausible_host_ipv4(ip):
                        out.add(ip)
            u = u.contents.Next
        if not a.Next:
            break
        p = a.Next
    return out


def _posix_ipv4_via_getifaddrs() -> Set[str]:
    out: Set[str] = set()
    if sys.platform == "win32":
        return out
    try:
        libc = ctypes.CDLL(ctypes.util.find_library("c"))
    except Exception:
        return out

    class in_addr(ctypes.Structure):
        _fields_ = [("s_addr", ctypes.c_uint32)]

    class sockaddr_in(ctypes.Structure):
        _fields_ = [
            ("sin_family", ctypes.c_uint16),
            ("sin_port", ctypes.c_uint16),
            ("sin_addr", in_addr),
        ]

    class sockaddr(ctypes.Structure):
        _fields_ = [("sa_family", ctypes.c_uint16), ("sa_data", ctypes.c_byte * 14)]

    class ifaddrs(ctypes.Structure):
        pass

    ifaddrs._fields_ = [
        ("ifa_next", ctypes.POINTER(ifaddrs)),
        ("ifa_name", ctypes.c_char_p),
        ("ifa_flags", ctypes.c_uint),
        ("ifa_addr", ctypes.POINTER(sockaddr)),
        ("ifa_netmask", ctypes.POINTER(sockaddr)),
        ("ifa_ifu", ctypes.c_void_p),
        ("ifa_data", ctypes.c_void_p),
    ]

    libc.getifaddrs.argtypes = [ctypes.POINTER(ctypes.POINTER(ifaddrs))]
    libc.getifaddrs.restype = ctypes.c_int
    libc.freeifaddrs.argtypes = [ctypes.POINTER(ifaddrs)]
    libc.freeifaddrs.restype = None

    head = ctypes.POINTER(ifaddrs)()
    if libc.getifaddrs(ctypes.byref(head)) != 0:
        return out
    try:
        p = head
        while p:
            a = p.contents
            if a.ifa_addr:
                fam = a.ifa_addr.contents.sa_family
                if fam == socket.AF_INET:
                    sin = ctypes.cast(a.ifa_addr, ctypes.POINTER(sockaddr_in)).contents
                    ip = socket.inet_ntoa(
                        ctypes.string_at(ctypes.addressof(sin.sin_addr), 4)
                    )
                    if _is_plausible_host_ipv4(ip):
                        out.add(ip)
            p = a.ifa_next
    finally:
        if head:
            libc.freeifaddrs(head)
    return out


def collect_non_loopback_ipv4() -> Set[str]:
    """Все нелокальные IPv4, назначенные интерфейсам."""
    if sys.platform == "win32":
        s = _windows_ipv4_addresses()
    else:
        s = _posix_ipv4_via_getifaddrs()
    return {x for x in s if _is_plausible_host_ipv4(x)}
