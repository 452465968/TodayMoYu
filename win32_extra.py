# -*- coding: utf-8 -*-
"""今天摸了吗 · 系统集成（开机自启 / 桌面嵌入 / 工具窗口）

* Windows：ctypes + 注册表 HKCU\\Run + WorkerW 桌面图层，不依赖 pywin32。
* macOS：LaunchAgent（~/Library/LaunchAgents/*.plist）实现开机自启；
  「贴到桌面」依赖 Windows 的 WorkerW，macOS 上自动降级为普通置顶窗口。
* 其它平台：所有函数安全降级为 no-op，源码仍可运行。
"""
from __future__ import annotations

import ctypes
import os
import plistlib
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path

from core import APP_NAME

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"
SUPPORTS_AUTOSTART = IS_WINDOWS or IS_MACOS
LAUNCH_AGENT_ID = "com.shu1nm.todaymoyu"
LAUNCH_AGENT = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCH_AGENT_ID}.plist"

if IS_WINDOWS:
    _user32 = ctypes.windll.user32
    _user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.FindWindowW.restype = wintypes.HWND
    _user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND,
                                      wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.FindWindowExW.restype = wintypes.HWND
    _user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    _user32.SetParent.restype = wintypes.HWND
    _user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongW.restype = ctypes.c_long
    _user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    _user32.SetWindowLongW.restype = ctypes.c_long
    _user32.SendMessageTimeoutW.argtypes = [wintypes.HWND, wintypes.UINT,
                                            wintypes.WPARAM, wintypes.LPARAM,
                                            wintypes.UINT, wintypes.UINT,
                                            ctypes.POINTER(wintypes.DWORD)]
    _user32.SendMessageTimeoutW.restype = wintypes.LPARAM
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.GetParent.argtypes = [wintypes.HWND]
    _user32.GetParent.restype = wintypes.HWND
    _user32.EnumWindows.argtypes = [ctypes.c_void_p, wintypes.LPARAM]
    _user32.EnumWindows.restype = wintypes.BOOL
    _user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, wintypes.UINT]
    _user32.SetWindowPos.restype = wintypes.BOOL
else:
    _user32 = None

GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
HWND_BOTTOM = 1
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


# --------------------------------------------------------------------------- #
# 开机自启
# --------------------------------------------------------------------------- #
def launch_argv() -> list[str]:
    """开机自启要执行的命令行（跨平台，返回 argv 列表）。

    Windows 打包后用 exe 自身；macOS 打包后同理；源码运行时用当前解释器 + main.py。
    """
    if getattr(sys, "frozen", False):
        return [sys.executable, "--minimized"]
    exe = Path(sys.executable)
    pyw = exe.with_name("pythonw.exe")         # Windows 无控制台窗口
    runner = str(pyw if pyw.exists() else exe)
    script = Path(__file__).resolve().with_name("main.py")
    return [runner, str(script), "--minimized"]


def launch_command() -> str:
    """返回用于注册表 / 快捷方式的启动命令字符串。"""
    return subprocess.list2cmdline(launch_argv())


def set_auto_start(enable: bool) -> tuple[bool, str]:
    """开启 / 关闭开机自启。返回 (是否成功, 说明)。"""
    if IS_MACOS:
        return _mac_set_auto_start(enable)
    if not IS_WINDOWS:
        return False, "当前系统暂不支持自动设置开机自启，请用系统启动项手动添加"
    try:
        import winreg
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            if enable:
                winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(key, APP_NAME)
                except FileNotFoundError:
                    pass
        return True, "已开启开机自启" if enable else "已关闭开机自启"
    except Exception as exc:  # 权限 / 组策略拦截时给出可读提示
        return False, f"开机自启设置失败：{exc}"


def is_auto_start() -> bool:
    if IS_MACOS:
        return LAUNCH_AGENT.is_file()
    if not IS_WINDOWS:
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE) as key:
            winreg.QueryValueEx(key, APP_NAME)
        return True
    except Exception:
        return False


# --------------------------------------------------------------------------- #
# 桌面小组件：工具窗口 + 嵌入桌面
# --------------------------------------------------------------------------- #
def make_tool_window(hwnd: int) -> None:
    """不在任务栏 / Alt-Tab 里出现，且不抢焦点。"""
    if not IS_WINDOWS or not hwnd:
        return
    try:
        style = _user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        _user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                               style | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
        _user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    except Exception:
        pass


