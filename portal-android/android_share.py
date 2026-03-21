"""
Чтение Android Share Intent (ACTION_SEND / SEND_MULTIPLE) через pyjnius.
Копирование content:// URI во временный файл в cacheDir.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class SharePayload:
    """Собранные данные из Intent: локальные пути к файлам + опциональный текст."""

    file_paths: List[str]
    text: str


def is_android_runtime() -> bool:
    return "ANDROID_ARGUMENT" in os.environ or os.path.exists("/system/build.prop")


def _safe_filename(name: str) -> str:
    n = (name or "").strip() or "shared"
    n = os.path.basename(n.replace("\\", "/"))
    n = re.sub(r"[^\w.\-]+", "_", n, flags=re.UNICODE)
    if not n or n.startswith("."):
        n = "shared_" + n
    return n[:180] if len(n) > 180 else n


def _java_activity():
    from jnius import autoclass  # type: ignore

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    return PythonActivity.mActivity


def _read_stream_to_path(inp, out_path: str) -> bool:
    """Считать java.io.InputStream в файл (бинарно)."""
    from jnius import autoclass  # type: ignore

    try:
        Array = autoclass("java.lang.reflect.Array")
        Byte = autoclass("java.lang.Byte")
        buf = Array.newInstance(Byte.TYPE, 65536)
        with open(out_path, "wb") as f:
            while True:
                n = int(inp.read(buf))
                if n <= 0:
                    break
                chunk = bytes((buf[i] & 0xFF) for i in range(n))
                f.write(chunk)
        return True
    except Exception:
        return False


def _uri_display_name(resolver, uri) -> Optional[str]:
    from jnius import autoclass  # type: ignore

    try:
        OpenableColumns = autoclass("android.provider.OpenableColumns")
        c = resolver.query(uri, None, None, None, None)
        if not c:
            return None
        try:
            if not c.moveToFirst():
                return None
            idx = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if idx < 0:
                return None
            s = c.getString(idx)
            return str(s) if s else None
        finally:
            c.close()
    except Exception:
        return None


def _copy_uri_to_cache(resolver, uri, cache_dir: str, idx: int) -> Optional[str]:
    try:
        inp = resolver.openInputStream(uri)
        if not inp:
            return None
        try:
            name = _uri_display_name(resolver, uri) or f"share_{idx}"
            fname = _safe_filename(name)
            out_path = os.path.join(
                cache_dir, f"{int(time.time() * 1000)}_{idx}_{fname}"
            )
            ok = _read_stream_to_path(inp, out_path)
            return out_path if ok and os.path.isfile(out_path) else None
        finally:
            inp.close()
    except Exception:
        return None


def _get_parcelable_extra_stream(intent):
    """EXTRA_STREAM для разных API."""
    from jnius import autoclass, cast  # type: ignore

    key = "android.intent.extra.STREAM"
    try:
        uri = intent.getParcelableExtra(key)
        if uri:
            return uri
    except Exception:
        pass
    try:
        Uri = autoclass("android.net.Uri")
        uri = intent.getParcelableExtra(key, Uri)
        return uri
    except Exception:
        return None


def _uris_from_clipdata(intent) -> List:
    """Новые приложения часто кладут content:// только в ClipData, без EXTRA_STREAM."""
    out: List = []
    try:
        clip = intent.getClipData()
        if clip is None:
            return out
        n = int(clip.getItemCount())
        for i in range(n):
            try:
                item = clip.getItemAt(i)
                if item is None:
                    continue
                uri = item.getUri()
                if uri:
                    out.append(uri)
            except Exception:
                continue
    except Exception:
        pass
    return out


def _get_parcelable_arraylist_streams(intent):
    from jnius import autoclass  # type: ignore

    key = "android.intent.extra.STREAM"
    try:
        lst = intent.getParcelableArrayListExtra(key)
        if lst:
            return lst
    except Exception:
        pass
    try:
        Uri = autoclass("android.net.Uri")
        lst = intent.getParcelableArrayListExtra(key, Uri)
        return lst
    except Exception:
        return None


