"""
Уведомления Android из фонового процесса (Foreground Service).
Без Kivy UI — только jnius + NotificationCompat (androidx или support).
"""

from __future__ import annotations

CHANNEL_ID = "portal_receive_v1"
NOTIFY_ID_FILE = 71001
NOTIFY_ID_TEXT = 71002


def _service_context():
    try:
        from jnius import autoclass  # type: ignore

        PythonService = autoclass("org.kivy.android.PythonService")
        ctx = PythonService.mService
        return ctx
    except Exception:
        return None


def _ensure_channel(ctx) -> None:
    try:
        from jnius import autoclass  # type: ignore

        mgr = ctx.getSystemService(ctx.NOTIFICATION_SERVICE)
        ch = autoclass("android.app.NotificationChannel")(
            CHANNEL_ID,
            "Portal приём",
            autoclass("android.app.NotificationManager").IMPORTANCE_DEFAULT,
        )
        ch.setDescription("Входящие файлы и текст с ПК")
        mgr.createNotificationChannel(ch)
    except Exception:
        pass


def _builder_class():
    try:
        from jnius import autoclass  # type: ignore

        return autoclass("androidx.core.app.NotificationCompat$Builder")
    except Exception:
        try:
            from jnius import autoclass  # type: ignore

            return autoclass("android.support.v4.app.NotificationCompat$Builder")
        except Exception:
            return None


def show_event_notification(kind: str, summary: str) -> None:
    """Краткое уведомление о приёме файла/текста (сервис уже в foreground)."""
    ctx = _service_context()
    if ctx is None:
        return
    Builder = _builder_class()
    if Builder is None:
        return
    try:
        from jnius import autoclass, cast  # type: ignore

        _ensure_channel(ctx)
        nid = NOTIFY_ID_FILE if kind == "receive_file" else NOTIFY_ID_TEXT
        app_info = ctx.getApplicationInfo()
        icon_id = app_info.icon
        bldr = Builder(ctx, CHANNEL_ID)
        bldr.setSmallIcon(icon_id)
        bldr.setContentTitle("Portal")
        body = (summary or "").strip()
        if len(body) > 220:
            body = body[:217] + "..."
        bldr.setContentText(body)
        try:
            bldr.setAutoCancel(True)
        except Exception:
            pass
        n = bldr.build()
        mgr = ctx.getSystemService(ctx.NOTIFICATION_SERVICE)
        mgr.notify(nid, n)
    except Exception:
        try:
            from jnius import autoclass, cast  # type: ignore

            _ensure_channel(ctx)
            Builder2 = autoclass("android.support.v4.app.NotificationCompat$Builder")
            nid = NOTIFY_ID_FILE if kind == "receive_file" else NOTIFY_ID_TEXT
            app_info = ctx.getApplicationInfo()
            icon_id = app_info.icon
            bldr = Builder2(ctx, CHANNEL_ID)
            bldr.setSmallIcon(icon_id)
            bldr.setContentTitle("Portal")
            body = (summary or "").strip()
            if len(body) > 220:
                body = body[:217] + "..."
            bldr.setContentText(body)
            mgr = ctx.getSystemService(ctx.NOTIFICATION_SERVICE)
            mgr.notify(nid, bldr.build())
        except Exception:
            pass
