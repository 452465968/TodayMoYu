# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：在 Windows 上执行  build.bat  即可。

输出：dist/今天摸了吗.exe （单文件、无控制台窗口、带图标）
"""
from pathlib import Path

APP_NAME = "今天摸了吗"
ROOT = Path(SPECPATH).resolve()

a = Analysis(
    ["main.py"],
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
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                 # Qt 插件经 UPX 压缩后容易被杀软误报 / 加载失败
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,             # 桌面程序，不弹黑色控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "resources" / "app.ico"),
)
