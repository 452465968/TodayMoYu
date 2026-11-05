# -*- coding: utf-8 -*-
"""今天摸了吗 · 桌面小组件（Widget）

一个无边框、半透明、可拖动的独立窗口，实时显示两项核心数据：
    今日混底色【工资】 / 已摸鱼时长
支持：窗口置顶、贴到 Windows 桌面图层（Win+D 后仍可见）、缩放、透明度、
      位置记忆、双击打开主窗口、右键菜单。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtGui import QAction, QCursor
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QProgressBar,
    QSizePolicy, QSpacerItem, QVBoxLayout, QWidget,
)

import win32_extra as win
from core import APP_NAME, Snapshot, format_hms, format_money
from theme import SoftGradient, qss, theme

if TYPE_CHECKING:
    from main import MoyuApp

BASE_W, BASE_H = 284, 190


class DesktopWidget(QWidget):
    def __init__(self, app: "MoyuApp"):
        super().__init__()
        self.app = app
        self.cfg = app.cfg
        self._scale = self.cfg.widget_scale
        self._docked = False
        self._on_top = False
        self._initialized = False
        self._drag_cursor: QPoint | None = None
        self._drag_pos: tuple[int, int] | None = None
        self._moved = False

        self.setWindowTitle(f"{APP_NAME} · 桌面小组件")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)

        self.bg = SoftGradient(self, self.cfg.theme, radius=16, glow=True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.bg)

        L = QVBoxLayout(self.bg)
        self._content_layout = L
        L.setContentsMargins(17, 12, 17, 14)
        L.setSpacing(2)

        top = QHBoxLayout()
        self._top_layout = top
        brand = QLabel(f"◉ {APP_NAME}")
        brand.setObjectName("Title")
        hint = QLabel("双击打开主窗口")
        hint.setObjectName("Hint")
        top.addWidget(brand)
        top.addStretch(1)
        top.addWidget(hint)
        L.addLayout(top)
        self._gap1 = QSpacerItem(0, 7, QSizePolicy.Minimum, QSizePolicy.Fixed)
        L.addSpacerItem(self._gap1)

        lab1 = QLabel("今日混底薪【工资】")
        lab1.setObjectName("FieldLabel")
        L.addWidget(lab1)

        money_row = QHBoxLayout()
        self._money_layout = money_row
        money_row.setSpacing(2)
        self.lb_sign = QLabel("¥")
        self.lb_sign.setObjectName("MoneySign")
        self.lb_money = QLabel("0.0000")
        self.lb_money.setObjectName("Money")
        money_row.addWidget(self.lb_sign)
        money_row.addWidget(self.lb_money)
        money_row.addStretch(1)
        L.addLayout(money_row)

        lab2 = QLabel("已摸鱼时长")
        lab2.setObjectName("FieldLabel")
        L.addWidget(lab2)
        self.lb_duration = QLabel("00:00:00")
        self.lb_duration.setObjectName("Duration")
        L.addWidget(self.lb_duration)

        self._gap2 = QSpacerItem(0, 4, QSizePolicy.Minimum, QSizePolicy.Fixed)
        L.addSpacerItem(self._gap2)
        self.pb = QProgressBar()
        self.pb.setMaximum(1000)
        self.pb.setTextVisible(False)
        self.pb.setFixedHeight(7)
        L.addWidget(self.pb)

        self.lb_status = QLabel("摸鱼中 · 距离下班还有 —")
        self.lb_status.setObjectName("Hint")
        L.addWidget(self.lb_status)

        # 所有子控件（含背景）都不吃鼠标事件，保证任意位置都能拖动 / 右键
        self.bg.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        for child in self.bg.findChildren(QWidget):
            child.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        self.apply_appearance()
        self.restore_position()

    # ------------------------------------------------------------------ #
    # 外观（缩放与透明度都作用于绘制层，跨平台一致）
    # ------------------------------------------------------------------ #
    def apply_appearance(self) -> None:
        t = theme(self.cfg.theme)
        s = self._scale
        self.bg.set_theme(self.cfg.theme)
        # 通透度做进背景绘制层：不与 WA_TranslucentBackground / 分层窗口机制冲突，
        # 也不依赖 setWindowOpacity（Windows 上常被忽略）。文字保持全不透明。
        self.bg.set_alpha(self.cfg.widget_opacity)
        self.setStyleSheet(qss(t, card_alpha=0.0, scale=s))
        # 布局的边距 / 间距 / 固定高度也要跟着缩放，否则缩小后内容会溢出裁切
        self._content_layout.setContentsMargins(
            max(4, int(17 * s)), max(3, int(12 * s)),
            max(4, int(17 * s)), max(3, int(14 * s)))
        self._content_layout.setSpacing(max(0, int(2 * s)))
        self._top_layout.setSpacing(max(0, int(2 * s)))
        self._money_layout.setSpacing(max(0, int(2 * s)))
        self._gap1.changeSize(0, max(1, int(7 * s)), QSizePolicy.Minimum, QSizePolicy.Fixed)
        self._gap2.changeSize(0, max(1, int(4 * s)), QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.pb.setFixedHeight(max(4, int(7 * s)))
        self.setFixedSize(int(BASE_W * s), int(BASE_H * s))
        self.setToolTip(f"{APP_NAME} 桌面小组件\n拖动移动 · 双击打开主窗口 · 右键调整大小与透明度")
        self.update()

    def set_scale(self, value: float, persist: bool = True) -> None:
        self._scale = max(0.6, min(2.0, value))
        self.cfg.widget_scale = self._scale
        self.apply_appearance()
        self._clamp_to_screen()
        if persist:
            self.app.save_config()

    def set_opacity(self, value: float, persist: bool = True) -> None:
        self.cfg.widget_opacity = max(0.3, min(1.0, value))
        self.bg.set_alpha(self.cfg.widget_opacity)
        if persist:
            self.app.save_config()

    # ------------------------------------------------------------------ #
    # 位置 / 窗口模式
    # ------------------------------------------------------------------ #
    def _clamp_to_screen(self) -> None:
        """放大 / 恢复位置后把小组件夹回屏幕内，避免跑到可视区外。"""
        if self._docked:
            return
        screen = self.app.available_geometry()
        x = max(screen.left(), min(self.x(), screen.left() + screen.width() - self.width()))
        y = max(screen.top(), min(self.y(), screen.top() + screen.height() - self.height()))
        self.move(x, y)

    def restore_position(self) -> None:
        pos = self.cfg.widget_pos
        if pos and len(pos) == 2:
            self.move(pos[0], pos[1])
        else:
            screen = self.app.available_geometry()
            self.move(screen.right() - int(BASE_W * self._scale) - 32, screen.top() + 48)
        self._clamp_to_screen()

    def save_position(self) -> None:
        hwnd = int(self.winId()) if win.IS_WINDOWS else 0
        pos = win.window_global_pos(hwnd) if hwnd else None
        if pos is None:
            g = self.frameGeometry()
            pos = (g.x(), g.y())
        self.cfg.widget_pos = [int(pos[0]), int(pos[1])]
        self.app.save_config()

    def set_docked(self, flag: bool) -> bool:
        """贴到桌面壁纸图层。失败时自动回退为普通窗口并返回 False。"""
        if not win.IS_WINDOWS:
            self.app.notify("提示", "「贴到桌面」是 Windows 专属功能，当前系统已自动使用普通置顶模式。")
            return False
        hwnd = int(self.winId())
        was_visible = self.isVisible()
        if flag:
            self.set_on_top(False)
            ok = win.dock_to_desktop(hwnd)
            self._docked = bool(ok)
            if ok:
                win.push_to_bottom(hwnd)
                if was_visible:
                    self.show()
            else:
                self.app.notify("提示", "未能挂载到桌面图层，已切换为普通小组件窗口。")
            return bool(ok)
        if self._docked:
            win.undock_from_desktop(hwnd)
            self._docked = False
            if was_visible:
                self.show()
                self.raise_()
        return True

    def set_on_top(self, flag: bool) -> None:
        """置顶与贴桌面互斥（改 window flags 会重建原生窗口、破坏 SetParent）。"""
        flag = bool(flag)
        if flag and self._docked:
            self.set_docked(False)
        self.cfg.always_on_top = flag
        if flag == self._on_top:
            return
        self._on_top = flag
        base = Qt.FramelessWindowHint | Qt.Tool
        if flag:
            base |= Qt.WindowStaysOnTopHint
        was_visible = self.isVisible()   # 改 flags 会重建原生窗口，别把隐藏的小组件意外显示出来
        self.setWindowFlags(base)
        if was_visible:
            self.show()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._initialized:
            self._initialized = True
            if win.IS_WINDOWS:
                win.make_tool_window(int(self.winId()))
            QTimer.singleShot(120, self._apply_initial_mode)

    def _apply_initial_mode(self) -> None:
        if self.cfg.widget_dock_desktop:
            if self.set_docked(True):
                self.cfg.widget_dock_desktop = True
            else:
                self.cfg.widget_dock_desktop = False
                self.set_on_top(True)
        elif self.cfg.always_on_top:
            self.set_on_top(True)
        self.app.save_config()

    def hideEvent(self, event) -> None:  # noqa: N802
        self.save_position()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.save_position()
        if self._docked:
            win.undock_from_desktop(int(self.winId()))
            self._docked = False
        event.ignore()
        self.app.toggle_widget(False)

    # ------------------------------------------------------------------ #
    # 数据刷新
    # ------------------------------------------------------------------ #
    def update_snapshot(self, snap: Snapshot) -> None:
        self.lb_money.setText(format_money(snap.earned_today, self.cfg.decimals))
        self.lb_duration.setText(format_hms(snap.fished_seconds))
        self.pb.setValue(int(snap.progress * 1000))
        self.lb_status.setText(f"{snap.status_text} · 进度 {snap.progress * 100:.1f}%")

    # ------------------------------------------------------------------ #
    # 交互
    # ------------------------------------------------------------------ #
    def _hwnd(self) -> int:
        return int(self.winId()) if win.IS_WINDOWS else 0

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag_cursor = QCursor.pos()
            pos = win.window_global_pos(self._hwnd()) if win.IS_WINDOWS else None
            if pos is None:
                g = self.frameGeometry()
                pos = (g.x(), g.y())
            self._drag_pos = pos
            self._moved = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag_cursor and self._drag_pos and (event.buttons() & Qt.LeftButton):
            cur = QCursor.pos()
            dx, dy = cur.x() - self._drag_cursor.x(), cur.y() - self._drag_cursor.y()
            if abs(dx) + abs(dy) > 3:
                self._moved = True
            x, y = self._drag_pos[0] + dx, self._drag_pos[1] + dy
            if win.IS_WINDOWS and not win.move_window_global(self._hwnd(), x, y):
                self.move(x, y)
            elif not win.IS_WINDOWS:
                self.move(x, y)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._moved:
            self.save_position()
        self._drag_cursor = None
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.app.show_main_window()
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background: #FFFFFF; color: {theme(self.cfg.theme)['text']};
                     border: 1px solid rgba(120,132,170,0.25); border-radius: 10px;
                     padding: 6px; font-size: 12px; }}
            QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
            QMenu::item:selected {{ background: {theme(self.cfg.theme)['accent2_soft']};
                                    color: {theme(self.cfg.theme)['accent2']}; }}
            QMenu::separator {{ height: 1px; background: rgba(120,132,170,0.18); margin: 4px 8px; }}
        """)

        act_open = menu.addAction("打开「今天摸了吗」主窗口")
        act_open.triggered.connect(self.app.show_main_window)
        menu.addSeparator()

        act_top = menu.addAction("窗口置顶")
        act_top.setCheckable(True)
        act_top.setChecked(bool(self.cfg.always_on_top) and not self._docked)
        act_top.triggered.connect(lambda checked: (self.set_on_top(checked), self.app.save_config()))

        act_dock = menu.addAction("贴到桌面（Win+D 后仍可见）")
        act_dock.setCheckable(True)
        act_dock.setChecked(self._docked)
        act_dock.setEnabled(win.IS_WINDOWS)
        act_dock.triggered.connect(self._on_dock_toggled)

        appearance = menu.addMenu(
            f"外观（当前 {round(self._scale * 100)}% · 透明度 {round(self.cfg.widget_opacity * 100)}%）")
        for label, delta in (("放大 +10%", 0.1), ("缩小 −10%", -0.1)):
            a = appearance.addAction(label)
            a.triggered.connect(lambda _=False, d=delta: self.set_scale(self._scale + d))
        scale_menu = appearance.addMenu("大小档位")
        for value, label in ((0.6, "60%"), (0.8, "80%"), (1.0, "100%（默认）"),
                            (1.25, "125%"), (1.5, "150%"), (2.0, "200%")):
            a = scale_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(abs(self._scale - value) < 0.01)
            a.triggered.connect(lambda _=False, v=value: self.set_scale(v))
        appearance.addSeparator()
        for label, delta in (("更不透明 +10%", 0.1), ("更透明 −10%", -0.1)):
            a = appearance.addAction(label)
            a.triggered.connect(
                lambda _=False, d=delta: self.set_opacity(self.cfg.widget_opacity + d))
        opacity_menu = appearance.addMenu("透明度档位")
        for value, label in ((0.3, "30%"), (0.6, "60%"), (0.8, "80%"),
                            (0.94, "94%（默认）"), (1.0, "100%")):
            a = opacity_menu.addAction(label)
            a.setCheckable(True)
            a.setChecked(abs(self.cfg.widget_opacity - value) < 0.01)
            a.triggered.connect(lambda _=False, v=value: self.set_opacity(v))

        menu.addSeparator()
        act_reset = menu.addAction("重置到屏幕右上角")
        act_reset.triggered.connect(self._reset_position)
        act_hide = menu.addAction("隐藏小组件")
        act_hide.triggered.connect(lambda: self.app.toggle_widget(False))
        # Qt6 用 globalPosition()，Qt5 / 手工事件只有 globalPos()
        pos = (event.globalPosition().toPoint() if hasattr(event, "globalPosition")
               else event.globalPos())
        # popup 非阻塞：不占用事件循环，也不会打断实时刷新；保持引用避免被回收
        self._ctx_menu = menu
        menu.popup(pos)

    def _on_dock_toggled(self, checked: bool) -> None:
        ok = self.set_docked(checked)
        self.cfg.widget_dock_desktop = bool(ok and checked)
        self.app.save_config()

    def _reset_position(self) -> None:
        self.cfg.widget_pos = None
        self.restore_position()
        self.save_position()
