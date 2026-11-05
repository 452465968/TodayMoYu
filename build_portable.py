# -*- coding: utf-8 -*-
"""构建「今天摸了吗」Windows 免安装压缩包（可在 macOS / Linux 上执行）。

原理：Windows 官方 embeddable Python + Windows 版 PySide6 wheel + 本项目源码，
全部解压到一个目录，配好 python311._pth，用户解压后双击 Run.bat 即可运行，
不需要安装 Python、不需要 pip、不需要 VC++ 运行库（Qt wheel 已自带）。

用法：
    python3 build_portable.py                    # 自动下载依赖并打包
    python3 build_portable.py --cache /tmp/moyu_win_dl   # 用已下载好的缓存
    python3 build_portable.py --output /path/to/x.zip

产物：../今天摸了吗_Windows免安装版.zip（默认，与项目目录同级）
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_CACHE = Path("/tmp/moyu_win_dl")
PACKAGE_NAME = "TodayMoYu-Windows-Portable"

PY_EMBED_URL = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip"
PY_EMBED_FILE = "python-3.11.9-embed-amd64.zip"
# 固定到已验证的 6.8.3 win_amd64 / cp39-abi3（兼容 Python 3.11 embeddable）
WHEELS = {
    "PySide6_Essentials-6.8.3-cp39-abi3-win_amd64.whl":
        "https://pypi.tuna.tsinghua.edu.cn/packages/8e/0f/5d8c6da7586e57ee032643e0c0e62335ef1a1add1a980160ddd1654f1d8d/PySide6_Essentials-6.8.3-cp39-abi3-win_amd64.whl",
    "shiboken6-6.8.3-cp39-abi3-win_amd64.whl":
        "https://pypi.tuna.tsinghua.edu.cn/packages/aa/29/e77f3fba5337f2d98f977eece0fd24cda6cf7d83be2699514d2ca1d34f6c/shiboken6-6.8.3-cp39-abi3-win_amd64.whl",
}

SOURCE_FILES = ["main.py", "core.py", "theme.py", "ui_main.py",
                "ui_settings.py", "ui_widget.py", "win32_extra.py"]
PTH_CONTENT = "\r\n".join([
    "python311.zip", ".", "Lib\\site-packages", "app",
    "# import site stays disabled on purpose (embeddable distribution)",
    "",
])

README_TXT = """今天摸了吗 · Windows 免安装版
========================================

【怎么用】
1. 把整个文件夹解压到任意位置（务必保持目录结构，不要只复制 exe）。
2. 双击【今天摸了吗.exe】即可启动 —— 这是真正的 Windows 可执行文件，
   双击不会出现黑色控制台窗口，程序会在系统托盘常驻并打开主窗口。
   若中文文件名在你的解压软件里显示乱码，双击 TodayMoYu.exe（完全相同）。
3. 也可以双击 Run.bat 启动；排障用 Run-Debug.bat；双击 SelfCheck.bat
   可逐个检查 Python / Qt / 项目模块是否都能正常导入。

【exe 是什么】
今天摸了吗.exe 是用 Go 交叉编译的 Windows GUI 启动器（PE32+ / x86-64），
双击后唤起同目录 runtime\pythonw.exe 运行 runtime\app\main.py，随后退出。
因此它需要同目录的 runtime 文件夹（Python 运行时与 Qt 库都在里面）。
如果要「单文件、可脱离目录」的 exe，请在 Windows 上执行项目里的 build.bat
（PyInstaller 只能在 Windows 上产出 Windows 可执行文件）。

【需要装什么吗】
不需要。Python 3.11 运行时、PySide6 / Qt 运行库、VC++ 运行库都已经放在
runtime 文件夹里。不用装 Python，不用 pip install，不用联网，不用管理员权限。
支持 Windows 10 / 11 64 位。

【常用功能】
- 主窗口：今日混底薪【工资】、已摸鱼时长实时跳动；设置里可改薪资与工时。
- 桌面小组件：点主窗口「桌面小组件」，或托盘菜单开启；右键可置顶 / 贴桌面。
- 调休：设置 → 工时 → 调休安排，选「休息日 + 补班日」添加。
  休息日不计摸鱼时长但按满勤补算（不扣薪），补班日正常实时计薪。
- 薪资联动：按月薪模式修改月薪后，日薪会按
  「月薪 ÷ 月计薪天数 ÷ 时薪折算工时 × 每日有效工时」立即重算并保存，
  重新打开也不会残留旧值。
