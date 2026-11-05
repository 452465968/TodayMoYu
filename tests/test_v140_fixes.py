# -*- coding: utf-8 -*-
"""v1.4.0 修复回归：主界面拖动/缩放/滚动兜底、小组件自适应、悬浮框残留。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

qt_app = None


@pytest.fixture(scope="module")
def qapp():
    global qt_app
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["HOME"] = os.environ.get("MOYU_TEST_HOME") or __import__("tempfile").mkdtemp(
        prefix="moyu_v140_home_")
    if qt_app is None:
        from PySide6.QtWidgets import QApplication
        import main as main_mod
        main_mod.SERVER_NAME += f"_t{os.getpid()}"
        qt_app = QApplication.instance() or QApplication(sys.argv[:1])
    return qt_app


@pytest.fixture(scope="module")
def app(qapp):
    from main import MoyuApp
    inst = MoyuApp(["--no-calendar", "--minimized", "--no-update"])
    return inst


# --------------------------------------------------------------------------- #
# 源码级断言（不依赖 GUI）
# --------------------------------------------------------------------------- #
def test_main_window_has_scroll_and_zoom_sources():
    ui = (ROOT / "ui_main.py").read_text(encoding="utf-8")
    assert "QScrollArea" in ui, "主窗口缺少内容滚动区"
    assert "clear_transient_button_state" in ui, "缺少悬浮框复位函数"
    assert "zoom_by" in ui, "缺少 Ctrl+滚轮缩放"
    assert "QAbstractButton, QScrollBar" in ui, "按钮/滚动条不应被拖动劫持"


def test_open_settings_clears_hover():
    src = (ROOT / "main.py").read_text(encoding="utf-8")
    assert src.count("clear_transient_button_state()") >= 2, "打开与关闭设置都应复位按钮状态"


def test_widget_fits_content():
    src = (ROOT / "ui_widget.py").read_text(encoding="utf-8")
    assert "_fit_size" in src
    assert src.count("_fit_size(") >= 3, "apply_appearance 与 update_snapshot 都要调用自适应"


def test_qss_scrollarea_transparent():
    import theme
    qss = theme.qss(theme.palette("aurora"))
    assert "QScrollArea { background: transparent; border: none; }" in qss
    assert "QScrollBar::handle:vertical" in qss


# --------------------------------------------------------------------------- #
# 行为级断言（离屏 GUI）
# --------------------------------------------------------------------------- #
def test_main_window_small_size_scrolls_not_clips(app, qapp):
    from PySide6.QtWidgets import QLabel
    w = app.window
    w.show()
    qapp.processEvents()
    for size in ((300, 380), (340, 500), (432, 724)):
        w.resize(*size)
        for _ in range(3):
            qapp.processEvents()
        for lb in w.body.findChildren(QLabel):
            assert lb.height() >= lb.minimumSizeHint().height() - 1, \
                f"{size} 下 {lb.objectName()} 被裁切"
        assert (w.scroll.verticalScrollBar().maximum() > 0) or \
               w.body.minimumSizeHint().height() <= w.scroll.viewport().height()


def test_drag_anywhere_and_persist(app, qapp):
    from PySide6.QtCore import QPoint, QPointF, Qt, QEvent
    from PySide6.QtGui import QMouseEvent
    w = app.window
    qapp.processEvents()
    vp = w.scroll.viewport()
    base = vp.mapToGlobal(QPoint(60, 120))
    qapp.sendEvent(vp, QMouseEvent(QEvent.MouseButtonPress, QPointF(60, 120),
                                   QPointF(base), Qt.LeftButton, Qt.LeftButton,
                                   Qt.NoModifier))
    qapp.sendEvent(vp, QMouseEvent(QEvent.MouseMove, QPointF(100, 150),
                                   QPointF(base + QPoint(37, 21)), Qt.NoButton,
                                   Qt.LeftButton, Qt.NoModifier))
    qapp.sendEvent(vp, QMouseEvent(QEvent.MouseButtonRelease, QPointF(100, 150),
                                   QPointF(base + QPoint(37, 21)), Qt.LeftButton,
                                   Qt.NoButton, Qt.NoModifier))
    qapp.processEvents()
    assert app.cfg.main_pos == [w.x(), w.y()], "拖动后位置应持久化"
    # 按钮与滚动条不被拖动逻辑劫持
    from PySide6.QtWidgets import QScrollBar
    gp = w.btn_settings.mapToGlobal(QPoint(5, 5))
    assert w.eventFilter(w.btn_settings, QMouseEvent(
        QEvent.MouseButtonPress, QPointF(5, 5), QPointF(gp), Qt.LeftButton,
        Qt.LeftButton, Qt.NoModifier)) is False
    sb = w.scroll.verticalScrollBar()
    gp2 = sb.mapToGlobal(QPoint(3, 3))
    assert w.eventFilter(sb, QMouseEvent(
        QEvent.MouseButtonPress, QPointF(3, 3), QPointF(gp2), Qt.LeftButton,
        Qt.LeftButton, Qt.NoModifier)) is False


def test_ctrl_wheel_zoom_clamped(app, qapp):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from ui_main import MAX_SCALE, MIN_SCALE, WIN_H, WIN_W
    w = app.window
    w.resize(WIN_W, WIN_H)
    for _ in range(3):
        qapp.processEvents()

    def wheel(dy: int) -> None:
        ev = QWheelEvent(QPointF(200, 300), w.mapToGlobal(QPoint(200, 300)),
                         QPoint(0, 0), QPoint(0, dy), Qt.NoButton,
                         Qt.ControlModifier, Qt.NoScrollPhase, False)
        qapp.sendEvent(w.scroll.viewport(), ev)
        qapp.processEvents()

    for _ in range(40):
        wheel(120)
    assert w.width() <= int(WIN_W * MAX_SCALE) + 2
    for _ in range(200):
        wheel(-120)
    assert w.width() >= int(WIN_W * MIN_SCALE) - 2
    w._zoom_save.stop()
    w.resize(WIN_W, WIN_H)


def test_widget_numbers_visible_at_any_scale(app, qapp):
    from core import WIDGET_SCALE_MAX, WIDGET_SCALE_MIN
    dw = app.widget
    if dw is None:
        app.toggle_widget(True)
        qapp.processEvents()
        dw = app.widget
    s = WIDGET_SCALE_MIN
    while s <= WIDGET_SCALE_MAX + 1e-9:
        dw.set_scale(round(s, 3))
        for _ in range(3):
            qapp.processEvents()
        for name in ("lb_sign", "lb_money", "lb_duration", "lb_status"):
            lb = getattr(dw, name)
            assert lb.height() >= lb.minimumSizeHint().height() - 1, \
                f"{int(s*100)}% 下 {name} 被裁切"
        need = dw._content_layout.minimumSize()
        assert dw.height() >= need.height() and dw.width() >= need.width() - 2
        s += 0.25
    dw.set_scale(1.0)


def test_clear_transient_button_state(app):
    from PySide6.QtCore import Qt
    w = app.window
    btn = w.btn_settings
    btn.setAttribute(Qt.WA_UnderMouse, True)
    btn.setDown(True)
    w.clear_transient_button_state()
    assert not btn.testAttribute(Qt.WA_UnderMouse)
    assert not btn.isDown()
