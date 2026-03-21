"""
Portal для Android (Kivy): список IP компьютеров и «кому слать» — как на ПК; Share Sheet (ACTION_SEND).
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.checkbox import CheckBox
from kivy.uix.anchorlayout import AnchorLayout

try:
    from portal_protocol import send_file_to_peer, send_text_clipboard
except ImportError:
    send_file_to_peer = None  # type: ignore
    send_text_clipboard = None  # type: ignore

try:
    from android_share import (
        SharePayload,
        bind_new_intent,
        finish_activity,
        is_android_runtime,
        is_share_intent,
        read_share_intent,
        toast,
    )
except ImportError:
    SharePayload = None  # type: ignore

    def is_android_runtime() -> bool:
        return False

    def is_share_intent(*_a, **_k):
        return False

    def read_share_intent(*_a, **_k):
        return None

    def toast(_m, long=False):
        pass

    def finish_activity():
        pass

    def bind_new_intent(_cb):
        pass


PORTAL_SOURCE_ANDROID = "android"
CONFIG_NAME = "portal_android_config.json"

# Тёмная тема в духе «портала»: тёмно-синий + оранжевый акцент
C_BG = (0.06, 0.07, 0.11, 1)
C_PANEL = (0.11, 0.13, 0.2, 1)
C_ACCENT = (0.95, 0.45, 0.12, 1)
C_ACCENT_2 = (0.2, 0.45, 0.95, 1)
C_TEXT = (0.92, 0.93, 0.96, 1)
C_MUTED = (0.55, 0.58, 0.68, 1)


def config_path() -> Path:
    try:
        from android.storage import app_storage_path  # type: ignore

        p = Path(app_storage_path()) / CONFIG_NAME
        p.parent.mkdir(parents=True, exist_ok=True)
        return p
    except Exception:
        pass
    return Path.home() / ".portal_android" / CONFIG_NAME


def load_cfg() -> dict:
    p = config_path()
    if p.is_file():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"peers": [], "secret": ""}


def save_cfg(data: dict) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def normalize_peers(raw) -> list:
    """Как peer_ips + алиасы на ПК; send = «отмечен в списке кому слать» (аналог галочек на главном экране)."""
    out = []
    for p in raw or []:
        if not isinstance(p, dict):
            continue
        ip = str(p.get("ip", "")).strip()
        if not ip:
            continue
        name = str(p.get("name", "") or ip).strip()
        send = p.get("send", True)
        if not isinstance(send, bool):
            send = str(send).strip().lower() in ("1", "true", "yes", "on")
        out.append({"ip": ip, "name": name, "send": send})
    return out


def peers_marked_for_send(peers: list) -> list:
    """Только те IP, куда разрешена отправка (галочка)."""
    return [p for p in peers if p.get("send", True)]


def _asset_icon_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "icon.png"


class Panel(BoxLayout):
    """Карточка с скруглённым фоном."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.padding = dp(14)
        self.spacing = dp(10)
        with self.canvas.before:
            Color(*C_PANEL)
            self._rect = RoundedRectangle(radius=[dp(16)])
        self.bind(pos=self._sync_rect, size=self._sync_rect)

    def _sync_rect(self, *_args):
        self._rect.pos = self.pos
        self._rect.size = self.size


