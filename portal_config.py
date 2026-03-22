"""
Постоянные настройки (IP пиров, папка приёма) — config.json
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Алфавит без O/0/I/1 — проще диктовать и копировать
_SHARED_SECRET_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


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


def load_ui_language() -> str:
    """Язык UI: ru | en. Хранится в config.json."""
    data = _load_all()
    lang = str(data.get("ui_language") or "ru").strip().lower()
    if lang not in ("ru", "en"):
        return "ru"
    return lang


def save_ui_language(lang: str) -> bool:
    lang = str(lang or "ru").strip().lower()
    if lang not in ("ru", "en"):
        return False
    data = _load_all()
    data["ui_language"] = lang
    return _write_all(data)


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


def load_peer_receive_dirs() -> Dict[str, str]:
    """IP отправителя → свой путь приёма; если IP нет в словаре — общая папка receive_dir."""
    data = _load_all()
    raw = data.get("peer_receive_dirs")
    out: Dict[str, str] = {}
    if isinstance(raw, dict):
        for k, v in raw.items():
            ip = str(k).strip()
            p = str(v).strip() if v is not None else ""
            if ip and p:
                out[ip] = p
    return out


def save_peer_receive_dirs(mapping: Dict[str, str]) -> bool:
    data = _load_all()
    clean: Dict[str, str] = {}
    for k, v in (mapping or {}).items():
        ip = str(k).strip()
        p = str(v).strip() if v is not None else ""
        if ip and p:
            clean[ip] = p
    if not clean:
        data.pop("peer_receive_dirs", None)
    else:
        data["peer_receive_dirs"] = clean
    return _write_all(data)


def resolve_receive_dir_for_peer(peer_ip: Optional[str]) -> Path:
    """
    Куда сохранять входящие файлы от peer_ip.
    Если для IP задана строка в peer_receive_dirs и путь доступен — она; иначе receive_dir_path().
    """
    base = receive_dir_path()
    ip = (peer_ip or "").strip()
    if not ip:
        return base
    custom = load_peer_receive_dirs().get(ip)
    if not custom or not str(custom).strip():
        return base
    p = Path(str(custom).strip()).expanduser()
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        return base
    if p.is_dir():
        return p.resolve()
    return base


def format_peer_receive_dirs_for_editor() -> str:
    lines = [
        "# IP отправителя<TAB>путь (или IP пробел путь). Нет строки для IP — общая папка выше.",
        "",
    ]
    for ip, pth in sorted(load_peer_receive_dirs().items()):
        lines.append(f"{ip}\t{pth}")
    return "\n".join(lines) + "\n"


def parse_peer_receive_dirs_editor(text: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for line in (text or "").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if "\t" in s:
            ip, _, rest = s.partition("\t")
            path = rest.strip()
        else:
            parts = s.split(None, 1)
            if len(parts) < 2:
                continue
            ip, path = parts[0].strip(), parts[1].strip()
        if ip and path:
            out[ip] = path
    return out


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


# ── Совместимость с portal_clipboard_rich / Windows-веткой ──────────


def incoming_clipboard_files_save_dir(peer_ip: Optional[str] = None) -> Path:
    """Куда писать поток clipboard_files; при «только буфер» — temp (как на Win). Иначе папка по IP или общая."""
    import tempfile

    if receive_files_mode() == "clipboard_only":
        d = Path(tempfile.gettempdir()) / "PortalIncoming"
        d.mkdir(parents=True, exist_ok=True)
        return d
    return resolve_receive_dir_for_peer(peer_ip)


def load_incoming_clipboard_files_mode() -> str:
    """disk | clipboard | both — внутри portal_clipboard_rich / приём push."""
    m = receive_files_mode()
    return {"disk_only": "disk", "clipboard_only": "clipboard", "both": "both"}[m]


def save_incoming_clipboard_files_mode(mode: str) -> bool:
    rev = {"disk": "disk_only", "clipboard": "clipboard_only", "both": "both"}
    key = rev.get(mode)
    if not key:
        return False
    return save_receive_files_mode(key)


INCOMING_CLIPBOARD_FILES_MODE_LABELS_RU: Dict[str, str] = {
    "both": "Папка приёма + буфер",
    "disk": "Только папка",
    "clipboard": "Только буфер (временная папка)",
}


# ── Несколько IP ───────────────────────────────────────────────


def load_peer_ips() -> List[str]:
    """Все сохранённые IP (порядок сохраняется, дубликаты убираем)."""
    data = _load_all()
    out: List[str] = []
    seen = set()
    raw = data.get("peer_ips")
    if not isinstance(raw, list) or not raw:
        raw = data.get("remote_ips")  # старый ключ до merge
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
    allowed = set(clean)
    na = data.get("peer_aliases")
    if isinstance(na, dict):
        pruned = {
            str(k).strip(): str(v).strip()
            for k, v in na.items()
            if str(k).strip() in allowed and str(v).strip()
        }
        if pruned:
            data["peer_aliases"] = pruned
        else:
            data.pop("peer_aliases", None)
    elif not clean:
        data.pop("peer_aliases", None)
    return _write_all(data)


def load_peer_aliases() -> Dict[str, str]:
    """Отображаемые имена пиров на этой машине (IP → имя)."""
    data = _load_all()
    raw = data.get("peer_aliases")
    if not isinstance(raw, dict):
        return {}
    out: Dict[str, str] = {}
    for k, v in raw.items():
        ip = str(k).strip()
        nm = str(v).strip() if v is not None else ""
        if ip and nm:
            out[ip] = nm
    return out


def save_peer_aliases(aliases: Dict[str, str]) -> bool:
    """Полная замена словаря имён (только для IP из списка пиров)."""
    data = _load_all()
    allowed = set(load_peer_ips())
    clean: Dict[str, str] = {}
    for k, v in (aliases or {}).items():
        ip = str(k).strip()
        nm = str(v).strip()
        if ip in allowed and nm:
            clean[ip] = nm
    if clean:
        data["peer_aliases"] = clean
    else:
        data.pop("peer_aliases", None)
    return _write_all(data)


def _is_ipv4(s: str) -> bool:
    parts = s.split(".")
    if len(parts) != 4:
        return False
    for p in parts:
        if not p.isdigit():
            return False
        n = int(p)
        if n < 0 or n > 255:
            return False
    return True


def parse_peer_line(line: str) -> Optional[Tuple[str, str]]:
    """
    Строка списка пиров: «100.x.x.x» или «100.x.x.x Имя» / «100.x.x.x, Имя».
    Возвращает (ip, name) где name может быть пустой строкой.
    """
    s = (line or "").strip()
    if not s or s.startswith("#"):
        return None
    s = re.sub(r"^#\s*", "", s)
    # «ip, name»
    if "," in s:
        left, _, right = s.partition(",")
        ip = left.strip()
        name = right.strip()
        if _is_ipv4(ip):
            return ip, name
        return None
    parts = s.split(None, 1)
    ip = parts[0].strip()
    name = parts[1].strip() if len(parts) > 1 else ""
    if not _is_ipv4(ip):
        return None
    return ip, name


def peer_display_label(ip: str) -> str:
    """Подпись в UI: «Мой Мак (100.x.x.x)» или просто IP."""
    ip = str(ip).strip()
    if not ip:
        return ""
    al = load_peer_aliases().get(ip, "").strip()
    return f"{al} ({ip})" if al else ip


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


# ── Совместимость со старыми именами API (единый portal.py) ─────────────


def load_auto_clipboard_enabled() -> bool:
    """Авто-отправка буфера при каждом копировании (чекбокс в UI)."""
    return bool(_load_all().get("auto_clipboard_enabled", False))


def save_auto_clipboard_enabled(enabled: bool) -> bool:
    data = _load_all()
    data["auto_clipboard_enabled"] = bool(enabled)
    return _write_all(data)


def load_remote_ips() -> List[str]:
    """Алиас для load_peer_ips() (старый код)."""
    return load_peer_ips()


def save_remote_ips(ips: List[str]) -> bool:
    """Алиас для save_peer_ips() (старый код)."""
    return save_peer_ips(ips)


def load_receive_dir() -> Path:
    """Алиас для receive_dir_path() (старый код)."""
    return receive_dir_path()


def default_receive_dir() -> Path:
    """Папка приёма по умолчанию (рабочий стол)."""
    return receive_dir_path()


# ── Пароль сети (shared secret) — одинаковый на всех своих ПК ─────────


def load_shared_secret() -> str:
    """Пустая строка = проверка отключена (как в старых версиях)."""
    v = _load_all().get("shared_secret")
    if v is None:
        return ""
    s = str(v).strip()
    return s


def save_shared_secret(secret: Optional[str]) -> bool:
    """Пустая строка или None — убрать пароль из конфига."""
    data = _load_all()
    if secret is None or not str(secret).strip():
        data.pop("shared_secret", None)
    else:
        data["shared_secret"] = str(secret).strip()
    return _write_all(data)


def generate_shared_secret(length: int = 12) -> str:
    """Случайный код без O/0/I/1 (по умолчанию 12 символов, мин. 6, макс. 32)."""
    n = max(6, min(int(length), 32))
    return "".join(secrets.choice(_SHARED_SECRET_ALPHABET) for _ in range(n))


# ── GitHub (сборка Android APK в Actions) ──────────────────────────

DEFAULT_GITHUB_REPO = "zapnikita95/portal"


def load_github_repo() -> str:
    """Репозиторий owner/repo для ссылок и workflow_dispatch."""
    env = os.environ.get("PORTAL_GITHUB_REPO", "").strip()
    if env and env.count("/") == 1 and not env.startswith("/"):
        return env
    raw = (_load_all().get("github_repo") or "").strip()
    if raw and raw.count("/") == 1 and not raw.startswith("/"):
        return raw
    return DEFAULT_GITHUB_REPO


def save_github_repo(repo: Optional[str]) -> bool:
    s = (repo or "").strip()
    if not s or s.count("/") != 1 or s.startswith("/"):
        return False
    a, _, b = s.partition("/")
    if not a or not b or "/" in b:
        return False
    data = _load_all()
    data["github_repo"] = s
    return _write_all(data)


# ── Внешний вид виджета-портала (GIF/PNG и т.д.) ───────────────────


def load_widget_media_path() -> Optional[str]:
    """Путь к файлу анимации/картинки из config; None — в конфиге не задан (см. effective_widget_media_path)."""
    data = _load_all()
    raw = data.get("widget_media_path")
    if not raw or not str(raw).strip():
        return None
    p = Path(str(raw).strip()).expanduser()
    try:
        if p.is_file():
            return str(p.resolve())
    except OSError:
        pass
    return None


def save_widget_media_path(path: Optional[str]) -> bool:
    data = _load_all()
    if path is None or not str(path).strip():
        data.pop("widget_media_path", None)
    else:
        p = Path(str(path).strip()).expanduser()
        if not p.is_file():
            return False
        data["widget_media_path"] = str(p.resolve())
    return _write_all(data)


def load_widget_media_mode() -> str:
    """auto | animated | static — для PNG/JPEG обычно static (масштаб при открытии/закрытии)."""
    m = _load_all().get("widget_media_mode", "auto")
    if m in ("auto", "animated", "static"):
        return str(m)
    return "auto"


def save_widget_media_mode(mode: str) -> bool:
    if mode not in ("auto", "animated", "static"):
        return False
    data = _load_all()
    data["widget_media_mode"] = mode
    return _write_all(data)


WIDGET_MEDIA_MODE_LABELS_RU: Dict[str, str] = {
    "auto": "Авто (GIF — анимация, PNG/JPEG — статика с масштабом)",
    "animated": "Всегда как анимация (первый кадр WebP/APNG при многокадровости)",
    "static": "Всегда статика (один кадр, масштаб при открытии/закрытии)",
}

# Угол экрана для виджета-портала: br=bottom-right …
WIDGET_CORNER_LABELS_RU: Dict[str, str] = {
    "br": "Снизу справа",
    "bl": "Снизу слева",
    "tr": "Сверху справа",
    "tl": "Сверху слева",
}

_VALID_WIDGET_CORNERS = frozenset(WIDGET_CORNER_LABELS_RU.keys())


def load_widget_size() -> int:
    """Сторона квадрата виджета (пиксели), 80…600."""
    try:
        n = int(_load_all().get("widget_size", 220))
    except (TypeError, ValueError):
        n = 220
    return max(80, min(n, 600))


def load_widget_corner() -> str:
    c = str(_load_all().get("widget_corner", "br") or "br").strip().lower()
    if c in _VALID_WIDGET_CORNERS:
        return c
    return "br"


def load_widget_margin_x() -> int:
    try:
        return max(0, min(int(_load_all().get("widget_margin_x", 24)), 500))
    except (TypeError, ValueError):
        return 24


def load_widget_margin_y() -> int:
    try:
        return max(0, min(int(_load_all().get("widget_margin_y", 96)), 500))
    except (TypeError, ValueError):
        return 96


def widget_window_xy(
    screen_w: int, screen_h: int, size: int, corner: str, margin_x: int, margin_y: int
) -> Tuple[int, int]:
    """
    Левый верхний угол окна виджета.
    margin_x / margin_y — отступ от ближайших рёбер экрана (как раньше: справа 24, снизу 96).
    """
    c = corner if corner in _VALID_WIDGET_CORNERS else "br"
    mx = max(0, int(margin_x))
    my = max(0, int(margin_y))
    s = max(1, int(size))
    if c == "br":
        return screen_w - s - mx, screen_h - s - my
    if c == "bl":
        return mx, screen_h - s - my
    if c == "tr":
        return screen_w - s - mx, my
    if c == "tl":
        return mx, my
    return screen_w - s - mx, screen_h - s - my


def save_widget_geometry_settings(
    *,
    size: int,
    corner_key: str,
    margin_x: int,
    margin_y: int,
) -> bool:
    data = _load_all()
    try:
        sz = int(size)
    except (TypeError, ValueError):
        sz = 220
    data["widget_size"] = max(80, min(sz, 600))
    ck = str(corner_key or "br").strip().lower()
    if ck not in _VALID_WIDGET_CORNERS:
        ck = "br"
    data["widget_corner"] = ck
    try:
        data["widget_margin_x"] = max(0, min(int(margin_x), 500))
    except (TypeError, ValueError):
        data["widget_margin_x"] = 24
    try:
        data["widget_margin_y"] = max(0, min(int(margin_y), 500))
    except (TypeError, ValueError):
        data["widget_margin_y"] = 96
    return _write_all(data)


# macOS: фон «окошка» виджета (режим с рамкой), #RRGGBB
_DEFAULT_WIDGET_MAC_PANEL_BG = "#2a2d35"

# (hex, ключ i18n widget.mac_bg.*)
WIDGET_MAC_PANEL_BG_PRESETS: List[Tuple[str, str]] = [
    ("#2a2d35", "dark_default"),
    ("#1c1c1e", "dark_system"),
    ("#3a3a3c", "graphite"),
    ("#48484a", "elevated_dark"),
    ("#e5e5ea", "light_gray"),
    ("#f2f2f7", "light_system"),
    ("#ffffff", "white"),
]


def _normalize_widget_mac_panel_hex(raw: str) -> Optional[str]:
    s = str(raw or "").strip()
    if not s.startswith("#"):
        s = "#" + s
    if len(s) != 7:
        return None
    try:
        int(s[1:], 16)
    except ValueError:
        return None
    return s.lower()


def load_widget_mac_panel_bg_hex() -> str:
    data = _load_all()
    norm = _normalize_widget_mac_panel_hex(str(data.get("widget_mac_panel_bg") or ""))
    if norm:
        return norm
    return _DEFAULT_WIDGET_MAC_PANEL_BG


def load_widget_mac_panel_bg_rgb() -> Tuple[int, int, int]:
    h = load_widget_mac_panel_bg_hex().lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def save_widget_mac_panel_bg_hex(hex_raw: str) -> bool:
    norm = _normalize_widget_mac_panel_hex(hex_raw)
    if not norm:
        return False
    data = _load_all()
    data["widget_mac_panel_bg"] = norm
    return _write_all(data)


def widget_mac_panel_bg_presets() -> List[Tuple[str, str]]:
    return list(WIDGET_MAC_PANEL_BG_PRESETS)


# ── Пресеты портала (анимация по событию и IP) ───────────────────────

WIDGET_PRESET_EVENT_LABELS_RU: Dict[str, str] = {
    "receive": "С ПК пришёл буфер (текст или картинка)",
    "receive_file": "По сети пришёл файл",
    "send": "С этого ПК ушла отправка на другой",
}

_VALID_WIDGET_PRESET_EVENTS = frozenset({"receive", "receive_file", "send"})

# Новые ассеты каталога — одноразово дописываются к уже сохранённому списку пресетов
WIDGET_PRESET_BUNDLE_20260322 = frozenset(
    {"fuzzy_portal", "tech_portal", "stargate_portal"}
)

# rel_path относительно папки с portal_config.py (корень приложения «portal»)
DEFAULT_WIDGET_PRESETS_CATALOG: List[Dict[str, Any]] = [
    {
        "id": "main",
        "name": "Основное медиа виджета",
        "rel_path": None,
    },
    {
        "id": "blue",
        "name": "Синий стандарт",
        "rel_path": "assets/presets/blue_standard.webp",
    },
    {
        "id": "yellow",
        "name": "Жёлтый стандарт",
        "rel_path": "assets/portal_main.gif",
    },
    {"id": "classic", "name": "Classic", "rel_path": "assets/presets/classic.gif"},
    {"id": "space", "name": "Space", "rel_path": "assets/presets/space.gif"},
    {"id": "strange", "name": "Strange", "rel_path": "assets/presets/strange.gif"},
    {"id": "rick", "name": "Rick", "rel_path": "assets/presets/rick.gif"},
    {"id": "giphy", "name": "Giphy WebP", "rel_path": "assets/presets/giphy.webp"},
    {
        "id": "fuzzy_portal",
        "name": "Fuzzy Portal",
        "rel_path": "assets/presets/fuzzy_portal.gif",
    },
    {
        "id": "tech_portal",
        "name": "Tech Portal",
        "rel_path": "assets/presets/tech_portal.png",
    },
    {
        "id": "stargate_portal",
        "name": "Stargate Portal",
        "rel_path": "assets/presets/stargate_portal.gif",
    },
]

DEFAULT_WIDGET_PRESET_RULES: List[Dict[str, str]] = [
    {"peer": "*", "event": "receive", "preset": "main"},
    {"peer": "*", "event": "receive_file", "preset": "main"},
    {"peer": "*", "event": "send", "preset": "main"},
]


def portal_package_dir() -> Path:
    return Path(__file__).resolve().parent


def _migrate_widget_presets_catalog_inplace(items: List[Dict[str, Any]]) -> bool:
    """
    Раньше «Жёлтый стандарт» ссылался на yellow_standard.gif (часто путался со Strange).
    Теперь — тот же ассет, что основной портал: assets/portal_main.gif.
    """
    changed = False
    for x in items:
        if str(x.get("id", "")).strip() != "yellow":
            continue
        rp = x.get("rel_path")
        if not isinstance(rp, str) or not rp.strip():
            continue
        norm = rp.replace("\\", "/").lower()
        if "yellow_standard" in norm:
            x["rel_path"] = "assets/portal_main.gif"
            changed = True
    return changed


def load_widget_presets_catalog() -> List[Dict[str, Any]]:
    data = _load_all()
    raw = data.get("widget_presets_catalog")
    if isinstance(raw, list) and raw:
        out: List[Dict[str, Any]] = []
        for x in raw:
            if isinstance(x, dict) and str(x.get("id", "")).strip():
                out.append(
                    {
                        "id": str(x["id"]).strip(),
                        "name": str(x.get("name") or x["id"]).strip(),
                        "rel_path": x.get("rel_path"),
                    }
                )
        if out:
            if _migrate_widget_presets_catalog_inplace(out):
                save_widget_presets_catalog(out)
            data_all = _load_all()
            if not data_all.get("widget_presets_bundle_20260322"):
                ids_existing = {str(x.get("id", "")).strip() for x in out}
                to_add: List[Dict[str, Any]] = []
                for d in DEFAULT_WIDGET_PRESETS_CATALOG:
                    pid = str(d.get("id", "")).strip()
                    if pid in WIDGET_PRESET_BUNDLE_20260322 and pid not in ids_existing:
                        to_add.append(dict(d))
                if to_add:
                    out.extend(to_add)
                    save_widget_presets_catalog(out)
                data_all = _load_all()
                data_all["widget_presets_bundle_20260322"] = True
                _write_all(data_all)
            return out
    return [dict(x) for x in DEFAULT_WIDGET_PRESETS_CATALOG]


def save_widget_presets_catalog(presets: List[Dict[str, Any]]) -> bool:
    clean: List[Dict[str, Any]] = []
    for x in presets:
        if not isinstance(x, dict):
            continue
        pid = str(x.get("id", "")).strip()
        if not pid:
            continue
        clean.append(
            {
                "id": pid,
                "name": str(x.get("name") or pid).strip(),
                "rel_path": x.get("rel_path"),
            }
        )
    data = _load_all()
    data["widget_presets_catalog"] = clean
    return _write_all(data)


def _normalize_widget_preset_rules(raw: List[Any]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for x in raw:
        if not isinstance(x, dict):
            continue
        peer = str(x.get("peer", "*")).strip() or "*"
        ev = str(x.get("event", "")).strip()
        if ev not in _VALID_WIDGET_PRESET_EVENTS:
            continue
        preset = str(x.get("preset", "main")).strip() or "main"
        out.append({"peer": peer, "event": ev, "preset": preset})
    return out


def load_widget_preset_rules() -> List[Dict[str, str]]:
    data = _load_all()
    raw = data.get("widget_preset_rules")
    if isinstance(raw, list) and raw:
        norm = _normalize_widget_preset_rules(raw)
        if norm:
            return norm
    return [dict(x) for x in DEFAULT_WIDGET_PRESET_RULES]


def save_widget_preset_rules(rules: List[Dict[str, str]]) -> bool:
    data = _load_all()
    data["widget_preset_rules"] = _normalize_widget_preset_rules(rules)
    return _write_all(data)


def format_widget_preset_rules_for_editor(
    rules: Optional[List[Dict[str, str]]] = None,
) -> str:
    if rules is None:
        rules = load_widget_preset_rules()
    lines = [
        "# IP или *     receive | receive_file | send     id_пресета",
        "# Порядок: сначала совпадёт конкретный IP, затем *.",
        "",
    ]
    for r in rules:
        lines.append(f'{r["peer"]}\t{r["event"]}\t{r["preset"]}')
    return "\n".join(lines) + "\n"


def parse_widget_preset_rules_editor(text: str) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = re.split(r"[\t|,;]+", s)
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) < 3:
            continue
        peer, ev, preset = parts[0], parts[1], parts[2]
        if ev not in _VALID_WIDGET_PRESET_EVENTS:
            continue
        rows.append(
            {"peer": peer or "*", "event": ev, "preset": preset or "main"}
        )
    return rows if rows else [dict(x) for x in DEFAULT_WIDGET_PRESET_RULES]


def default_widget_media_fallback_path() -> Optional[str]:
    """
    Стандартное медиа виджета, если пользователь ничего не выбрал: portal_main.gif и т.д. в assets/.
    """
    assets_dir = portal_package_dir() / "assets"
    for name in (
        "portal_main.gif",
        "portal_main.png",
        "portal_animated.gif",
    ):
        cand = assets_dir / name
        if cand.is_file():
            return str(cand.resolve())
    return None


def effective_widget_media_path() -> Optional[str]:
    """Фактический путь к медиа: из config или стандартный файл из assets/."""
    mp = load_widget_media_path()
    if mp and Path(mp).is_file():
        return mp
    return default_widget_media_fallback_path()


def ensure_widget_media_path_persisted() -> Optional[str]:
    """
    Если в config нет пути, но в assets есть стандартный файл — записать его в config,
    чтобы в UI и логике «Медиа» всегда было конкретное значение.
    """
    mp = load_widget_media_path()
    if mp and Path(mp).is_file():
        return mp
    fb = default_widget_media_fallback_path()
    if fb and save_widget_media_path(fb):
        return fb
    return None


def resolve_widget_preset_file_path(preset_id: str) -> Optional[str]:
    pid = (preset_id or "main").strip() or "main"
    if pid == "main":
        eff = effective_widget_media_path()
        return str(Path(eff).resolve()) if eff and Path(eff).is_file() else None
    for pr in load_widget_presets_catalog():
        if str(pr.get("id", "")).strip() != pid:
            continue
        rel = pr.get("rel_path")
        if rel is None or (isinstance(rel, str) and not rel.strip()):
            eff = effective_widget_media_path()
            return str(Path(eff).resolve()) if eff and Path(eff).is_file() else None
        p = portal_package_dir() / str(rel).strip().lstrip("/\\")
        if p.is_file():
            return str(p.resolve())
        # Старые конфиги могли ссылаться на .gif, файл переименован в .webp
        if p.suffix.lower() == ".gif":
            alt = p.with_suffix(".webp")
            if alt.is_file():
                return str(alt.resolve())
        if p.suffix.lower() == ".webp":
            alt = p.with_suffix(".gif")
            if alt.is_file():
                return str(alt.resolve())
        return None
    return None


def resolve_widget_pulse_media_path(event: str, peer_ip: Optional[str]) -> Optional[str]:
    """
    Абсолютный путь к GIF/WebP/PNG для короткого импульса виджета.
    None — не менять медиа (остаётся как в поле «Медиа» / assets).
    """
    ev = (event or "").strip()
    if ev not in _VALID_WIDGET_PRESET_EVENTS:
        ev = "receive"
    peer_ip = (peer_ip or "").strip()
    rules = load_widget_preset_rules()

    def _sort_key(r: Dict[str, str]) -> Tuple[int, int]:
        wild = 1 if str(r.get("peer", "*")).strip() == "*" else 0
        return (wild, 0)

    def _pick(for_ev: str) -> Optional[str]:
        preset_id: Optional[str] = None
        for rule in sorted(rules, key=_sort_key):
            if str(rule.get("event", "")).strip() != for_ev:
                continue
            rp = str(rule.get("peer", "*")).strip() or "*"
            if rp != "*" and rp != peer_ip:
                continue
            preset_id = str(rule.get("preset", "main")).strip() or "main"
            break
        if preset_id is None:
            return None
        return resolve_widget_preset_file_path(preset_id)

    path = _pick(ev)
    if path is None and ev == "receive_file":
        path = _pick("receive")
    return path
