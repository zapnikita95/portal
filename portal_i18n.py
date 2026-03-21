"""
Локализация UI (ru / en). Строки в одном файле — без внешних JSON, чтобы PyInstaller не терял данные.
Язык: portal_config.load_ui_language(); после смены — перезапуск приложения.
"""

from __future__ import annotations

from typing import Any, Dict

import portal_config

# Параллель к portal_config.*_RU для выпадающих списков
WIDGET_MEDIA_MODE_LABELS_EN: Dict[str, str] = {
    "auto": "Auto (GIF = animated, PNG/JPEG = static scaled)",
    "animated": "Always animated (first frame for multi-frame WebP/APNG)",
    "static": "Always static (single frame, scale on open/close)",
}

WIDGET_CORNER_LABELS_EN: Dict[str, str] = {
    "br": "Bottom right",
    "bl": "Bottom left",
    "tr": "Top right",
    "tl": "Top left",
}

WIDGET_PRESET_EVENT_LABELS_EN: Dict[str, str] = {
    "receive": "Clipboard arrived from another PC",
    "receive_file": "A file arrived over the network",
    "send": "This PC sent something to another PC",
}


def get_lang() -> str:
    return portal_config.load_ui_language()


def tr(key: str, **kwargs: Any) -> str:
    lang = get_lang()
    table = STRINGS.get(lang) or STRINGS["ru"]
    s = table.get(key)
    if s is None:
        s = STRINGS["ru"].get(key, key)
    if kwargs:
        try:
            return s.format(**kwargs)
        except Exception:
            return s
    return s


def widget_media_mode_labels() -> Dict[str, str]:
    if get_lang() == "en":
        return dict(WIDGET_MEDIA_MODE_LABELS_EN)
    return dict(portal_config.WIDGET_MEDIA_MODE_LABELS_RU)


def widget_corner_labels() -> Dict[str, str]:
    if get_lang() == "en":
        return dict(WIDGET_CORNER_LABELS_EN)
    return dict(portal_config.WIDGET_CORNER_LABELS_RU)


def widget_preset_event_labels() -> Dict[str, str]:
    if get_lang() == "en":
        return dict(WIDGET_PRESET_EVENT_LABELS_EN)
    return dict(portal_config.WIDGET_PRESET_EVENT_LABELS_RU)


def incoming_clipboard_files_mode_labels() -> Dict[str, str]:
    if get_lang() == "en":
        return {
            "both": "Receive folder + clipboard",
            "disk": "Folder only",
            "clipboard": "Clipboard only (temp folder)",
        }
    return dict(portal_config.INCOMING_CLIPBOARD_FILES_MODE_LABELS_RU)


def hotkey_help_text(is_mac: bool, mac_legacy: bool, py313: bool) -> str:
    nl = "\n"
    if is_mac:
        if mac_legacy:
            body = tr("help.mac_legacy_body")
        else:
            body = tr("help.mac_default_body")
        extra = [tr("help.mac_extra1"), tr("help.mac_extra2")]
        if py313:
            extra.append(tr("help.mac_py313"))
        return nl.join([body, ""] + extra)
    return tr("help.win_body")


