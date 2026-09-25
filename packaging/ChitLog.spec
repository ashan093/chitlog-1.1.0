# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build for ChitLog 1.1.0 on Windows x64."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

# PyInstaller exposes SPECPATH as the directory containing this .spec file.
# ChitLog.spec lives in <project_root>/packaging, so one parent is the project root.
project_root = Path(SPECPATH).resolve().parent
entry_script = project_root / "app.py"
if not entry_script.is_file():
    raise FileNotFoundError(f"ChitLog entry script not found: {entry_script}")

# sqlcipher3 wheels are self-contained on supported Windows builds, but collect
# any adjacent native libraries if the wheel exposes them separately.
sqlcipher_binaries = collect_dynamic_libs("sqlcipher3")

analysis = Analysis(
    [str(entry_script)],
    pathex=[str(project_root)],
    binaries=sqlcipher_binaries,
    datas=[(str(project_root / "assets"), "assets")],
    hiddenimports=[
        "keyring.backends.Windows",
        "win32ctypes.pywin32",
        "win32ctypes.pywin32.pywintypes",
        "win32ctypes.pywin32.win32cred",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "unittest",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="ChitLog",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "assets" / "chit.ico"),
    version=str(project_root / "packaging" / "version_info.txt"),
    uac_admin=False,
    uac_uiaccess=False,
)

bundle = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="ChitLog",
)
