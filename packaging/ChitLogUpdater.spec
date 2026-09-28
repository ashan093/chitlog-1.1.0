# -*- mode: python ; coding: utf-8 -*-
"""One-file, windowless PyInstaller build for ChitLogUpdater.exe."""

from pathlib import Path


project_root = Path(SPECPATH).resolve().parent
entry_script = project_root / "packaging" / "updater_entry.py"
version_file = project_root / "packaging" / "version_info.txt"

if not entry_script.is_file():
    raise FileNotFoundError(f"Updater entry script is missing: {entry_script}")
if not version_file.is_file():
    raise FileNotFoundError(f"Version metadata is missing: {version_file}")


a = Analysis(
    [str(entry_script)],
    pathex=[str(project_root)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6",
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ChitLogUpdater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=True,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(version_file),
)
