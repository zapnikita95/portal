#!/usr/bin/env python3
"""После `flutter create`: ключи для локальных уведомлений при приёме на iOS."""
from __future__ import annotations

import plistlib
from pathlib import Path

PLIST = Path("ios/Runner/Info.plist")


def main() -> None:
    if not PLIST.is_file():
        raise SystemExit(f"Нет {PLIST} — сначала flutter create --platforms=ios")

    with PLIST.open("rb") as f:
        pl = plistlib.load(f)

    changed = False
    if "NSUserNotificationsUsageDescription" not in pl:
        pl["NSUserNotificationsUsageDescription"] = (
            "Показывать, что файл или текст с ПК приняты в Portal."
        )
        changed = True

    if changed:
        with PLIST.open("wb") as f:
            plistlib.dump(pl, f)
        print("Info.plist: добавлен NSUserNotificationsUsageDescription.")
    else:
        print("Info.plist: без изменений.")


if __name__ == "__main__":
    main()
