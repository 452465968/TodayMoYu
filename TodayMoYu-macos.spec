# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置（macOS）：只产出 .app，不产出 exe。

执行：`python3 build_macos.py`（会自动调用本 spec）。
产物：dist/今天摸了吗.app，再由 build_macos.py 打成 zip。
"""
from pathlib import Path

APP_NAME = "今天摸了吗"
BUNDLE_ID = "com.shu1nm.todaymoyu"
ROOT = Path(SPECPATH).resolve()

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "rainmeter" / "TodayMoYu" / "TodayMoYu.ini"), "rainmeter/TodayMoYu"),
        (str(ROOT / "resources" / "app.ico"), "resources"),
        (str(ROOT / "resources" / "app.png"), "resources"),
        (str(ROOT / "resources" / "holiday_cn_2026.json"), "resources"),
    ],
    hiddenimports=["PySide6.QtNetwork", "PySide6.QtSvg"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
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
    icon=str(ROOT / "resources" / "app.icns"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)

app = BUNDLE(
    coll,
    name=f"{APP_NAME}.app",
    icon=str(ROOT / "resources" / "app.icns"),
    bundle_identifier=BUNDLE_ID,
    info_plist={
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleShortVersionString": "1.3.0",
        "CFBundleVersion": "1.3.0",
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.productivity",
        # 只作为状态栏 / 菜单栏常驻工具，不抢前台 Dock 焦点
        "LSUIElement": False,
        "NSHumanReadableCopyright": "Shu1nm LLC",
    },
)