class PeerRow(BoxLayout):
    """Строка как на ПК: галочка «кому слать» + IP + подпись + удалить."""

    def __init__(
        self,
        ip: str = "",
        name: str = "",
        send: bool = True,
        on_remove=None,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.spacing = dp(6)
        self.size_hint_y = None
        self.height = dp(54)
        self._on_remove = on_remove

        # Галочка — как на главном экране Portal на ПК («Кому отправлять»)
        self.chk_send = CheckBox(
            size_hint=(None, None), size=(dp(36), dp(36)), active=send
        )
        self.chk_send.color = C_ACCENT
        wrap_chk = AnchorLayout(size_hint=(None, 1), width=dp(44))
        wrap_chk.add_widget(self.chk_send)
        self.add_widget(wrap_chk)

        self.ip_input = TextInput(
            hint_text="IP компьютера (100.x…)",
            text=ip,
            multiline=False,
            size_hint_x=0.44,
            background_color=(0.16, 0.18, 0.26, 1),
            foreground_color=C_TEXT,
            hint_text_color=C_MUTED,
            padding=[dp(10), dp(12), dp(8), dp(8)],
        )
        self.name_input = TextInput(
            hint_text="Подпись (необязательно)",
            text=name,
            multiline=False,
            size_hint_x=0.36,
            background_color=(0.16, 0.18, 0.26, 1),
            foreground_color=C_TEXT,
            hint_text_color=C_MUTED,
            padding=[dp(10), dp(12), dp(8), dp(8)],
        )
        rm = Button(
            text="✕",
            size_hint_x=0.12,
            background_color=(0.35, 0.18, 0.18, 1),
            color=C_TEXT,
        )
        rm.bind(on_press=lambda *_a: self._do_remove())
        self.add_widget(self.ip_input)
        self.add_widget(self.name_input)
        self.add_widget(rm)

    def _do_remove(self):
        if self._on_remove:
            self._on_remove(self)


class PortalAndroidApp(App):
    title = "Portal"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._share_boot = False
        self._share_completed = False
        self._settings_root = None
        self._cold_share_started = False
        self._peer_rows: list = []
        self._peers_box: BoxLayout | None = None
        self._status_label: Label | None = None
        self._secret_field: TextInput | None = None
        self._test_text: TextInput | None = None

    def build(self):
        Window.clearcolor = C_BG
        if is_android_runtime():
            bind_new_intent(self._android_on_new_intent)
            try:
                if is_share_intent():
                    self._share_boot = True
                    return FloatLayout()
            except Exception:
                pass

        return self._build_settings_ui()

    def _build_settings_ui(self):
        root = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
        self._settings_root = root

        # Шапка: логотип + название
        header = BoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(76),
            spacing=dp(14),
        )
        ipath = _asset_icon_path()
        if ipath.is_file():
            header.add_widget(
                Image(
                    source=str(ipath),
                    size_hint=(None, 1),
                    width=dp(64),
                    allow_stretch=True,
                    keep_ratio=True,
                )
            )
        ht = BoxLayout(orientation="vertical", spacing=dp(4))
        ht.add_widget(
            Label(
                text="Portal",
                font_size=dp(22),
                bold=True,
                color=C_TEXT,
                size_hint_y=None,
                height=dp(30),
                halign="left",
                valign="middle",
            )
        )
        ht.add_widget(
            Label(
                text="Отправка на твои компьютеры — те же IP и пароль, что в Portal на ПК",
                font_size=dp(13),
                color=C_MUTED,
                size_hint_y=None,
                height=dp(40),
                text_size=(max(Window.width - dp(120), dp(180)), None),
                halign="left",
            )
        )
        header.add_widget(ht)
        root.add_widget(header)

        scroll = ScrollView(do_scroll_x=False, bar_width=dp(6))
        body = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(14),
            padding=(0, 0, 0, dp(8)),
        )
        body.bind(minimum_height=body.setter("height"))

        # Онбординг (логика как на ПК)
        onb = Panel()
        onb.add_widget(
            Label(
                text="Что сюда вписывать",
                font_size=dp(17),
                bold=True,
                color=C_TEXT,
                size_hint_y=None,
                height=dp(28),
                halign="left",
                text_size=(Window.width - dp(56), None),
            )
        )
        onb_hint = Label(
            text=(
                "Сюда вносятся те же IP компьютеров, что на ПК в ⚙ Настройки → вкладка со списком адресов "
                "(на компьютере она называется «Пиры» — это просто список: один IP на строку, можно «100.x.x.x Имя»). "
                "Здесь удобнее таблицей.\n\n"
                "• IP — смотри на том ПК в главном окне Portal сверху: строка «📍 Tailscale IP» "
                "(часто 100.…) или локальный IP, если без Tailscale.\n"
                "• Галочка слева — «на этот компьютер слать»; на ПК это те же отметки, "
                "что блок «Кому отправлять» и кнопка «Сохранить выбор получателей».\n"
                "• Пароль сети — как на ПК: «Пароль сети (одинаковый на всех своих ПК)» в настройках.\n\n"
                "На ПК должен быть нажат «Запустить портал». Сохрани здесь настройки — потом в любом приложении: "
                "«Поделиться» → Portal."
            ),
            font_size=dp(13),
            color=C_MUTED,
            size_hint_y=None,
            text_size=(max(Window.width - dp(56), dp(200)), None),
            halign="left",
        )

        def _h_from_tex(inst, sz):
            inst.height = max(sz[1], dp(24))

        onb_hint.bind(texture_size=_h_from_tex)
        onb.add_widget(onb_hint)
        body.add_widget(onb)

        # Список IP — как «Пиры» + галочки «Кому отправлять» на ПК
        peers_panel = Panel()
        peers_panel.add_widget(
            Label(
                text="Список IP и кому слать",
                font_size=dp(17),
                bold=True,
                color=C_TEXT,
                size_hint_y=None,
                height=dp(28),
                halign="left",
            )
        )
        peers_sub = Label(
            text=(
                "☑ = этот адрес в списке получателей (как галочки «Кому отправлять» на главном экране Portal). "
                "IP = адрес другого компьютера. Подпись — только для себя."
            ),
            font_size=dp(12),
            color=C_MUTED,
            size_hint_y=None,
            text_size=(max(Window.width - dp(56), dp(200)), None),
            halign="left",
        )
        peers_sub.bind(texture_size=_h_from_tex)
        peers_panel.add_widget(peers_sub)
        self._peers_box = BoxLayout(
            orientation="vertical",
            spacing=dp(8),
            size_hint_y=None,
        )
        self._peers_box.bind(minimum_height=self._peers_box.setter("height"))
        peers_panel.add_widget(self._peers_box)

        add_btn = Button(
            text="+ Добавить IP компьютера",
            size_hint_y=None,
            height=dp(48),
            background_color=C_ACCENT_2,
            color=C_TEXT,
            font_size=dp(15),
        )
        add_btn.bind(on_press=lambda *_a: self._add_peer_row())
        peers_panel.add_widget(add_btn)
        body.add_widget(peers_panel)

        # Пароль
        sec_panel = Panel()
        sec_panel.add_widget(
            Label(
                text="Пароль сети (одинаковый на всех своих ПК)",
                font_size=dp(16),
                bold=True,
                color=C_TEXT,
                size_hint_y=None,
                height=dp(26),
                halign="left",
            )
        )
        sec_hint = Label(
            text="Как в Portal на компьютере: ⚙ Настройки → вкладка «Пароль». Должен совпадать на телефоне и на всех ПК.",
            font_size=dp(12),
            color=C_MUTED,
            size_hint_y=None,
            text_size=(max(Window.width - dp(56), dp(200)), None),
            halign="left",
        )
        sec_hint.bind(texture_size=_h_from_tex)
        sec_panel.add_widget(sec_hint)
        self._secret_field = TextInput(
            hint_text="Введи пароль с ПК и сохрани",
            multiline=False,
            size_hint_y=None,
            height=dp(48),
            password=True,
            background_color=(0.16, 0.18, 0.26, 1),
            foreground_color=C_TEXT,
            hint_text_color=C_MUTED,
            padding=[dp(10), dp(14), dp(8), dp(8)],
        )
        sec_panel.add_widget(self._secret_field)
        body.add_widget(sec_panel)

        # Тест
        test_panel = Panel()
        test_panel.add_widget(
            Label(
                text="Проверка (как «Отправить буфер» на ПК)",
                font_size=dp(16),
                bold=True,
                color=C_TEXT,
                size_hint_y=None,
                height=dp(26),
                halign="left",
            )
        )
        test_hint = Label(
            text=(
                "Отправит текст в буфер обмена на все отмеченные галочкой компьютеры "
                "(на ПК должен быть «Запустить портал»)."
            ),
            font_size=dp(12),
            color=C_MUTED,
            size_hint_y=None,
            text_size=(max(Window.width - dp(56), dp(200)), None),
            halign="left",
        )
        test_hint.bind(texture_size=_h_from_tex)
        test_panel.add_widget(test_hint)
        self._test_text = TextInput(
            hint_text="Например: Привет с телефона",
            multiline=True,
            size_hint_y=None,
            height=dp(88),
            background_color=(0.16, 0.18, 0.26, 1),
            foreground_color=C_TEXT,
            hint_text_color=C_MUTED,
            padding=[dp(10), dp(10), dp(8), dp(8)],
        )
        test_panel.add_widget(self._test_text)

        row = BoxLayout(
            size_hint_y=None,
            height=dp(50),
            spacing=dp(10),
        )
        save_btn = Button(
            text="Сохранить список IP и выбор",
            background_color=C_ACCENT_2,
            color=C_TEXT,
        )
        save_btn.bind(on_press=lambda *_a: self.save_settings())
        test_btn = Button(
            text="Отправить тест на отмеченные",
            background_color=C_ACCENT,
            color=C_TEXT,
        )
        test_btn.bind(on_press=lambda *_a: self.send_test_text())
        row.add_widget(save_btn)
        row.add_widget(test_btn)
        test_panel.add_widget(row)
        body.add_widget(test_panel)

        self._status_label = Label(
            text="Сохрани список и галочки — потом «Поделиться» → Portal шлёт на отмеченные IP.",
            font_size=dp(12),
            color=C_MUTED,
            size_hint_y=None,
            text_size=(max(Window.width - dp(32), dp(200)), None),
            halign="left",
        )
        self._status_label.bind(texture_size=_h_from_tex)
        body.add_widget(self._status_label)

        scroll.add_widget(body)
        root.add_widget(scroll)

        # Загрузить конфиг
        cfg = load_cfg()
        if self._secret_field:
            self._secret_field.text = cfg.get("secret", "") or ""
        for pr in normalize_peers(cfg.get("peers")):
            self._add_peer_row(
                ip=pr["ip"],
                name=pr.get("name") or pr["ip"],
                send=pr.get("send", True),
            )
        if not self._peer_rows:
            self._add_peer_row()

        return root

    def _add_peer_row(self, ip: str = "", name: str = "", send: bool = True):
        if not self._peers_box:
            return

        def on_remove(row: PeerRow):
            if row in self._peer_rows:
                self._peer_rows.remove(row)
            self._peers_box.remove_widget(row)

        row = PeerRow(ip=ip, name=name, send=send, on_remove=on_remove)
        self._peer_rows.append(row)
        self._peers_box.add_widget(row)

    def on_start(self):
        if self._share_boot:
            Clock.schedule_once(lambda _dt: self._begin_share_from_cold_start(), 0.05)

    def _android_on_new_intent(self, intent):
        try:
            if not is_share_intent(intent=intent):
                return
            payload = read_share_intent(intent=intent)
            Clock.schedule_once(lambda _dt: self._run_share_flow(payload), 0.05)
        except Exception as ex:
            toast(f"Portal: intent {ex}", long=True)
            finish_activity()

    def _begin_share_from_cold_start(self):
        if self._cold_share_started:
            return
        self._cold_share_started = True
        try:
            payload = read_share_intent()
            self._run_share_flow(payload)
        except Exception as ex:
            toast(f"Portal: {ex}", long=True)
            finish_activity()

    def _run_share_flow(self, payload: SharePayload | None):
        if send_file_to_peer is None or send_text_clipboard is None:
            toast("Portal: нет portal_protocol", long=True)
            finish_activity()
            return
        if not payload:
            toast("Portal: пустой share", long=True)
            finish_activity()
            return
        has_files = bool(payload.file_paths)
        has_text = bool((payload.text or "").strip())
        if not has_files and not has_text:
            toast("Portal: нечего отправить", long=True)
            finish_activity()
            return

        cfg = load_cfg()
        peers = normalize_peers(cfg.get("peers"))
        secret = (cfg.get("secret") or "").strip()
        if not peers:
            toast(
                "Открой Portal на телефоне: добавь IP компьютера и нажми «Сохранить список IP и выбор».",
                long=True,
            )
            finish_activity()
            return

        targets = peers_marked_for_send(peers)
        if not targets:
            toast(
                "Ни у одного адреса не стоит галочка «слать сюда». Открой Portal и отметь получателей.",
                long=True,
            )
            finish_activity()
            return

        if len(targets) == 1:
            self._share_completed = True
            self._send_payload_thread(payload, targets, secret)
            return

        self._open_peer_picker(payload, targets, secret)

    def _open_peer_picker(self, payload: SharePayload, peers: list, secret: str):
        self._share_completed = False
        layout = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(10))
        layout.add_widget(
            Label(
                text="Куда отправить? (только отмеченные в настройках)",
                size_hint_y=None,
                height=dp(36),
                color=C_TEXT,
                text_size=(Window.width * 0.82, None),
                halign="center",
            )
        )
        btn_col = BoxLayout(
            orientation="vertical",
            spacing=dp(6),
            size_hint_y=None,
        )
        btn_col.bind(minimum_height=btn_col.setter("height"))

        pop = [None]

        def make_choose(peer):
            def on_press(_w):
                self._share_completed = True
                pop[0].dismiss()
                self._send_payload_thread(payload, [peer], secret)

            return on_press

        for peer in peers:
            label = peer.get("name") or peer["ip"]
            b = Button(
                text=label,
                size_hint_y=None,
                height=dp(48),
                background_color=C_ACCENT_2,
                color=C_TEXT,
            )
            b.bind(on_press=make_choose(peer))
            btn_col.add_widget(b)

        b_all = Button(
            text="На все отмеченные компьютеры",
            size_hint_y=None,
            height=dp(48),
            background_color=C_ACCENT,
            color=C_TEXT,
        )

        def on_all(_w):
            self._share_completed = True
            pop[0].dismiss()
            self._send_payload_thread(payload, list(peers), secret)

        b_all.bind(on_press=on_all)
        btn_col.add_widget(b_all)

        scroll = ScrollView(
            size_hint=(1, 1),
            do_scroll_x=False,
        )
        scroll.add_widget(btn_col)
        layout.add_widget(scroll)

        pop[0] = Popup(
            title="Portal",
            content=layout,
            size_hint=(0.88, 0.55),
            auto_dismiss=True,
        )

        def on_dismiss(_inst):
            if not self._share_completed:
                finish_activity()

        pop[0].bind(on_dismiss=on_dismiss)
        pop[0].open()

    def _send_payload_thread(self, payload: SharePayload, targets: list, secret: str):
        src = PORTAL_SOURCE_ANDROID

        def work():
            errs: list[str] = []
            for peer in targets:
                ip = peer["ip"]
                name = peer.get("name") or ip
                for fp in payload.file_paths:
                    ok, err = send_file_to_peer(
                        ip, fp, secret=secret, portal_source=src
                    )
                    if not ok:
                        errs.append(f"{name}: файл — {err}")
                if (payload.text or "").strip():
                    ok, err = send_text_clipboard(
                        ip, payload.text, secret=secret, portal_source=src
                    )
                    if not ok:
                        errs.append(f"{name}: текст — {err}")

            def done():
                if errs:
                    msg = "; ".join(errs[:4])
                    if len(errs) > 4:
                        msg += "…"
                    toast(f"Portal: {msg}", long=True)
                else:
                    toast("Portal: отправлено")
                finish_activity()

            try:
                from android.runnable import run_on_ui_thread  # type: ignore

                run_on_ui_thread(done)
            except Exception:
                done()

        threading.Thread(target=work, daemon=True).start()

    def _collect_peers(self) -> list:
        peers = []
        for row in self._peer_rows:
            ip = row.ip_input.text.strip()
            if not ip:
                continue
            nm = row.name_input.text.strip() or ip
            peers.append(
                {
                    "ip": ip,
                    "name": nm,
                    "send": bool(row.chk_send.active),
                }
            )
        return peers

    def save_settings(self) -> None:
        if not self._settings_root or not self._secret_field:
            return
        try:
            peers = self._collect_peers()
            if not peers:
                if self._status_label:
                    self._status_label.text = "Добавь хотя бы один IP другого компьютера (как в списке IP в ⚙ на ПК)."
                return
            if not any(p.get("send") for p in peers):
                if self._status_label:
                    self._status_label.text = (
                        "Отметь галочку хотя бы у одного адреса — иначе некуда слать "
                        "(как «Сохранить выбор получателей» на ПК)."
                    )
                return
            cfg = {
                "peers": peers,
                "secret": self._secret_field.text.strip(),
            }
            save_cfg(cfg)
            if self._status_label:
                n = sum(1 for p in peers if p.get("send"))
                self._status_label.text = (
                    f"Сохранено: {len(peers)} адрес(ов), отправка на {n} отмеченных. "
                    "«Поделиться» → Portal — без открытия приложения."
                )
        except Exception as e:
            if self._status_label:
                self._status_label.text = f"Ошибка: {e}"

    def send_test_text(self) -> None:
        if not self._test_text:
            return
        if send_text_clipboard is None:
            return
        peers = self._collect_peers()
        if not peers:
            if self._status_label:
                self._status_label.text = "Сначала введи IP и нажми «Сохранить список IP и выбор»."
            return
        targets = peers_marked_for_send(peers)
        if not targets:
            if self._status_label:
                self._status_label.text = "Отметь галочку у хотя бы одного компьютера."
            return
        cfg = load_cfg()
        secret = (cfg.get("secret") or "").strip()
        txt = self._test_text.text or ""
        errs: list[str] = []
        oks = 0
        for p in targets:
            ip = p["ip"]
            ok, err = send_text_clipboard(
                ip,
                txt,
                secret=secret,
                portal_source=PORTAL_SOURCE_ANDROID,
            )
            if ok:
                oks += 1
            else:
                lbl = p.get("name") or ip
                errs.append(f"{lbl}: {err}")
        if self._status_label:
            if oks == len(targets):
                self._status_label.text = (
                    f"Текст отправлен на {oks} ПК — вставь Ctrl+V / Cmd+V на каждом."
                )
            elif oks:
                self._status_label.text = (
                    f"Частично: ок {oks}, ошибки: {'; '.join(errs[:2])}"
                )
            else:
                self._status_label.text = (
                    f"Не вышло: {'; '.join(errs[:2])}. Проверь IP, пароль и «Запустить портал» на ПК."
                )


if __name__ == "__main__":
    PortalAndroidApp().run()
