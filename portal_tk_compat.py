"""
Совместимость Tk / tkinterdnd2 с CustomTkinter на Python 3.13+.

В 3.13 у tkinter.Tk MRO: (Tk, Misc, Wm, object) — без BaseWidget.
tkinterdnd2 через TkinterDnD._require() вешает drop_target_register и др. на BaseWidget.
Вызывай ensure_tkdnd_tk_misc_patch() **сразу после** TkinterDnD._require(...), иначе методов
ещё нет на BaseWidget при первом вызове — и одноразовый флаг больше не даст их скопировать.
"""

from __future__ import annotations

import tkinter as tk


def ensure_tkdnd_tk_misc_patch() -> None:
    """
    Скопировать DnD-методы с BaseWidget на Misc, если их ещё нет.
    Безопасно вызывать многократно (после каждого TkinterDnD._require).
    """
    for name in dir(tk.BaseWidget):
        if name.startswith("__"):
            continue
        if not any(x in name for x in ("dnd", "drop", "drag", "subst")):
            continue
        if hasattr(tk.Misc, name):
            continue
        try:
            setattr(tk.Misc, name, getattr(tk.BaseWidget, name))
        except Exception:
            pass