STRINGS: Dict[str, Dict[str, str]] = {
    "ru": {
        "app.title": "🌀 Портал",
        "toolbar.settings": "⚙ Настройки",
        "toolbar.apk": "📥 APK",
        "toolbar.log": "📋 Журнал",
        "toolbar.help": "❓",
        "main.subtitle": "Передача файлов и общий буфер · пиры и папки — в ⚙ Настройки",
        "main.ip_tailscale": "📍 Tailscale IP: {ip}",
        "main.ip_local": "📍 Локальный IP: {ip} (Tailscale не обнаружен)",
        "main.ip_unknown": "⚠️ IP адрес не определен",
        "main.peer_heading": "Кому отправлять ({hk}, файлы и виджет). Список IP редактируется в ⚙ Настройки → вкладка «Пиры»:",
        "main.network_password": "Пароль сети (одинаковый на всех своих ПК):",
        "main.secret_placeholder": "введи пароль и сохрани",
        "main.save_password": "Сохранить пароль",
        "main.secret_hint": "Когда пароль задан, менять его можно в ⚙ Настройки → «Пароль».",
        "main.save_recipients": "Сохранить выбор получателей",
        "main.conn_title": "📡 Статус связи",
        "main.local_recv_unknown": "⏸ Локальный приём: неизвестно",
        "main.peers_idle": "⚪ Пары: сохрани список IP и проверь связь",
        "main.probe_btn": "🔄 Проверить связь",
        "main.probe_auto": "авто каждые {sec} с, если есть IP",
        "btn.start": "🚀 Запустить портал",
        "btn.stop": "⏹ Остановить портал",
        "btn.send_file": "📤 Отправить файл",
        "btn.send_clipboard": "📋 Отправить буфер",
        "status.stopped": "⏸ Портал остановлен",
        "status.active": "✅ Портал активен — {shown}:{port}",
        "status.all_interfaces": "все интерфейсы (0.0.0.0)",
        "log.journal_hint": "📋 Журнал — кнопка «📋 Журнал» сверху. Файл: {path}",
        "log.ready": "Готов к работе...",
        "settings.title": "Настройки · Портал",
        "settings.tab_general": "Общее",
        "settings.tab_recv": "Папка и приём",
        "settings.tab_widget": "Виджет",
        "settings.tab_peers": "Пиры",
        "settings.tab_secret": "Пароль",
        "settings.ui_language": "Язык интерфейса:",
        "settings.save_language": "Сохранить язык",
        "settings.lang_note": "После сохранения перезапусти приложение.",
        "lang.saved_title": "Язык",
        "lang.restart_hint": "Перезапустите Портал, чтобы применить язык.",
        "recv.incoming_folder": "Папка для входящих файлов (по умолчанию — Рабочий стол):",
        "recv.incoming_hint": "Общая папка; ниже можно задать свою для конкретного IP отправителя. Режим «только в буфер» — файлы во временную папку (не по списку IP).",
        "recv.browse": "Обзор…",
        "recv.save_folder": "Сохранить папку",
        "recv.per_ip_title": "Своя папка приёма для каждого пира (необязательно):",
        "recv.per_ip_hint": "Ниже — по одному блоку на каждый IP из вкладки «Пиры». Пустое поле = используется общая папка приёма выше. После изменения списка IP нажмите «Сохранить список IP», затем настройте пути здесь.",
        "recv.per_ip_empty": "Пока нет сохранённых IP — добавьте их на вкладке «Пиры» и нажмите «Сохранить список IP».",
        "recv.per_ip_path_placeholder": "пусто → общая папка",
        "recv.per_ip_filedialog": "Папка для файлов с этого IP",
        "recv.save_ip_list": "Сохранить папки по IP",
        "recv.mode_title": "Режим входящих файлов (не из «буферного» push с другого ПК):",
        "recv_mode.both": "На диск и в буфер (Cmd+V)",
        "recv_mode.disk_only": "Только в папку приёма",
        "recv_mode.clipboard_only": "В буфер (+ файл в папке; без «Показать в Finder»)",
        "widget.media_title": "Медиа виджета на столе (GIF / PNG / JPEG / WebP):",
        "widget.media_placeholder": "стандарт: assets/portal_main.gif (подставляется автоматически)",
        "widget.video_gif": "Видео → GIF",
        "widget.reset": "Сброс",
        "widget.save_look": "Сохранить внешний вид",
        "widget.size_px": "Размер (px):",
        "widget.corner": "Угол:",
        "widget.margin_x": "Отступ X:",
        "widget.margin_y": "Y:",
        "widget.save_geo": "Сохранить размер и угол",
        "widget.hint_geo": "Компактно: 120–160 px, угол снизу справа. Видео — «Видео→GIF» или Обзор→MP4.",
        "widget.pulse_title": "Импульс виджета: пресеты и правила (какая анимация при приёме / отправке):",
        "widget.pulse_hint": "Пресет «Основное медиа виджета (main)» — то же изображение, что в поле «Медиа виджета на столе» выше (по умолчанию там же assets/portal_main.gif). Остальные пресеты — готовые файлы из assets/ и assets/presets/. Выбери пресет и нажми «Показать превью в углу» (~4 с).",
        "widget.preview_btn": "Показать превью в углу",
        "widget.rules_hint": "Для каждой строки: чей это IP в паре Portal (или * = любой), что произошло, какую картинку показать на виджете. Сначала ищется точное совпадение IP, иначе строка со *. IP можно выбрать из списка «Пиры» или вписать вручную в поле.",
        "widget.add_rule": "+ Строка правила",
        "widget.save_rules": "Сохранить правила пресетов",
        "widget.desktop_title": "🌀 Портал · виджет",
        "widget.rule_ip_placeholder": "* или IP",
        "widget.rules_col_peer": "Адрес в сети Portal",
        "widget.rules_col_event": "Событие",
        "widget.rules_col_preset": "Анимация (пресет)",
        "widget.rules_col_del": "",
        "widget.menu_remote_ip": "IP удалённого ПК (или тройной клик по порталу)",
        "widget.menu_pick_file": "Выбрать файл (Ctrl+клик)",
        "widget.menu_clip_recv": "Приём файлов из буфера (папка / буфер / оба)…",
        "widget.menu_hide": "Скрыть",
        "widget.menu_exit": "Выход",
        "widget.ip_dialog_title": "IP получателя",
        "widget.ip_label_simple": "IP второго компьютера:",
        "widget.ip_label_full": "IP второго компьютера (Tailscale / LAN):",
        "widget.file_pick_title": "Выберите файлы для отправки",
        "widget.no_clipboard_image": "⚠️ В буфере нет картинки. Скопируй изображение (не только файл в Finder).",
        "log.clipboard_recv_mode": "⚙️ Приём файлов из буфера: {label}",
        "log.clipboard_image_send": "📋 Картинка из буфера → {path} → отправка на {ip}",
        "log.clipboard_image_fail": "❌ Не удалось сохранить картинку из буфера: {err}",
        "log.widget_clipboard_err": "⚠️ Буфер: {m}",
        "log.widget_image_err": "⚠️ Картинка: {m}",
        "log.widget_send_clip_image": "📤 Картинка из буфера → отправка",
        "log.widget_send_files": "📤 Виджет: {name} → {n} ПК",
        "peers.list_title": "Список пиров (один IP на строку или «IP Имя»):",
        "peers.save_list": "Сохранить\nсписок IP",
        "secret.title": "Пароль сети (shared secret):",
        "secret.placeholder": "пусто = без пароля (как в старых версиях)",
        "secret.fill": "Подставить",
        "secret.save": "Сохранить",
        "secret.copy": "Копировать",
        "secret.gen_push": "Сгенерировать и разослать по сети",
        "secret.push_field": "Разослать пароль из поля (уже введённый)",
        "secret.long_hint": "Разсылка идёт на все IP из вкладки «Пиры» (кроме этого ПК). На удалённых машинах должен быть запущен приём Портала. Нужен текущий общий пароль — сначала все в одной сети с одним паролем, или без пароля (режим как в старых версиях). Отключить TCP-рассылку: PORTAL_NO_REMOTE_SECRET_SYNC=1.",
        "secret.banner_hint2": "Пока пароль не задан, на главном экране показывается быстрый ввод.",
        "apk.title": "Android APK",
        "apk.heading": "Android · Share → Portal",
        "apk.blurb": "Готовый APK лежит в GitHub Release (тег portal-android-latest). Кнопка ниже качает его в папку «Загрузки».",
        "apk.download": "⬇ Скачать APK с GitHub",
        "apk.open_release": "Открыть релиз в браузере",
        "apk.build_gh": "Собрать на GitHub",
        "apk.repo_hint": "Другой репозиторий (редко нужно):",
        "apk.save": "Сохранить",
        "apk.token_hint": "Скачивание с GitHub для публичного репо идёт без токена (битый PAT в .env раньше ломал только его). Сборка: без PORTAL_GITHUB_TOKEN откроется Actions — Run workflow; с токеном (repo + workflow) — запуск из приложения. Приватный репо — нужен валидный токен и для скачивания.",
        "logwin.title": "Журнал · Портал",
        "logwin.heading": "📋 Журнал",
        "logwin.copy_all": "Копировать всё",
        "logwin.copy_sel": "Копировать выделение",
        "logwin.open_folder": "Папка лога",
        "logwin.hint": "Ctrl+C в журнале — копирование. Файл: {path}",
        "help.title": "Справка · горячие клавиши",
        "help.mac_legacy_body": "macOS (PORTAL_MAC_HOTKEY_LEGACY=1):\n  Портал — Cmd+Option+P\n  Отправить буфер — Cmd+Shift+C\n  Забрать буфер — Cmd+Shift+V\n  Русская раскладка — Cmd+Option+з, Cmd+Shift+с / м",
        "help.mac_default_body": "macOS (по умолчанию, Cmd+Ctrl):\n  Показать/скрыть портал — Cmd+Ctrl+P\n  Отправить буфер — Cmd+Ctrl+C\n  Забрать буфер — Cmd+Ctrl+V\n  Русская раскладка — Cmd+Ctrl+з / с / м",
        "help.mac_extra1": "Забрать буфер — первый отмеченный IP на главном экране.",
        "help.mac_extra2": "Старые сочетания: export PORTAL_MAC_HOTKEY_LEGACY=1",
        "help.mac_py313": (
            "Python 3.13+: глобальные хоткеи — отдельный процесс (CGEventTap → NSEvent → pynput); "
            "обязательно «Мониторинг ввода» для **Portal.app** (сборка) или Python/Terminal (запуск из кода). "
            "После выдачи прав — полностью закрой Portal и открой снова. "
            "PORTAL_MAC_NO_HOTKEY_HELPER=1 — только при фокусе на окне Портала. "
            "Свёрнутое окно: байты из helper идут в Tk fileevent по pipe."
        ),
        "help.win_body": "Windows / Linux:\n  Портал — Ctrl+Alt+P или Win+Shift+P\n  Отправить буфер — Ctrl+Alt+C\n  Забрать буфер — Ctrl+Alt+V",
        "peer.add_ip_hint": "Добавь IP выше → «Сохранить список IP»",
        "local.recv_on": "🟢 Этот ПК принимает: {ip}:{port} (второй комп шлёт сюда файлы/буфер)",
        "local.recv_off": "⏸ Этот ПК не принимает — нажми «Запустить портал» (слушать :{port})",
        "peer.probe_empty": "⚪ Пары: добавь IP в список",
        "peer.all_ok": "🟢 Все {n} ПК отвечают на :{port}",
        "peer.partial": "⚠️ Онлайн {ok}/{total} — нет: {bad}",
        "peer.none_ok": "🔌 Ни один из {n} ПК не отвечает ({first}…)",
        "peer.need_ip": "⚪ Пара: укажи IP и «Сохранить IP»",
        "peer.ok": "🟢 Пара ({lbl}): Портал на :{port} отвечает",
        "peer.refused": "🔌 Пара ({lbl}): порт {port} закрыт — на том ПК «Запустить портал»",
        "peer.timeout": "⏱ Пара ({lbl}): таймаут — Tailscale, IP или файрвол",
        "peer.dns": "❓ Пара ({lbl}): адрес не найден (DNS)",
        "peer.bad_reply": "⚠ Пара ({lbl}): порт открыт, но ответ не Портал",
        "peer.no_host": "⚪ Пара: укажи IP",
        "peer.error": "❌ Пара ({lbl}): ошибка ({code})",
        "log.probe_ok": "📡 {ip}: OK (Портал)",
        "log.probe_fail": "📡 {ip}: нет связи ({code})",
    },
    "en": {
        "app.title": "🌀 Portal",
        "toolbar.settings": "⚙ Settings",
        "toolbar.apk": "📥 APK",
        "toolbar.log": "📋 Log",
        "toolbar.help": "❓",
        "main.subtitle": "File transfer & shared clipboard · peers and folders in ⚙ Settings",
        "main.ip_tailscale": "📍 Tailscale IP: {ip}",
        "main.ip_local": "📍 Local IP: {ip} (Tailscale not detected)",
        "main.ip_unknown": "⚠️ IP address not detected",
        "main.peer_heading": "Send to ({hk}, files & widget). Edit IPs in ⚙ Settings → Peers tab:",
        "main.network_password": "Network password (same on all your PCs):",
        "main.secret_placeholder": "enter password and save",
        "main.save_password": "Save password",
        "main.secret_hint": "Once set, change it in ⚙ Settings → Password.",
        "main.save_recipients": "Save recipient selection",
        "main.conn_title": "📡 Connection status",
        "main.local_recv_unknown": "⏸ Local receive: unknown",
        "main.peers_idle": "⚪ Peers: save IP list and check connection",
        "main.probe_btn": "🔄 Check connection",
        "main.probe_auto": "auto every {sec} s if IPs exist",
        "btn.start": "🚀 Start Portal",
        "btn.stop": "⏹ Stop Portal",
        "btn.send_file": "📤 Send file",
        "btn.send_clipboard": "📋 Send clipboard",
        "status.stopped": "⏸ Portal stopped",
        "status.active": "✅ Portal active — {shown}:{port}",
        "status.all_interfaces": "all interfaces (0.0.0.0)",
        "log.journal_hint": "📋 Log — «📋 Log» button at top. File: {path}",
        "log.ready": "Ready...",
        "settings.title": "Settings · Portal",
        "settings.tab_general": "General",
        "settings.tab_recv": "Folder & receive",
        "settings.tab_widget": "Widget",
        "settings.tab_peers": "Peers",
        "settings.tab_secret": "Password",
        "settings.ui_language": "Interface language:",
        "settings.save_language": "Save language",
        "settings.lang_note": "Restart the app after saving.",
        "lang.saved_title": "Language",
        "lang.restart_hint": "Restart Portal to apply the language.",
        "recv.incoming_folder": "Folder for incoming files (default — Desktop):",
        "recv.incoming_hint": "Shared folder; below you can set per-sender IP. “Clipboard only” uses a temp folder (not per-IP list).",
        "recv.browse": "Browse…",
        "recv.save_folder": "Save folder",
        "recv.per_ip_title": "Per-peer receive folder (optional):",
        "recv.per_ip_hint": "One block per IP from the Peers tab. Leave empty to use the main receive folder above. After editing peers, save the peer list, then set paths here.",
        "recv.per_ip_empty": "No saved IPs yet — add them on the Peers tab and click “Save IP list”.",
        "recv.per_ip_path_placeholder": "empty → main folder",
        "recv.per_ip_filedialog": "Folder for files from this peer",
        "recv.save_ip_list": "Save per-IP folders",
        "recv.mode_title": "Incoming files mode (not clipboard push from remote):",
        "recv_mode.both": "To disk and clipboard (Cmd/Ctrl+V)",
        "recv_mode.disk_only": "To receive folder only",
        "recv_mode.clipboard_only": "To clipboard (+ file in folder; no “Reveal in Finder”)",
        "widget.media_title": "Desktop widget media (GIF / PNG / JPEG / WebP):",
        "widget.media_placeholder": "default: assets/portal_main.gif (filled automatically)",
        "widget.video_gif": "Video → GIF",
        "widget.reset": "Reset",
        "widget.save_look": "Save appearance",
        "widget.size_px": "Size (px):",
        "widget.corner": "Corner:",
        "widget.margin_x": "Margin X:",
        "widget.margin_y": "Y:",
        "widget.save_geo": "Save size & corner",
        "widget.hint_geo": "Compact: 120–160 px, bottom-right corner. Video — «Video→GIF» or Browse→MP4.",
        "widget.pulse_title": "Widget pulse: presets & rules (animation on receive / send):",
        "widget.pulse_hint": "Preset “Main widget media” is the same as “Desktop widget media” above (default assets/portal_main.gif). Other presets are under assets/ and assets/presets/. Pick one and tap «Corner preview» (~4 s).",
        "widget.preview_btn": "Corner preview",
        "widget.rules_hint": "Each row: which machine in your Portal pair (or * = any), what happened, which image to pulse on the widget. Exact IP is tried first, then *. Pick an IP from Peers or type a custom one.",
        "widget.add_rule": "+ Add rule row",
        "widget.save_rules": "Save preset rules",
        "widget.desktop_title": "🌀 Portal · widget",
        "widget.rule_ip_placeholder": "* or IP",
        "widget.rules_col_peer": "Portal peer address",
        "widget.rules_col_event": "Event",
        "widget.rules_col_preset": "Animation (preset)",
        "widget.rules_col_del": "",
        "widget.menu_remote_ip": "Remote PC IP (or triple-click portal)",
        "widget.menu_pick_file": "Pick file (Ctrl+click)",
        "widget.menu_clip_recv": "Receive pasted files (folder / clipboard / both)…",
        "widget.menu_hide": "Hide",
        "widget.menu_exit": "Quit",
        "widget.ip_dialog_title": "Recipient IP",
        "widget.ip_label_simple": "Second computer IP:",
        "widget.ip_label_full": "Second computer IP (Tailscale / LAN):",
        "widget.file_pick_title": "Choose files to send",
        "widget.no_clipboard_image": "⚠️ No image in clipboard. Copy an image (not only a file in Finder).",
        "log.clipboard_recv_mode": "⚙️ Pasted files receive mode: {label}",
        "log.clipboard_image_send": "📋 Clipboard image → {path} → sending to {ip}",
        "log.clipboard_image_fail": "❌ Could not save clipboard image: {err}",
        "log.widget_clipboard_err": "⚠️ Clipboard: {m}",
        "log.widget_image_err": "⚠️ Image: {m}",
        "log.widget_send_clip_image": "📤 Clipboard image → send",
        "log.widget_send_files": "📤 Widget: {name} → {n} PC(s)",
        "peers.list_title": "Peer list (one IP per line or “IP Name”):",
        "peers.save_list": "Save\nIP list",
        "secret.title": "Network password (shared secret):",
        "secret.placeholder": "empty = no password (legacy mode)",
        "secret.fill": "Generate",
        "secret.save": "Save",
        "secret.copy": "Copy",
        "secret.gen_push": "Generate and push to peers",
        "secret.push_field": "Push password from field (already entered)",
        "secret.long_hint": "Push goes to all IPs in Peers (except this PC). Remote PCs must run Portal receive. Current shared password required — or start with no password (legacy). Disable TCP push: PORTAL_NO_REMOTE_SECRET_SYNC=1.",
        "secret.banner_hint2": "Until a password is set, quick entry is shown on the main screen.",
        "apk.title": "Android APK",
        "apk.heading": "Android · Share → Portal",
        "apk.blurb": "The APK is on GitHub Releases (tag portal-android-latest). The button below downloads it to Downloads.",
        "apk.download": "⬇ Download APK from GitHub",
        "apk.open_release": "Open release in browser",
        "apk.build_gh": "Build on GitHub",
        "apk.repo_hint": "Other repository (rare):",
        "apk.save": "Save",
        "apk.token_hint": "Public repos download without a token. Build: without PORTAL_GITHUB_TOKEN, Actions opens — Run workflow; with token (repo + workflow) — run from the app. Private repo needs a valid token for downloads too.",
        "logwin.title": "Log · Portal",
        "logwin.heading": "📋 Log",
        "logwin.copy_all": "Copy all",
        "logwin.copy_sel": "Copy selection",
        "logwin.open_folder": "Log folder",
        "logwin.hint": "Ctrl+C in log copies. File: {path}",
        "help.title": "Help · hotkeys",
        "help.mac_legacy_body": "macOS (PORTAL_MAC_HOTKEY_LEGACY=1):\n  Portal — Cmd+Option+P\n  Send clipboard — Cmd+Shift+C\n  Pull clipboard — Cmd+Shift+V\n  Russian layout — Cmd+Option+з, Cmd+Shift+с / м",
        "help.mac_default_body": "macOS (default, Cmd+Ctrl):\n  Show/hide portal — Cmd+Ctrl+P\n  Send clipboard — Cmd+Ctrl+C\n  Pull clipboard — Cmd+Ctrl+V\n  Russian layout — Cmd+Ctrl+з / с / м",
        "help.mac_extra1": "Pull clipboard — first checked IP on the main screen.",
        "help.mac_extra2": "Legacy shortcuts: export PORTAL_MAC_HOTKEY_LEGACY=1",
        "help.mac_py313": (
            "Python 3.13+: global hotkeys use a separate process (CGEventTap → NSEvent → pynput); "
            "enable Input Monitoring for **Portal.app** (release build) or Python/Terminal (dev). "
            "After granting permissions, fully quit Portal and reopen. "
            "PORTAL_MAC_NO_HOTKEY_HELPER=1 — only when the Portal window is focused. "
            "Minimized window: helper bytes go to Tk fileevent on a pipe."
        ),
        "help.win_body": "Windows / Linux:\n  Portal — Ctrl+Alt+P or Win+Shift+P\n  Send clipboard — Ctrl+Alt+C\n  Pull clipboard — Ctrl+Alt+V",
        "peer.add_ip_hint": "Add IPs above → «Save IP list»",
        "local.recv_on": "🟢 This PC receives: {ip}:{port} (remote PC sends files/clipboard here)",
        "local.recv_off": "⏸ This PC is not receiving — press «Start Portal» (listen :{port})",
        "peer.probe_empty": "⚪ Peers: add IPs to the list",
        "peer.all_ok": "🟢 All {n} PCs respond on :{port}",
        "peer.partial": "⚠️ Online {ok}/{total} — down: {bad}",
        "peer.none_ok": "🔌 None of {n} PCs respond ({first}…)",
        "peer.need_ip": "⚪ Peer: enter IP and save list",
        "peer.ok": "🟢 Peer ({lbl}): Portal responds on :{port}",
        "peer.refused": "🔌 Peer ({lbl}): port {port} closed — start Portal on that PC",
        "peer.timeout": "⏱ Peer ({lbl}): timeout — Tailscale, IP or firewall",
        "peer.dns": "❓ Peer ({lbl}): host not found (DNS)",
        "peer.bad_reply": "⚠ Peer ({lbl}): port open but reply is not Portal",
        "peer.no_host": "⚪ Peer: enter IP",
        "peer.error": "❌ Peer ({lbl}): error ({code})",
        "log.probe_ok": "📡 {ip}: OK (Portal)",
        "log.probe_fail": "📡 {ip}: no link ({code})",
    },
}