- 开机自启：设置 → 外观与系统 → 勾选「开机自动启动」。

【数据与配置】
%APPDATA%\\今天摸了吗\\ 下的 config.json / state.json / widget.txt / widget.json。
卸载时直接删除本文件夹即可，不会写注册表（除非你开了开机自启，
可在设置里取消勾选）。

【可选：Rainmeter 桌面小组件】
把 app\\rainmeter\\TodayMoYu 复制到
%USERPROFILE%\\Documents\\Rainmeter\\Skins\\TodayMoYu\\，
主程序会自动把实时数据写到该目录。

【源码与完整文档】
app\\README.md。也可以在项目目录用 python main.py 从源码运行，
或在 Windows 上执行 build.bat 生成单文件 exe。
"""


def download(url: str, target: Path) -> None:
    if target.exists() and target.stat().st_size > 1024:
        print(f"  使用缓存 {target.name} ({target.stat().st_size/1024/1024:.1f} MB)")
        return
    print(f"  下载 {target.name} ...")
    req = urllib.request.Request(url, headers={"User-Agent": "TodayMoYu-Build/1.0"})
    with urllib.request.urlopen(req, timeout=300) as resp, target.open("wb") as out:
        shutil.copyfileobj(resp, out)
    print(f"  完成 {target.stat().st_size/1024/1024:.1f} MB")


def ensure_launcher(cache: Path) -> Path:
    """优先复用已编译的 Windows 启动器，否则用 Go 现场交叉编译。"""
    exe = cache / "TodayMoYu.exe"
    if exe.exists() and exe.stat().st_size > 100_000:
        print(f"  使用启动器 {exe.name} ({exe.stat().st_size/1024/1024:.1f} MB)")
        return exe
    go = os.environ.get("GO_BIN") or shutil.which("go")
    if not go:
        raise RuntimeError(
            "缺少 Windows 启动器：请把 TodayMoYu.exe 放到缓存目录，或安装 Go 并设置 GO_BIN 后重试")
    print("  用 Go 交叉编译 Windows GUI 启动器 ...")
    env = os.environ.copy()
    env.update(GOOS="windows", GOARCH="amd64", CGO_ENABLED="0",
               GOPROXY="off", GOTOOLCHAIN="local")
    subprocess.run([go, "build", "-ldflags=-H windowsgui -s -w",
                    "-o", str(exe), "."],
                   cwd=str(ROOT / "launcher"), env=env, check=True)
    return exe


def build(cache: Path, output: Path) -> None:
    stage = Path("/tmp/moyu_win_stage") / PACKAGE_NAME
    if stage.parent.exists():
        shutil.rmtree(stage.parent)
    runtime = stage / "runtime"
    app_dir = runtime / "app"
    site = runtime / "Lib" / "site-packages"
    for p in (runtime, app_dir, site):
        p.mkdir(parents=True, exist_ok=True)

    cache.mkdir(parents=True, exist_ok=True)
    print("=== 1/5 准备依赖 ===")
    download(PY_EMBED_URL, cache / PY_EMBED_FILE)
    for name, url in WHEELS.items():
        download(url, cache / name)
    launcher_exe = ensure_launcher(cache)

    print("=== 2/5 展开运行时 ===")
    with zipfile.ZipFile(cache / PY_EMBED_FILE) as z:
        z.extractall(runtime)
    for name in WHEELS:
        with zipfile.ZipFile(cache / name) as z:
            z.extractall(site)

    # 去掉开发用的 .lib 静态库（dist-info 保留，避免影响 importlib.metadata）
    for lib in site.glob("**/*.lib"):
        lib.unlink(missing_ok=True)

    print("=== 3/5 写 _pth / 启动脚本 / 源码 ===")
    pth = runtime / "python311._pth"
    pth.write_bytes(PTH_CONTENT.encode("ascii"))
    (stage / "Run.bat").write_bytes(
        (b"@echo off\r\ncd /d \"%~dp0\"\r\n"
         b"start \"\" \"runtime\\pythonw.exe\" \"runtime\\app\\main.py\" %*\r\n"))
    (stage / "Run-Debug.bat").write_bytes(
        (b"@echo off\r\ncd /d \"%~dp0\"\r\n"
         b"\"runtime\\python.exe\" \"runtime\\app\\main.py\" %*\r\n"
         b"echo.\r\necho [Exit code: %errorlevel%]\r\npause\r\n"))
    # 自检：逐个导入 Qt 与项目模块，Windows 上双击即可看到结果
    selfcheck = (
        "import sys; print('Python', sys.version); "
        "import PySide6; print('PySide6', PySide6.__version__); "
        "from PySide6 import QtCore,QtGui,QtWidgets,QtNetwork; print('Qt', QtCore.qVersion()); "
        "import core,theme,ui_main,ui_settings,ui_widget,win32_extra,main; "
        "print('All project modules OK')")
    (stage / "SelfCheck.bat").write_bytes(
        ("@echo off\r\ncd /d \"%~dp0\"\r\n"
         "\"runtime\\python.exe\" -c \"" + selfcheck + "\"\r\n"
         "echo.\r\necho [Exit code: %errorlevel%]\r\npause\r\n").encode("ascii"))
    (stage / "README.txt").write_bytes(b"\xef\xbb\xbf" + README_TXT.encode("utf-8"))
    # 双击即运行的 Windows exe（中文名 + ASCII 备份，内容完全相同）
    shutil.copy2(launcher_exe, stage / "今天摸了吗.exe")
    shutil.copy2(launcher_exe, stage / "TodayMoYu.exe")

    for name in SOURCE_FILES:
        shutil.copy2(ROOT / name, app_dir / name)
    res = app_dir / "resources"
    res.mkdir(parents=True, exist_ok=True)
    for name in ("app.ico", "app.png"):
        shutil.copy2(ROOT / "resources" / name, res / name)
    rain = app_dir / "rainmeter" / "TodayMoYu"
    rain.mkdir(parents=True, exist_ok=True)
    shutil.copy2(ROOT / "rainmeter" / "TodayMoYu" / "TodayMoYu.ini", rain / "TodayMoYu.ini")
    shutil.copy2(ROOT / "README.md", app_dir / "README.md")
    shutil.copy2(ROOT / "requirements.txt", app_dir / "requirements.txt")

    print("=== 4/5 静态校验 ===")
    required = [
        runtime / "python.exe", runtime / "pythonw.exe",
        runtime / "python311.dll", runtime / "python311.zip",
        runtime / "python311._pth",
        site / "PySide6" / "__init__.py",
        site / "PySide6" / "QtCore.pyd", site / "PySide6" / "QtGui.pyd",
        site / "PySide6" / "QtWidgets.pyd", site / "PySide6" / "QtNetwork.pyd",
        site / "PySide6" / "plugins" / "platforms" / "qwindows.dll",
        site / "PySide6" / "msvcp140.dll",
        site / "shiboken6" / "Shiboken.pyd",
        site / "shiboken6" / "shiboken6.abi3.dll",
        stage / "Run.bat", stage / "Run-Debug.bat", stage / "SelfCheck.bat",
        stage / "README.txt", stage / "今天摸了吗.exe", stage / "TodayMoYu.exe",
    ] + [app_dir / n for n in SOURCE_FILES]
    missing = [str(p.relative_to(stage)) for p in required if not p.is_file()]
    if missing:
        raise RuntimeError("缺少关键文件: " + ", ".join(missing))

    pe_files = [runtime / "pythonw.exe", runtime / "python311.dll",
                site / "PySide6" / "QtCore.pyd",
                site / "PySide6" / "plugins" / "platforms" / "qwindows.dll",
                stage / "今天摸了吗.exe", stage / "TodayMoYu.exe"]
    for p in pe_files:
        if p.read_bytes()[:2] != b"MZ":
            raise RuntimeError(f"不是 Windows PE 文件: {p}")
    for name in ("Run.bat", "Run-Debug.bat", "SelfCheck.bat"):
        raw = (stage / name).read_bytes()
        if b"\r\n" not in raw or any(b > 127 for b in raw):
            raise RuntimeError(f"{name} 必须是 CRLF + ASCII")
    print(f"  校验通过：{len(required)} 个关键文件齐全，PE / CRLF 检查通过")

    print("=== 5/5 打包 zip ===")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                z.write(path, Path(PACKAGE_NAME) / path.relative_to(stage))
    size = output.stat().st_size
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    (output.with_suffix(".zip.sha256")).write_text(
        f"{digest}  {output.name}\n", encoding="utf-8")
    print(f"  产物: {output}  ({size/1024/1024:.1f} MB)")
    print(f"  SHA256: {digest}")
    print(f"  文件数: {sum(1 for p in stage.rglob('*') if p.is_file())}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--output", type=Path,
                    default=ROOT.parent / "今天摸了吗_Windows免安装版.zip")
    args = ap.parse_args()
    build(args.cache, args.output.resolve())


if __name__ == "__main__":
    sys.exit(main())
