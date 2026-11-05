# -*- coding: utf-8 -*-
"""今天摸了吗 · 自定义配色 / 小组件无级缩放 / macOS 平台适配 的单元测试

不联网；涉及 Qt 的用例用 importorskip，保证在无 PySide6 的环境里也能跑其余用例。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

import win32_extra as win
from core import (
    WIDGET_SCALE_MAX, WIDGET_SCALE_MIN, Settings, effective_hues,
)

# --------------------------------------------------------------------------- #
# 一、配色字段：宽容解析 / 范围校验 / 默认跟随主题
# --------------------------------------------------------------------------- #
def test_hue_fields_default_to_follow_theme():
    s = Settings()
    assert (s.accent_hue, s.accent2_hue, s.bg_hue) == (-1, -1, -1)
    assert s.widget_follow_main is True
    assert (s.widget_accent_hue, s.widget_accent2_hue, s.widget_bg_hue) == (-1, -1, -1)


@pytest.mark.parametrize("raw,expect", [
    (0, 0), (359, 359), (180, 180),
    (-1, -1), (-99, -1), (360, -1), (1000, -1),
    ("200", 200), ("abc", -1), (None, -1), (12.7, 12),
])
def test_hue_parsing_is_tolerant(raw, expect):
    s = Settings.from_dict({"accent_hue": raw})
    assert s.accent_hue == expect


def test_hue_roundtrip_through_dict():
    s = Settings.from_dict({
        "accent_hue": 210, "accent2_hue": 12, "bg_hue": 285,
        "widget_follow_main": False,
        "widget_accent_hue": 330, "widget_accent2_hue": 45, "widget_bg_hue": 100,
    })
    assert (s.accent_hue, s.accent2_hue, s.bg_hue) == (210, 12, 285)
    assert s.widget_follow_main is False
    assert (s.widget_accent_hue, s.widget_accent2_hue, s.widget_bg_hue) == (330, 45, 100)


def test_effective_hues_prefers_widget_values_only_when_not_following():
    s = Settings.from_dict({"accent_hue": 10, "accent2_hue": 20, "bg_hue": 30,
                            "widget_accent_hue": 100, "widget_accent2_hue": 110,
                            "widget_bg_hue": 120})
    assert effective_hues(s) == (10, 20, 30)
    assert effective_hues(s, widget=True) == (10, 20, 30)   # 默认跟随主界面
    s.widget_follow_main = False
    assert effective_hues(s, widget=True) == (100, 110, 120)
    assert effective_hues(s) == (10, 20, 30)                # 互不影响


# --------------------------------------------------------------------------- #
# 二、小组件无级缩放：连续取值 / 边界钳制 / 持久化
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expect", [
    (1.0, 1.0), (0.873, 0.873), (2.456, 2.456), (0.5, 0.5), (3.0, 3.0),
    (0.1, WIDGET_SCALE_MIN), (9.0, WIDGET_SCALE_MAX),
    ("1.25", 1.25), ("oops", 1.0),
])
def test_widget_scale_is_continuous_and_clamped(raw, expect):
    s = Settings.from_dict({"widget_scale": raw})
    assert s.widget_scale == pytest.approx(expect)


def test_widget_opacity_clamped_to_new_range():
    assert Settings.from_dict({"widget_opacity": 0.15}).widget_opacity == pytest.approx(0.15)
    assert Settings.from_dict({"widget_opacity": 0.05}).widget_opacity == pytest.approx(0.15)
    assert Settings.from_dict({"widget_opacity": 1.0}).widget_opacity == pytest.approx(1.0)


def test_save_and_reload_keeps_colors_and_scale(tmp_path: Path):
    s = Settings.from_dict({"accent_hue": 137, "bg_hue": 42,
                            "widget_scale": 1.234, "widget_opacity": 0.667,
                            "widget_follow_main": False, "widget_accent_hue": 300})
    s.save(tmp_path)
    back = Settings.load(tmp_path)
    assert (back.accent_hue, back.bg_hue) == (137, 42)
    assert back.widget_scale == pytest.approx(1.234)
    assert back.widget_opacity == pytest.approx(0.667)
    assert back.widget_follow_main is False
    assert back.widget_accent_hue == 300


# --------------------------------------------------------------------------- #
# 三、调色板推导（需要 PySide6）
# --------------------------------------------------------------------------- #
def test_palette_recolors_only_hue():
    theme = pytest.importorskip("theme")
    from PySide6.QtGui import QColor

    base = theme.palette("aurora")
    custom = theme.palette("aurora", accent_hue=210, accent2_hue=120, bg_hue=280)

    # 文字色不动，保证可读性
    assert custom["text"] == base["text"]
    assert custom["muted"] == base["muted"]
    # 主色 / 副色换到目标色相
    assert abs(QColor(custom["accent"]).hue() - 210) <= 2
    assert abs(QColor(custom["accent2"]).hue() - 120) <= 2
    # 明度保持不变（对比度不被破坏）
    assert abs(QColor(custom["accent"]).lightness() - QColor(base["accent"]).lightness()) <= 2


def test_palette_background_stays_light():
    theme = pytest.importorskip("theme")
    from PySide6.QtGui import QColor

    for hue in (0, 60, 120, 200, 300):
        pal = theme.palette("aurora", bg_hue=hue)
        for stop in pal["stops"].split("|"):
            assert QColor(stop).lightness() >= 235, f"背景过暗：{stop}"


def test_palette_without_overrides_matches_theme():
    theme = pytest.importorskip("theme")
    assert theme.palette("mint") == theme.theme("mint")


def test_palette_for_respects_widget_follow():
    pytest.importorskip("PySide6")
    theme = pytest.importorskip("theme")
    cfg = Settings.from_dict({"accent_hue": 30, "widget_follow_main": True,
                              "widget_accent_hue": 300})
    assert theme.palette_for(cfg, widget=True)["accent"] == theme.palette_for(cfg)["accent"]
    cfg.widget_follow_main = False
    assert theme.palette_for(cfg, widget=True)["accent"] != theme.palette_for(cfg)["accent"]


# --------------------------------------------------------------------------- #
# 四、macOS 平台适配
# --------------------------------------------------------------------------- #
def test_platform_flags_are_consistent():
    assert win.IS_WINDOWS == (sys.platform == "win32")
    assert win.IS_MACOS == (sys.platform == "darwin")
    assert win.SUPPORTS_AUTOSTART == (win.IS_WINDOWS or win.IS_MACOS)


def test_launch_argv_points_to_this_project():
    argv = win.launch_argv()
    assert argv and all(isinstance(x, str) for x in argv)
    assert "--minimized" in argv
    if not getattr(sys, "frozen", False):
        assert any(a.endswith("main.py") for a in argv)
        assert Path(next(a for a in argv if a.endswith("main.py"))).is_file()


def test_launch_agent_path_is_in_user_library():
    assert win.LAUNCH_AGENT.name == "com.shu1nm.todaymoyu.plist"
    assert win.LAUNCH_AGENT.parent == Path.home() / "Library" / "LaunchAgents"


def test_non_windows_desktop_dock_degrades_gracefully():
    if win.IS_WINDOWS:
        pytest.skip("Windows 上贴桌面是原生能力")
    assert win.find_desktop_workerw() == 0
    assert win.dock_to_desktop(123) is False
    assert win.undock_from_desktop(123) is False
    assert win.window_global_pos(123) is None
    win.make_tool_window(123)      # 不应抛异常


# --------------------------------------------------------------------------- #
# 五、导入冒烟：UI 模块必须能完整 import（曾因 QColorDialog 放错模块导致启动崩溃）
# --------------------------------------------------------------------------- #
def test_ui_modules_import_cleanly():
    pytest.importorskip("PySide6")
    import importlib

    for name in ("theme", "ui_main", "ui_widget", "ui_settings", "main"):
        mod = importlib.import_module(name)
        assert mod is not None


def test_qcolordialog_imported_from_qtwidgets():
    pytest.importorskip("PySide6")
    import ui_settings
    from PySide6.QtWidgets import QColorDialog

    assert ui_settings.QColorDialog is QColorDialog


def test_macos_menubar_uses_global_qmenubar():
    pytest.importorskip("PySide6")
    import inspect

    import main as main_mod
    src = inspect.getsource(main_mod.MoyuApp._init_macos_menubar)
    assert "QMenuBar()" in src, "macOS 菜单栏必须用无父级 QMenuBar（QApplication 没有 menuBar()）"
    assert "self._mac_menubar" in src, "菜单栏必须保留引用，避免被 GC 后消失"
