#-*- mode: python ; coding: utf-8 -*-
"""构建主窗口、Qt 取用精灵与兼容取用窗，输出 onedir 目录。"""
import os

import PyInstaller
from PyInstaller.utils.hooks import collect_all
from tools.build_picker_icon import build as build_picker_icon

build_picker_icon()


CONTENTS_DIR = (
    {"contents_directory": "runtime"}
    if int(PyInstaller.__version__.split(".")[0]) >= 6
    else {}
)

datas = [("ui", "ui"), ("licenses", "licenses"), ("assistant_asr_worker.py", "."), ("draft_codec_worker.py", ".")]
binaries = []


hiddenimports = ["clr", "pythonnet"]

if os.path.isdir("brand-assets"):
    datas.append(("brand-assets", "brand-assets"))

#pywebview ships JS/CSS assets that PyInstaller cannot auto-detect.
try:
    wv_datas, wv_binaries, wv_hiddenimports = collect_all("webview")
    datas += wv_datas
    binaries += wv_binaries
    hiddenimports += wv_hiddenimports
except Exception:
    pass


for production_package in ("pyJianYingDraft", "pymediainfo"):
    production_datas, production_binaries, production_hiddenimports = collect_all(production_package)
    datas += production_datas
    binaries += production_binaries
    hiddenimports += production_hiddenimports

icon = "ui/app.ico"

a = Analysis(
    ["app_launcher.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "PyQt5", "PyQt6"],
    noarchive=False,
)
pyz = PYZ(a.pure)


a_pet = Analysis(
    ["desktop_pet.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6"],
    noarchive=False,
)
pyz_pet = PYZ(a_pet.pure)


a_picker = Analysis(
    ["floating_picker.py"],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide6", "PyQt5", "PyQt6"],
    noarchive=False,
)
pyz_picker = PYZ(a_picker.pure)



for analysis in (a, a_pet, a_picker):
    analysis.binaries = [entry for entry in analysis.binaries
                         if os.path.basename(entry[0]).lower() != "icuuc.dll"]

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BingyiGalCreativeWorkshop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon,
    **CONTENTS_DIR,
)
exe_picker = EXE(
    pyz_picker,
    a_picker.scripts,
    [],
    exclude_binaries=True,
    name="FloatingPicker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon,
    **CONTENTS_DIR,
)
exe_pet = EXE(
    pyz_pet,
    a_pet.scripts,
    [],
    exclude_binaries=True,
    name="IceWingCompanion",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=icon,
    **CONTENTS_DIR,
)
coll = COLLECT(
    exe,
    exe_pet,
    exe_picker,
    a.binaries,
    a.datas,
    a_pet.binaries,
    a_pet.datas,
    a_picker.binaries,
    a_picker.datas,
    strip=False,
    upx=False,
    name="BingyiGalCreativeWorkshop",
    **CONTENTS_DIR,
)

#Inference resources are delivered separately. Never copy tts_bundle or a GPU
#extension into the main application, including when legacy build variables exist.
