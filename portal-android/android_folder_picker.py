"""
Выбор папки для сохранения через Storage Access Framework (OPEN_DOCUMENT_TREE).
Сохраняем content:// URI с persistable permission — путь вручную на Android часто недоступен.
"""

from __future__ import annotations

import os
from typing import Callable, Optional

REQ_OPEN_TREE = 9341
_on_result: Optional[Callable[[Optional[str]], None]] = None
_bound = False


def is_android_runtime() -> bool:
    return "ANDROID_ARGUMENT" in os.environ or os.path.exists("/system/build.prop")


def _java_activity():
    from jnius import autoclass  # type: ignore

    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    return PythonActivity.mActivity


def bind_folder_picker() -> None:
    """Повесить on_activity_result (один раз)."""
    global _bound
    if _bound or not is_android_runtime():
        return
    try:
        from android.activity import bind as activity_bind  # type: ignore
    except Exception:
        return

    def on_activity_result(request_code, result_code, intent):
        global _on_result
        cb = _on_result
        _on_result = None
        if request_code != REQ_OPEN_TREE or cb is None:
            return
        # Activity.RESULT_OK == -1
        if result_code != -1 or intent is None:
            cb(None)
            return
        try:
            uri = intent.getData()
            if uri is None:
                cb(None)
                return
            uri_str = uri.toString()
            try:
                from jnius import autoclass  # type: ignore

                act = _java_activity()
                Intent = autoclass("android.content.Intent")
                flags = int(
                    Intent.FLAG_GRANT_READ_URI_PERMISSION
                    | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                )
                act.takePersistableUriPermission(uri, flags)
            except Exception:
                pass
            cb(uri_str)
        except Exception:
            try:
                cb(None)
            except Exception:
                pass

    try:
        activity_bind(on_activity_result=on_activity_result)
        _bound = True
    except Exception:
        pass


def pick_receive_folder(callback: Callable[[Optional[str]], None]) -> None:
    """
    Открыть системный выбор папки. callback(uri_str | None).
    uri_str — content://... для DocumentsContract.
    """
    global _on_result
    if not is_android_runtime():
        callback(None)
        return
    bind_folder_picker()
    _on_result = callback
    try:
        from jnius import autoclass  # type: ignore
        from android.runnable import run_on_ui_thread  # type: ignore

        Intent = autoclass("android.content.Intent")
        act = _java_activity()
        if act is None:
            callback(None)
            return

        def run(*_a):
            try:
                i = Intent(Intent.ACTION_OPEN_DOCUMENT_TREE)
                i.addFlags(
                    int(
                        Intent.FLAG_GRANT_READ_URI_PERMISSION
                        | Intent.FLAG_GRANT_WRITE_URI_PERMISSION
                        | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION
                    )
                )
                act.startActivityForResult(i, REQ_OPEN_TREE)
            except Exception:
                global _on_result
                _on_result = None
                try:
                    callback(None)
                except Exception:
                    pass

        run_on_ui_thread(run)
    except Exception:
        _on_result = None
        callback(None)


def create_document_output_stream(tree_uri_str: str, display_name: str):
    """
    Создать файл в выбранном дереве и вернуть (java.io.OutputStream, android.net.Uri) или (None, None).
    """
    if not tree_uri_str or not is_android_runtime():
        return None, None
    try:
        from jnius import autoclass  # type: ignore

        act = _java_activity()
        if act is None:
            return None, None
        Uri = autoclass("android.net.Uri")
        DocumentsContract = autoclass("android.provider.DocumentsContract")
        tree = Uri.parse(tree_uri_str)
        cr = act.getContentResolver()
        doc_id = DocumentsContract.getTreeDocumentId(tree)
        parent_uri = DocumentsContract.buildDocumentUriUsingTree(tree, doc_id)
        mime = "application/octet-stream"
        new_uri = DocumentsContract.createDocument(cr, parent_uri, mime, display_name)
        if new_uri is None:
            return None, None
        out = cr.openOutputStream(new_uri)
        return out, new_uri
    except Exception:
        return None, None


def write_bytes_to_output_stream(out, data: bytes) -> bool:
    if out is None or not data:
        return True
    try:
        out.write(data)
        return True
    except Exception:
        pass
    try:
        out.write(bytearray(data))
        return True
    except Exception:
        pass
    try:
        for b in data:
            out.write(int(b) & 0xFF)
        return True
    except Exception:
        return False


def copy_path_to_java_stream(path: str, out) -> bool:
    try:
        with open(path, "rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                if not write_bytes_to_output_stream(out, chunk):
                    return False
        return True
    except Exception:
        return False


def android_cache_dir() -> str:
    if not is_android_runtime():
        return ""
    try:
        act = _java_activity()
        if act is None:
            return ""
        return str(act.getCacheDir().getAbsolutePath())
    except Exception:
        return ""


def close_java(obj) -> None:
    if obj is None:
        return
    try:
        obj.close()
    except Exception:
        pass
