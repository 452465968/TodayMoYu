# -*- coding: utf-8 -*-
"""v1.5.0 新特性回归：头部固定不裁切、刷新 10ms / 8 位小数、壁纸自动配色。"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

qt_app = None


@pytest.fixture(scope="module")
def qapp():
    global qt_app
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["HOME"] = os.environ.get("MOYU_TEST_HOME") or tempfile.mkdtemp(
        prefix="moyu_v150_home_")
    if qt_app is None:
        from PySide6.QtWidgets import QApplication
        import main as main_mod
        main_mod.SERVER_NAME += f"_t150_{os.getpid()}"
        qt_app = QApplication.instance() or QApplication(sys.argv[:1])
    return qt_app


@pytest.fixture(scope="module")
def app(qapp):
    from main import MoyuApp
    return MoyuApp(["--no-calendar", "--minimized", "--no-update"])


# --------------------------------------------------------------------------- #
# 一、刷新间隔解锁 + 8 位小数（纯逻辑）
# --------------------------------------------------------------------------- #
def test_refresh_floor_is_10ms():
    from core import REFRESH_MIN_MS, validate_refresh_interval
    assert REFRESH_MIN_MS == 10
    ok, msg, ms = validate_refresh_interval(10, "ms")
    assert ok and ms == 10
    ok, msg, ms = validate_refresh_interval(0.01, "s")
    assert ok and ms == 10
    ok, msg, ms = validate_refresh_interval(5, "ms")          # 低于下限 → 修正
    assert not ok and ms == 10
    ok, _msg, ms = validate_refresh_interval(30, "ms")
    assert ok and ms == 30


def test_decimals_up_to_8_roundtrip(tmp_path):
    from core import Settings
    s = Settings.from_dict({"decimals": 8})
    assert s.decimals == 8
    s.save(tmp_path)
    import json
    raw = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert raw["decimals"] == 8
    assert Settings.load(tmp_path).decimals == 8
    from core import format_money
    assert format_money(0.123456789, 8) == "0.12345679"


# --------------------------------------------------------------------------- #
# 二、壁纸主色提取
# --------------------------------------------------------------------------- #
def _solid_image(color, size=32):
    from PySide6.QtGui import QImage
    img = QImage(size, size, QImage.Format_RGB32)
    img.fill(color)
    return img


def test_dominant_hue_solid_color():
    import wallpaper_color as wc
    from PySide6.QtGui import QColor
    for hue in (0, 60, 120, 210, 300):
        c = QColor.fromHslF(hue / 360.0, 0.8, 0.5)
        got = wc.dominant_hue(_solid_image(c))
        assert got is not None
        assert min(abs(got - hue), 360 - abs(got - hue)) <= 4, \
            f"色相 {hue}° 提取成 {got}°"


def test_dominant_hue_gray_returns_none():
    import wallpaper_color as wc
    from PySide6.QtGui import QColor
    assert wc.dominant_hue(_solid_image(QColor(128, 128, 128))) is None


def test_hues_from_image_roundtrip(tmp_path):
    import wallpaper_color as wc
    from PySide6.QtGui import QColor
    path = tmp_path / "wall.png"
    _solid_image(QColor.fromHslF(120 / 360.0, 0.8, 0.5)).save(str(path))
    hues = wc.hues_from_image(str(path))
    assert hues is not None
    h, h2, bg = hues
    assert min(abs(h - 120), 360 - abs(h - 120)) <= 4
    assert h2 == (h + wc.ANALOGOUS_OFFSET) % 360
    assert bg == h
    assert wc.hues_from_image(str(tmp_path / "missing.png")) is None


def test_auto_hues_cache_and_env(monkeypatch, tmp_path):
    import wallpaper_color as wc
    from PySide6.QtGui import QColor
    img = tmp_path / "w.png"
    _solid_image(QColor.fromHslF(0.55, 0.8, 0.5)).save(str(img))
    monkeypatch.setenv("MOYU_WALLPAPER", str(img))
    wc.reset_cache()
    first = wc.auto_hues()
    assert first is not None and first[0] == first[2]
    # TTL 内且壁纸没变：直接用缓存
    assert wc.auto_hues() == first
    assert wc.auto_hues() == first
    # 壁纸换了 → 立即重算（不等 TTL），拿到新壁纸的色相
    other = tmp_path / "w2.png"
    _solid_image(QColor.fromHslF(0.0, 0.8, 0.5)).save(str(other))
    monkeypatch.setenv("MOYU_WALLPAPER", str(other))
    second = wc.auto_hues()
    assert second is not None and second != first
    # force 也返回同样结果
    assert wc.auto_hues(force=True) == second


def test_effective_hues_auto_wallpaper(monkeypatch):
    import wallpaper_color as wc
    from core import Settings, effective_hues
    cfg = Settings.from_dict({"widget_auto_wallpaper": True,
                              "widget_follow_main": False})
    monkeypatch.setattr(wc, "auto_hues", lambda force=False: (100, 125, 100))
    assert effective_hues(cfg, widget=True) == (100, 125, 100)
    assert effective_hues(cfg, widget=False) != (100, 125, 100)   # 主界面不受影响
    # 壁纸取不到 → 回退普通逻辑
    monkeypatch.setattr(wc, "auto_hues", lambda force=False: None)
    fell_back = effective_hues(cfg, widget=True)
    assert fell_back == (int(cfg.widget_accent_hue), int(cfg.widget_accent2_hue),
                         int(cfg.widget_bg_hue))
    # 关闭开关 → 完全不走壁纸
    cfg2 = Settings.from_dict({"widget_auto_wallpaper": False})
    monkeypatch.setattr(wc, "auto_hues",
                        lambda force=False: (_ for _ in ()).throw(AssertionError("不应调用")))
    assert effective_hues(cfg2, widget=True) == (-1, -1, -1)


# --------------------------------------------------------------------------- #
# 三、主窗口头部：固定、不随内容滚动、按钮不被裁切（离屏 GUI）
# --------------------------------------------------------------------------- #
def test_header_fixed_and_visible_at_all_sizes(app, qapp):
    from PySide6.QtWidgets import QPushButton
    w = app.window
    w.show()
    qapp.processEvents()
    assert w.scroll.widget() is not w.header, "头部不应放在滚动区里"
    assert w.header.parent() is w.bg
    btns = [w.btn_top, w.btn_min, w.btn_close, w.btn_settings]
    for size in ((300, 380), (340, 500), (432, 724), (620, 1000)):
        w.resize(*size)
        for _ in range(3):
            qapp.processEvents()
        header_bottom = w.header.mapTo(w, w.header.rect().bottomLeft()).y()
        for btn in btns:
            assert isinstance(btn, QPushButton) and btn.isVisible(), f"{size} 按钮不可见"
            gp = btn.mapTo(w, btn.rect().topLeft())
            br = btn.rect()
            inside = (gp.x() >= 0 and gp.y() >= 0
                      and gp.x() + br.width() <= w.width()
                      and gp.y() + br.height() <= w.height())
            assert inside, f"{size} 下 {btn.text()} 超出窗口"
            assert gp.y() + br.height() <= header_bottom + 1, \
                f"{size} 下 {btn.text()} 不在固定头部内"
            fm = btn.fontMetrics()
            assert fm.horizontalAdvance(btn.text()) <= btn.width(), \
                f"{size} 下 {btn.text()} 文字溢出按钮"
        # 滚动条滚动时头部不动
        sb = w.scroll.verticalScrollBar()
        before = w.header.mapTo(w, w.header.rect().topLeft()).y()
        sb.setValue(sb.maximum())
        qapp.processEvents()
        after = w.header.mapTo(w, w.header.rect().topLeft()).y()
        assert before == after, "滚动内容时头部跟着动了"


# --------------------------------------------------------------------------- #
# 四、设置页：8 位小数、10ms 步进、壁纸开关
# --------------------------------------------------------------------------- #
def test_settings_dialog_new_controls(app, qapp):
    from ui_settings import SettingsDialog
    dlg = SettingsDialog(app)
    assert dlg.ed_decimals.maximum() == 8
    dlg.ed_refresh.setValue(10)
    dlg.ed_refresh_unit.setCurrentIndex(0)            # 毫秒
    ok, msg, ms = __import__("core").validate_refresh_interval(
        dlg.ed_refresh.value(), dlg.ed_refresh_unit.currentData())
    assert ok and ms == 10
    assert hasattr(dlg, "cb_widget_auto")
    assert dlg.cb_widget_auto.isChecked() is False
    assert dlg._draft().widget_auto_wallpaper is False
    dlg.cb_widget_auto.setChecked(True)
    assert dlg._draft().widget_auto_wallpaper is True
    dlg.reject()


def test_widget_context_menu_source_has_wallpaper_actions():
    src = (ROOT / "ui_widget.py").read_text(encoding="utf-8")
    assert "配色自动匹配壁纸" in src
    assert "重新匹配壁纸颜色" in src
