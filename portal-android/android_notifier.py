"""
Уведомления Android из foreground service + опционально «Открыть» через FileProvider.
"""

from __future__ import annotations

import os
from typing import Optional

CHANNEL_ID = "portal_receive_v1"
NOTIFY_ID_FILE = 71001
NOTIFY_ID_TEXT = 71002

FILE_PROVIDER_AUTHORITY = "org.portal.portalshare.fileprovider"


def _service_context():
    try:
        from jnius import autoclass  # type: ignore

        PythonService = autoclass("org.kivy.android.PythonService")
        ctx = PythonService.mService
        return ctx
    except Exception:
        return None


def _activity_context():
    try:
        from jnius import autoclass  # type: ignore

        return autoclass("org.kivy.android.PythonActivity").mActivity
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


def _pending_intent_view_file(ctx, abs_path: str) -> Optional[object]:
    """PendingIntent ACTION_VIEW через FileProvider (content://)."""
    try:
        from jnius import autoclass, cast  # type: ignore

        File = autoclass("java.io.File")
        FileProvider = autoclass("androidx.core.content.FileProvider")
        Intent = autoclass("android.content.Intent")
        PendingIntent = autoclass("android.app.PendingIntent")
        URLConnection = autoclass("java.net.URLConnection")

        f = File(abs_path)
        if not f.exists():
            return None
        uri = FileProvider.getUriForFile(ctx, FILE_PROVIDER_AUTHORITY, f)
        mt = URLConnection.guessContentTypeFromName(abs_path) or "application/octet-stream"
        intent = Intent(Intent.ACTION_VIEW)
        intent.setDataAndType(uri, mt)
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
        flag_immutable = getattr(PendingIntent, "FLAG_IMMUTABLE", 0)
        flag_update = PendingIntent.FLAG_UPDATE_CURRENT
        return PendingIntent.getActivity(
            ctx, NOTIFY_ID_FILE, intent, flag_update | flag_immutable
        )
    except Exception:
        return None


def show_event_notification(
    kind: str,
    summary: str,
    local_path: Optional[str] = None,
) -> None:
    """Уведомление о приёме; для файла на диске — кнопка/тап «открыть»."""
    ctx = _service_context()
    if ctx is None:
        return
    Builder = _builder_class()
    if Builder is None:
        return
    body = (summary or "").strip()
    if len(body) > 220:
        body = body[:217] + "..."

    open_pi = None
    if kind == "receive_file" and local_path and os.path.isfile(local_path):
        open_pi = _pending_intent_view_file(ctx, local_path)

    try:
        from jnius import autoclass  # type: ignore

        _ensure_channel(ctx)
        nid = NOTIFY_ID_FILE if kind == "receive_file" else NOTIFY_ID_TEXT
        app_info = ctx.getApplicationInfo()
        icon_id = app_info.icon
        bldr = Builder(ctx, CHANNEL_ID)
        bldr.setSmallIcon(icon_id)
        bldr.setContentTitle("Portal")
        bldr.setContentText(body)
        try:
            bldr.setAutoCancel(True)
        except Exception:
            pass
        if open_pi is not None:
            try:
                bldr.setContentIntent(open_pi)
            except Exception:
                pass
            try:
                bldr.setPriority(
                    autoclass("androidx.core.app.NotificationCompat").PRIORITY_HIGH
                )
            except Exception:
                pass
        n = bldr.build()
        mgr = ctx.getSystemService(ctx.NOTIFICATION_SERVICE)
        mgr.notify(nid, n)
    except Exception:
        try:
            from jnius import autoclass  # type: ignore

            _ensure_channel(ctx)
            Builder2 = autoclass("android.support.v4.app.NotificationCompat$Builder")
            nid = NOTIFY_ID_FILE if kind == "receive_file" else NOTIFY_ID_TEXT
            app_info = ctx.getApplicationInfo()
            bldr = Builder2(ctx, CHANNEL_ID)
            bldr.setSmallIcon(app_info.icon)
            bldr.setContentTitle("Portal")
            bldr.setContentText(body)
            if open_pi is not None:
                try:
                    bldr.setContentIntent(open_pi)
                except Exception:
                    pass
            mgr = ctx.getSystemService(ctx.NOTIFICATION_SERVICE)
            mgr.notify(nid, bldr.build())
        except Exception:
            pass


def request_post_notifications_permission() -> None:
    """Android 13+ (API 33): runtime POST_NOTIFICATIONS."""
    try:
        from jnius import autoclass  # type: ignore

        Build = autoclass("android.os.Build$VERSION")
        if Build.SDK_INT < 33:
            return
        act = _activity_context()
        if act is None:
            return
        perm = "android.permission.POST_NOTIFICATIONS"
        PM = autoclass("android.content.pm.PackageManager")
        if act.checkSelfPermission(perm) == PM.PERMISSION_GRANTED:
            return
        act.requestPermissions([perm], 71003)
    except Exception:
        pass
