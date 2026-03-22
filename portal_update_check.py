"""
Проверка новой версии на GitHub Releases (десктоп Mac/Win).
Полная авто-установка без действий пользователя не делаем (подпись/notarize/права);
показываем диалог и открываем страницу загрузки.
"""

from __future__ import annotations

import os
import threading
import webbrowser
from typing import Any

import portal_config
import portal_github
import portal_i18n as i18n


def _current_desktop_version() -> str:
    return (os.environ.get("PORTAL_DESKTOP_VERSION") or portal_config.PORTAL_DESKTOP_VERSION).strip()


def _show_update_dialog(
    app: Any,
    *,
    current: str,
    new_tag: str,
    download_url: str,
    asset_name: str,
) -> None:
    try:
        import customtkinter as ctk
    except Exception:
        return

    msg = i18n.tr(
        "update.dialog_body",
        current=current,
        new_tag=new_tag,
        asset=asset_name,
    )

    win = ctk.CTkToplevel(app)
    win.title(i18n.tr("update.dialog_title"))
    win.geometry("480x220")
    try:
        win.transient(app)
        win.lift()
        win.focus_force()
    except Exception:
        pass

    ctk.CTkLabel(win, text=msg, wraplength=440, justify="left").pack(
        padx=16, pady=(16, 8)
    )

    def open_dl() -> None:
        try:
            webbrowser.open(download_url)
        except Exception:
            pass
        try:
            portal_config.save_dismissed_update_tag(new_tag)
        except Exception:
            pass
        win.destroy()

    def dismiss() -> None:
        try:
            portal_config.save_dismissed_update_tag(new_tag)
        except Exception:
            pass
        win.destroy()

    row = ctk.CTkFrame(win, fg_color="transparent")
    row.pack(pady=12)
    ctk.CTkButton(row, text=i18n.tr("update.open_download"), command=open_dl, width=200).pack(
        side="left", padx=6
    )
    ctk.CTkButton(
        row,
        text=i18n.tr("update.later"),
        command=dismiss,
        width=120,
        fg_color="transparent",
        border_width=1,
    ).pack(side="left", padx=6)


def check_and_notify_on_main_thread(app: Any) -> None:
    """Вызывать только из главного потока Tk."""
    repo = portal_config.load_github_repo()
    cur = _current_desktop_version()

    data, err = portal_github.fetch_latest_release_json(repo)
    try:
        portal_config.save_last_update_check_epoch()
    except Exception:
        pass
    if not data:
        try:
            app.log(f"🔄 Обновления: {err or 'нет данных'}")
        except Exception:
            pass
        return

    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        return

    if portal_config.load_dismissed_update_tag() == tag:
        return

    if not portal_github.version_a_newer_than_b(tag, cur):
        return

    dl_url, name = portal_github.pick_desktop_download_url(data)
    if not dl_url:
        dl_url = portal_github.all_releases_page_url(repo)
        name = "GitHub Releases"

    try:
        _show_update_dialog(app, current=cur, new_tag=tag, download_url=dl_url, asset_name=name)
    except Exception as ex:
        try:
            app.log(f"🔄 Доступна версия {tag} (у тебя {cur}). Ошибка окна: {ex}")
        except Exception:
            pass


def maybe_notify_update_async(app: Any) -> None:
    """Фоновый запрос API → UI в главном потоке."""
    if not portal_config.should_run_auto_update_check():
        return

    def work() -> None:
        try:
            repo = portal_config.load_github_repo()
            data, _err = portal_github.fetch_latest_release_json(repo)
            try:
                portal_config.save_last_update_check_epoch()
            except Exception:
                pass
            if not data:
                return
            tag = str(data.get("tag_name") or "").strip()
            cur = _current_desktop_version()
            if not portal_github.version_a_newer_than_b(tag, cur):
                return
            if portal_config.load_dismissed_update_tag() == tag:
                return
            dl_url, name = portal_github.pick_desktop_download_url(data)
            if not dl_url:
                dl_url = portal_github.all_releases_page_url(repo)
                name = "GitHub Releases"

            def ui() -> None:
                try:
                    _show_update_dialog(
                        app,
                        current=cur,
                        new_tag=tag,
                        download_url=dl_url,
                        asset_name=name or "",
                    )
                except Exception:
                    pass

            try:
                app.after(0, ui)
            except Exception:
                pass
        except Exception:
            pass

    threading.Thread(target=work, daemon=True, name="portal-update-check").start()


def manual_check_from_menu(app: Any) -> None:
    """Принудительная проверка из меню."""

    def work() -> None:
        try:
            repo = portal_config.load_github_repo()
            data, err = portal_github.fetch_latest_release_json(repo)
            try:
                portal_config.save_last_update_check_epoch()
            except Exception:
                pass

            def ui() -> None:
                if not data:
                    try:
                        app.log(f"🔄 Проверка обновлений: {err or 'ошибка'}")
                    except Exception:
                        pass
                    return
                tag = str(data.get("tag_name") or "").strip()
                cur = _current_desktop_version()
                if not portal_github.version_a_newer_than_b(tag, cur):
                    try:
                        app.log(f"🔄 Установлена актуальная версия ({cur}). На GitHub: {tag}.")
                    except Exception:
                        pass
                    return
                dl_url, name = portal_github.pick_desktop_download_url(data)
                if not dl_url:
                    dl_url = portal_github.all_releases_page_url(repo)
                    name = "GitHub Releases"
                try:
                    _show_update_dialog(
                        app,
                        current=cur,
                        new_tag=tag,
                        download_url=dl_url,
                        asset_name=name or "",
                    )
                except Exception as ex:
                    try:
                        app.log(f"🔄 Обновление {tag}: {ex}")
                    except Exception:
                        pass

            try:
                app.after(0, ui)
            except Exception:
                pass
        except Exception:
            pass

    threading.Thread(target=work, daemon=True, name="portal-update-check-manual").start()
