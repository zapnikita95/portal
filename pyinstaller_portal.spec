# PyInstaller: из корня репозитория portal/
#   pip install pyinstaller
#   pyinstaller pyinstaller_portal.spec
#
# На macOS для .app: проверь права и quarantine (xattr -dr com.apple.quarantine dist/...).

import sys
from pathlib import Path

block_cipher = None
root = Path(SPECPATH).resolve()
assets = root / "assets"

datas = []
if assets.is_dir():
    datas.append((str(assets), "assets"))

hiddenimports = [
    "customtkinter",
    "PIL",
    "PIL.Image",
    "PIL.ImageTk",
    "PIL.ImageSequence",
    "pyperclip",
    "portal_config",
    "portal_clipboard_rich",
    "portal_widget",
    "portal_tk_compat",
]

if sys.platform == "darwin":
    hiddenimports.extend(["AppKit", "Foundation"])

a = Analysis(
    [str(root / "portal.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Portal",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False if sys.platform == "win32" else True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Portal",
)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Portal.app",
        icon=None,
        bundle_identifier="app.portal.desktop",
    )
