#!/usr/bin/env bash
# Сборка Portal.app и сжатого DMG для установки на macOS.
# Запуск из корня репозитория: ./scripts/build_mac_dmg.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "Только macOS (нужны PyInstaller .app и hdiutil)." >&2
  exit 1
fi

python3 -m pip install -q -r requirements.txt pyinstaller pillow pynput
python3 scripts/generate_branding_icons.py
pyinstaller -y pyinstaller_portal.spec

APP="$ROOT/dist/Portal.app"
ZIP="$ROOT/dist/Portal-macOS.zip"
DMG="$ROOT/dist/Portal-macOS.dmg"
test -d "$APP" || { echo "Нет $APP" >&2; exit 1; }

rm -f "$ZIP" "$DMG"
( cd "$ROOT/dist" && ditto -c -k --sequesterRsrc --keepParent Portal.app Portal-macOS.zip )
hdiutil create -volname "Portal" -srcfolder "$APP" -ov -format UDZO \
  -imagekey zlib-level=9 "$DMG"

echo "OK:"
echo "  $ZIP"
echo "  $DMG"