def read_share_intent(activity=None, intent=None) -> Optional[SharePayload]:
    """
    Прочитать Intent (текущий у Activity или переданный из on_new_intent).
    Возвращает None, если это не SEND / SEND_MULTIPLE.
    """
    from jnius import autoclass  # type: ignore

    act = activity or _java_activity()
    if act is None:
        return None
    intent = intent or act.getIntent()
    if intent is None:
        return None
    action = str(intent.getAction() or "")
    Intent = autoclass("android.content.Intent")
    send = str(Intent.ACTION_SEND)
    send_mul = str(Intent.ACTION_SEND_MULTIPLE)

    if action not in (send, send_mul):
        return None

    resolver = act.getContentResolver()
    cache_dir = str(act.getCacheDir().getAbsolutePath())
    os.makedirs(cache_dir, exist_ok=True)

    text = ""
    try:
        tx = intent.getStringExtra("android.intent.extra.TEXT")
        if tx:
            text = str(tx)
    except Exception:
        pass
    try:
        subj = intent.getStringExtra("android.intent.extra.SUBJECT")
        if subj and not text:
            text = str(subj)
    except Exception:
        pass

    paths: List[str] = []

    if action == send_mul:
        lst = _get_parcelable_arraylist_streams(intent)
        if lst:
            n = int(lst.size())
            for i in range(n):
                uri = lst.get(i)
                if uri:
                    p = _copy_uri_to_cache(resolver, uri, cache_dir, i)
                    if p:
                        paths.append(p)
        if not paths:
            for idx, uri in enumerate(_uris_from_clipdata(intent)):
                p = _copy_uri_to_cache(resolver, uri, cache_dir, 200 + idx)
                if p:
                    paths.append(p)
    else:
        uri = _get_parcelable_extra_stream(intent)
        if uri:
            p = _copy_uri_to_cache(resolver, uri, cache_dir, 0)
            if p:
                paths.append(p)
        if not paths:
            for idx, uri in enumerate(_uris_from_clipdata(intent)):
                p = _copy_uri_to_cache(resolver, uri, cache_dir, 100 + idx)
                if p:
                    paths.append(p)

    if not paths and not (text and text.strip()):
        return None

    return SharePayload(file_paths=paths, text=text or "")


def toast(message: str, long: bool = False) -> None:
    from jnius import autoclass  # type: ignore
    from android.runnable import run_on_ui_thread  # type: ignore

    act = _java_activity()
    if act is None:
        return
    Toast = autoclass("android.widget.Toast")
    dur = Toast.LENGTH_LONG if long else Toast.LENGTH_SHORT

    def _show(*_a):
        try:
            t = Toast.makeText(act, str(message), dur)
            t.show()
        except Exception:
            pass

    try:
        run_on_ui_thread(_show)
    except Exception:
        _show()


def finish_activity() -> None:
    from android.runnable import run_on_ui_thread  # type: ignore

    act = _java_activity()

    def _fin(*_a):
        try:
            act.finish()
        except Exception:
            pass

    try:
        run_on_ui_thread(_fin)
    except Exception:
        _fin()


def is_share_intent(activity=None, intent=None) -> bool:
    """True, если Intent — «Поделиться» (не обязательно уже с данными)."""
    try:
        from jnius import autoclass  # type: ignore

        act = activity or _java_activity()
        if act is None:
            return False
        intent = intent or act.getIntent()
        if intent is None:
            return False
        Intent = autoclass("android.content.Intent")
        a = str(intent.getAction() or "")
        return a in (str(Intent.ACTION_SEND), str(Intent.ACTION_SEND_MULTIPLE))
    except Exception:
        return False


def bind_new_intent(_callback) -> None:
    """
    Устарело: второй activity_bind затирает on_activity_result (SAF).
    on_new_intent вешается в PortalAndroidApp._install_android_activity_bindings.
    """
    return
