# -*- coding: utf-8 -*-
"""今天摸了吗 · 桌面壁纸主色提取（小组件「配色自动匹配壁纸」）

设计
----
* ``wallpaper_path()``：Windows 读注册表 ``HKCU\\Control Panel\\Desktop\\WallPaper``；
  macOS 用 ``osascript`` 问 System Events（不需要额外依赖，也不需要管理员权限）。
* ``dominant_hue()``：把图片缩到 64×64，按「饱和度加权」的色相向量平均求主色相，
  跳过近灰 / 过暗 / 过亮像素——纯灰壁纸返回 None，由调用方回退主题默认配色。
* ``auto_hues()``：带 TTL 缓存（默认 10 分钟），壁纸路径或文件变化时才重新解析，
  因此可以安全地在每次重绘时调用。

只返回色相角：``theme.palette()`` 只替换色相、保留明度与饱和度，
所以无论壁纸多鲜艳，文字对比度都不会被破坏。
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
import time
from pathlib import Path

TTL_SECONDS = 600.0          # 同一张壁纸 10 分钟内不重复解析
ANALOGOUS_OFFSET = 25        # 副色 = 主色 +25°（邻近色，整体协调且不刺眼）
SAMPLE_EDGE = 64             # 缩略图边长：64×64 = 4096 像素已足够代表主色调

_cache: dict[str, object] = {"path": None, "mtime": 0.0, "hues": None, "ts": 0.0}


# --------------------------------------------------------------------------- #
# 壁纸路径
# --------------------------------------------------------------------------- #
def _windows_wallpaper() -> str | None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Control Panel\Desktop",
                            0, winreg.KEY_QUERY_VALUE) as key:
            value, _kind = winreg.QueryValueEx(key, "WallPaper")
        path = str(value).strip().strip('"')
        if path and path.lower() != "none" and Path(path).is_file():
            return path
    except Exception:
        pass
    return None


def _macos_wallpaper() -> str | None:
    """System Events 取当前桌面图片；动态壁纸会返回 .heic，QImage 读不了就回退。"""
    for script in ('tell application "System Events" to get picture of desktop 1',
                   'tell application "System Events" to get picture of every desktop'):
        try:
            out = subprocess.run(["osascript", "-e", script],
                                 capture_output=True, text=True, timeout=8)
        except Exception:
            continue
        if out.returncode != 0:
            continue
        for line in out.stdout.replace("\r", "\n").split("\n"):
            path = line.strip().strip('"')
            # 多桌面时是 "a.jpg, b.jpg" 这样的逗号列表，取第一张存在的
            for item in path.split(", "):
                item = item.strip().strip('"')
                if item and Path(item).is_file():
                    return item
    return None


def wallpaper_path() -> str | None:
    """当前桌面壁纸的绝对路径；取不到返回 None。

    环境变量 ``MOYU_WALLPAPER`` 可覆盖（便于测试与手动指定）。
    """
    override = os.environ.get("MOYU_WALLPAPER")
    if override:
        return override if Path(override).is_file() else None
    if sys.platform == "win32":
        return _windows_wallpaper()
    if sys.platform == "darwin":
        return _macos_wallpaper()
    return None


# --------------------------------------------------------------------------- #
# 主色相
# --------------------------------------------------------------------------- #
def dominant_hue(image) -> int | None:
    """从 QImage 求主色相（0-359）；没有明显彩色像素时返回 None。"""
    try:
        img = image.scaled(SAMPLE_EDGE, SAMPLE_EDGE)
    except Exception:
        return None
    sin_sum = cos_sum = weight = 0.0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            h, s, l, _a = c.getHslF()
            # 忽略近灰（无彩色）、过暗、过亮（白底 / 黑边）像素
            if h < 0 or s < 0.15 or l < 0.08 or l > 0.92:
                continue
            w = s * s                      # 饱和度越高越能代表「壁纸的颜色」
            angle = 2.0 * math.pi * h
            sin_sum += math.sin(angle) * w
            cos_sum += math.cos(angle) * w
            weight += w
    if weight <= 1e-6:
        return None
    hue = math.degrees(math.atan2(sin_sum, cos_sum)) % 360.0
    return int(round(hue)) % 360


def hues_from_image(path: str | None) -> tuple[int, int, int] | None:
    """图片 → (主色相, 副色相, 背景色相)；读取失败 / 无彩色返回 None。"""
    if not path:
        return None
    try:
        from PySide6.QtGui import QImage
        img = QImage(str(path))
        if img.isNull():
            return None
    except Exception:
        return None
    hue = dominant_hue(img)
    if hue is None:
        return None
    return hue, (hue + ANALOGOUS_OFFSET) % 360, hue


# --------------------------------------------------------------------------- #
# 对外：带缓存
# --------------------------------------------------------------------------- #
def auto_hues(force: bool = False) -> tuple[int, int, int] | None:
    """当前壁纸推导出的三个色相；缓存 TTL 内直接复用上次结果。"""
    now = time.time()
    path = wallpaper_path()
    try:
        mtime = Path(path).stat().st_mtime if path else 0.0
    except OSError:
        mtime = 0.0

    fresh = (not force
             and _cache["path"] == path
             and _cache["mtime"] == mtime
             and now - float(_cache["ts"]) < TTL_SECONDS)
    if fresh:
        return _cache["hues"]        # type: ignore[return-value]

    hues = hues_from_image(path)
    _cache.update(path=path, mtime=mtime, hues=hues, ts=now)
    return hues


def reset_cache() -> None:
    """测试 / 手动重新匹配时清空缓存。"""
    _cache.update(path=None, mtime=0.0, hues=None, ts=0.0)


def describe() -> str:
    """给设置页看的一行说明（当前壁纸路径 + 命中的色相）。"""
    path = wallpaper_path()
    if not path:
        return "未读取到桌面壁纸（纯色壁纸或系统限制），将沿用当前配色"
    hues = auto_hues()
    if not hues:
        return f"壁纸 {Path(path).name} 没有明显主色，将沿用当前配色"
    return f"壁纸 {Path(path).name} → 主色相 {hues[0]}°（副色 {hues[1]}°）"