def find_desktop_workerw() -> int:
    """找到壁纸所在的 WorkerW 窗口句柄（Win10/Win11 通用做法）。"""
    if not IS_WINDOWS:
        return 0
    try:
        progman = _user32.FindWindowW("Progman", None)
        if not progman:
            return 0
        result = wintypes.DWORD(0)
        # 0x052C: 让 Progman 生成一个独立的 WorkerW 来承载壁纸
        _user32.SendMessageTimeoutW(progman, 0x052C, 0, 0, 0x0002, 1000,
                                    ctypes.byref(result))
        found = {"handle": 0}
        proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum(hwnd: int, _lparam: int) -> bool:
            shell = _user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None)
            if shell:
                nxt = _user32.FindWindowExW(None, hwnd, "WorkerW", None)
                if nxt:
                    found["handle"] = nxt
                    return False
            return True

        cb = proc_type(_enum)
        _user32.EnumWindows(ctypes.cast(cb, ctypes.c_void_p), 0)
        return int(found["handle"]) if found["handle"] else 0
    except Exception:
        return 0


def dock_to_desktop(hwnd: int) -> bool:
    """把小组件挂到桌面图层：按 Win+D 显示桌面时依然可见、不遮挡其它窗口。"""
    if not IS_WINDOWS or not hwnd:
        return False
    workerw = find_desktop_workerw()
    if not workerw:
        return False
    try:
        return bool(_user32.SetParent(hwnd, workerw))
    except Exception:
        return False


def undock_from_desktop(hwnd: int) -> bool:
    """从桌面图层取回，恢复为普通独立窗口。"""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        return bool(_user32.SetParent(hwnd, 0))
    except Exception:
        return False


def window_global_pos(hwnd: int) -> tuple[int, int] | None:
    """读取窗口真实的屏幕坐标（SetParent 之后 Qt 的 pos() 可能不准，用 Win32 直读）。"""
    if not IS_WINDOWS or not hwnd:
        return None
    try:
        rect = wintypes.RECT()
        if _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return int(rect.left), int(rect.top)
    except Exception:
        pass
    return None


def parent_origin(hwnd: int) -> tuple[int, int]:
    """父窗口客户区原点；贴到 WorkerW 后用于坐标换算。"""
    if not IS_WINDOWS or not hwnd:
        return 0, 0
    try:
        parent = _user32.GetParent(hwnd)
        if parent:
            rect = wintypes.RECT()
            if _user32.GetWindowRect(parent, ctypes.byref(rect)):
                return int(rect.left), int(rect.top)
    except Exception:
        pass
    return 0, 0


def move_window_global(hwnd: int, x: int, y: int) -> bool:
    """按屏幕坐标移动窗口（自动换算到父窗口坐标）。"""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        ox, oy = parent_origin(hwnd)
        return bool(_user32.SetWindowPos(hwnd, 0, x - ox, y - oy, 0, 0,
                                         SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOZORDER))
    except Exception:
        return False


def push_to_bottom(hwnd: int) -> None:
    if not IS_WINDOWS or not hwnd:
        return
    try:
        _user32.SetWindowPos(hwnd, HWND_BOTTOM, 0, 0, 0, 0,
                             SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# macOS：LaunchAgent 开机自启
# --------------------------------------------------------------------------- #
def _mac_set_auto_start(enable: bool) -> tuple[bool, str]:
    """通过 LaunchAgent plist 实现登录自启（不需要管理员权限）。

    写入后顺带尝试 `launchctl load/unload`，失败也不影响下次登录生效。
    """
    try:
        LAUNCH_AGENT.parent.mkdir(parents=True, exist_ok=True)
        if enable:
            payload = {
                "Label": LAUNCH_AGENT_ID,
                "ProgramArguments": launch_argv(),
                "RunAtLoad": True,
                "ProcessType": "Interactive",
                "LimitLoadToSessionType": "Aqua",
            }
            with LAUNCH_AGENT.open("wb") as fh:
                plistlib.dump(payload, fh)
            _launchctl("load", LAUNCH_AGENT)
            return True, "已开启开机自启"
        if LAUNCH_AGENT.exists():
            _launchctl("unload", LAUNCH_AGENT)
            LAUNCH_AGENT.unlink()
        return True, "已关闭开机自启"
    except Exception as exc:                       # 权限 / 沙盒拦截时给出可读提示
        return False, f"开机自启设置失败：{exc}"


def _launchctl(action: str, path: Path) -> None:
    try:
        subprocess.run(["launchctl", action, "-w", str(path)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=6, check=False)
    except Exception:
        pass


def is_macos() -> bool:
    return IS_MACOS


def platform_label() -> str:
    if IS_WINDOWS:
        return "Windows"
    if IS_MACOS:
        return "macOS"
    return sys.platform
