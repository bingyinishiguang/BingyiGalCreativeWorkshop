#-*- mode: python ; coding: utf-8 -*-
"""构建主窗口、Qt 取用精灵与兼容取用窗，输出 onedir 目录。"""
import os

import PyInstaller
from PyInstaller.utils.hooks import collect_all

#PyInstaller 6 起，onedir 的私有运行库目录默认叫 `_internal`。
CONTENTS_DIR = (
    {"contents_directory": "runtime"}
    if int(PyInstaller.__version__.split(".")[0]) >= 6
    else {}
)

datas = [("ui", "ui"), ("licenses", "licenses")]
binaries = []
#pythonnet（clr）是 pywebview 在 Windows 上的 UI 线程封送（Form.Invoke）依赖，
#显式加入 hiddenimports，避免打包版缺失导致拖动/缩放失效。
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

#草稿生成模板 JSON 与 MediaInfo 动态库必须随冻结版打包。
for production_package in ("pyJianYingDraft", "pymediainfo"):
    production_datas, production_binaries, production_hiddenimports = collect_all(production_package)
    datas += production_datas
    binaries += production_binaries
    hiddenimports += production_hiddenimports

icon = "brand-assets/app.ico" if os.path.isfile("brand-assets/app.ico") else None

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

#新默认入口：「冰翼取用精灵」（PySide6/QML 桌宠 + 立绘总览）。
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

#tkinter 取用窗暂时保留为兼容兜底，不再是主入口。
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

#Qt 6 使用 Windows 自带 ICU。PATH 中 Poppler 的同名 DLL 依赖 icudt78，
#收入运行目录会遮蔽系统 ICU，导致 QtCore 在启动时无法加载。
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
