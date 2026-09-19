# -*- mode: python ; coding: utf-8 -*-
import os

# Fallback spec only. The release pipeline is packaging/stage_release.py.
_gui = os.path.abspath(os.path.join(SPECPATH, "..", "cnv_randomizer", "cnv_randomizer_gui.py"))
_cnv = os.path.abspath(os.path.join(SPECPATH, "..", "cnv_randomizer"))

a = Analysis(
    [_gui],
    pathex=[_cnv],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=True,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RandomizerForAll',
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
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='RandomizerForAll',
)
