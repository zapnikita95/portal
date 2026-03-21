"""
Точка входа Android Foreground Service (python-for-android).
Слушает TCP :12345 в отдельном процессе — приём не обрывается при сворачивании UI.

Запуск из приложения: jnius ServicePortalreceive.start(PythonActivity.mActivity, ...).
"""
from __future__ import annotations

import os
import threading


def _run() -> None:
    try:
        from jnius import autoclass  # type: ignore

        PythonService = autoclass("org.kivy.android.PythonService")
        PythonService.mService.setAutoRestartService(True)
    except Exception:
        pass

    # Импорт main после инициализации сервиса (Kivy + виджеты подтянутся один раз).
    from main import ReceiveServer, load_cfg, _default_receive_dir

    cfg = load_cfg()
    secret = (cfg.get("secret") or "").strip()
    saf = (cfg.get("receive_saf_tree_uri") or "").strip()
    recv_dir = (cfg.get("receive_dir") or "").strip()
    if not saf:
        recv_dir = recv_dir or _default_receive_dir()
    else:
        recv_dir = recv_dir or _default_receive_dir()

    def on_event(kind: str, msg: str) -> None:
        try:
            from android_notifier import show_event_notification

            if kind in ("receive_file", "receive_text"):
                show_event_notification(kind, msg)
        except Exception:
            pass
        print(f"[PortalReceive] {kind}: {msg}")

    srv = ReceiveServer(
        receive_dir=recv_dir,
        secret=secret,
        on_event=on_event,
        saf_tree_uri=saf,
        use_kivy_clock=False,
    )
    srv.start()
    threading.Event().wait()


# p4a задаёт PYTHON_SERVICE_ARGUMENT при старте сервиса (может быть пустой строкой).
if "PYTHON_SERVICE_ARGUMENT" in os.environ:
    _run()
