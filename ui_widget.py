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
from core import (APP_NAME, WIDGET_SCALE_MAX, WIDGET_SCALE_MIN, Snapshot,
                  format_hms, format_money)
from theme import SoftGradient, palette_for, qss

if TYPE_CHECKING:
    from main import MoyuApp

BASE_W, BASE_H = 284, 190
GRIP = 18            # 右下角无级缩放的命中范围（像素）
SCALE_STEP = 0.01     # 滚轮 / 菜单的最小步进（1%，连续可调）


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
        # 无级缩放的拖拽状态：记录起点与起点缩放比，拖动时逐像素换算
        self._grip_origin: QPoint | None = None
        self._grip_scale = 1.0

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
        t = palette_for(self.cfg, widget=True)
        s = self._scale
        self.bg.set_palette(t)
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
        self._fit_size(s)
        self.setToolTip(
            f"{APP_NAME} 桌面小组件\n"
            f"拖动移动 · 右下角拖拽无级缩放（{round(s * 100)}%）\n"
            f"滚轮缩放 · Shift+滚轮调透明度（{round(self.cfg.widget_opacity * 100)}%）\n"
            f"双击打开主窗口 · 右键更多选项")
        self.update()

    def _fit_size(self, s: float) -> None:
        """窗口尺寸 = max(基准尺寸 × 缩放, 布局最小需求)。

        固定用「基准 × 缩放」会在低缩放比下比内容矮，金额 / 时长标签
        就会被压扁裁切（v1.3.0 实测 100% 时布局最小高 220 > 窗口 190）；
        按布局 minimumSize 撑开窗口后，任何缩放比下数字都完整可见。
        """
        self._content_layout.activate()
        need = self._content_layout.minimumSize()
        screen = self.app.available_geometry()
        w = max(120, int(round(BASE_W * s)), min(need.width(), screen.width()))
        h = max(80, int(round(BASE_H * s)), min(need.height(), screen.height()))
        self.setFixedSize(w, h)

    def set_scale(self, value: float, persist: bool = True) -> None:
        """无级缩放：内部保留三位小数，任意数值都能停在原处。"""
        self._scale = round(max(WIDGET_SCALE_MIN, min(WIDGET_SCALE_MAX, float(value))), 3)
        self.cfg.widget_scale = self._scale
        self.apply_appearance()
        self._clamp_to_screen()
        if persist:
            self.app.save_config()

    def set_opacity(self, value: float, persist: bool = True) -> None:
        self.cfg.widget_opacity = round(max(0.15, min(1.0, float(value))), 3)
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
        # 金额位数 / 状态文案变化会改变布局最小需求，必要时把窗口撑大一点，
        # 保证任何时刻数字都不被裁切
        self._fit_size(self._scale)

    # ------------------------------------------------------------------ #
    # 交互
    # ------------------------------------------------------------------ #
    def _hwnd(self) -> int:
        return int(self.winId()) if win.IS_WINDOWS else 0

    def _on_grip(self, pos: QPoint) -> bool:
        """是否点在右下角的缩放热区。"""
        return (pos.x() >= self.width() - GRIP) and (pos.y() >= self.height() - GRIP)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            if self._on_grip(event.position().toPoint()):
                # 进入无级缩放：记录锚点与起始比例，之后逐像素换算
                self._grip_origin = QCursor.pos()
                self._grip_scale = self._scale
                self.setCursor(Qt.SizeFDiagCursor)
                return
            self._drag_cursor = QCursor.pos()
            pos = win.window_global_pos(self._hwnd()) if win.IS_WINDOWS else None
            if pos is None:
                g = self.frameGeometry()
                pos = (g.x(), g.y())
            self._drag_pos = pos
            self._moved = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._grip_origin and (event.buttons() & Qt.LeftButton):
            # 用「宽高两个方向的相对位移取平均」换算比例，横向竖向拖拽都跟手
            cur = QCursor.pos()
            dx = cur.x() - self._grip_origin.x()
            dy = cur.y() - self._grip_origin.y()
            delta = (dx / float(BASE_W) + dy / float(BASE_H)) / 2.0
            self.set_scale(self._grip_scale + delta, persist=False)
            return
        if not (event.buttons() & Qt.LeftButton):
            # 悬停在右下角时给出缩放光标，让「可拖拽」这件事可被发现
            self.setCursor(Qt.SizeFDiagCursor if self._on_grip(event.position().toPoint())
                           else Qt.ArrowCursor)
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
        if self._grip_origin:
            # 松手才落盘：拖动过程只重绘，避免高频写配置
            self._grip_origin = None
            self.unsetCursor()
            self.app.save_config()
            return
        if self._moved:
            self.save_position()
        self._drag_cursor = None
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:  # noqa: N802
        """滚轮连续缩放；Shift+滚轮连续调透明度（每次 1%，可细调）。"""
        steps = event.angleDelta().y() / 120.0
        if not steps:
            return
        if event.modifiers() & Qt.ShiftModifier:
            self.set_opacity(self.cfg.widget_opacity + steps * 0.02)
        else:
            self.set_scale(self._scale + steps * SCALE_STEP * 2)
        event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.app.show_main_window()
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        pal = palette_for(self.cfg, widget=True)
        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{ background: #FFFFFF; color: {pal['text']};
                     border: 1px solid rgba(120,132,170,0.25); border-radius: 10px;
                     padding: 6px; font-size: 12px; }}
            QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
            QMenu::item:selected {{ background: {pal['accent2_soft']};
                                    color: {pal['accent2']}; }}
            QMenu::separator {{ height: 1px; background: rgba(120,132,170,0.18); margin: 4px 8px; }}
        """)

        act_open = menu.addAction("打开「今天摸了吗」主窗口")
        act_open.triggered.connect(self.app.show_main_window)
        menu.addSeparator()

        act_top = menu.addAction("窗口置顶")
        act_top.setCheckable(True)
        act_top.setChecked(bool(self.cfg.always_on_top) and not self._docked)
        act_top.triggered.connect(lambda checked: (self.set_on_top(checked), self.app.save_config()))

        act_dock = menu.addAction("贴到桌面（Win+D 后仍可见）" if win.IS_WINDOWS
                                  else "贴到桌面（Windows 专属）")
        act_dock.setCheckable(True)
        act_dock.setChecked(self._docked)
        act_dock.setEnabled(win.IS_WINDOWS)
        act_dock.triggered.connect(self._on_dock_toggled)

        # 无级调节：1% 细调 + 5% 快调，任意数值都能停下并保存
        appearance = menu.addMenu(
            f"外观（{self._scale:.0%} · 不透明度 {self.cfg.widget_opacity:.0%}）")
        size_menu = appearance.addMenu(f"大小（当前 {self._scale:.0%}）")
        for label, delta in (("放大 +5%", 0.05), ("放大 +1%", 0.01),
                             ("缩小 −1%", -0.01), ("缩小 −5%", -0.05)):
            a = size_menu.addAction(label)
            a.triggered.connect(lambda _=False, d=delta: self.set_scale(self._scale + d))
        size_menu.addSeparator()
        a = size_menu.addAction("恢复 100%")
        a.triggered.connect(lambda: self.set_scale(1.0))

        opacity_menu = appearance.addMenu(
            f"不透明度（当前 {self.cfg.widget_opacity:.0%}）")
        for label, delta in (("更不透明 +5%", 0.05), ("更不透明 +1%", 0.01),
                             ("更透明 −1%", -0.01), ("更透明 −5%", -0.05)):
            a = opacity_menu.addAction(label)
            a.triggered.connect(
                lambda _=False, d=delta: self.set_opacity(self.cfg.widget_opacity + d))
        opacity_menu.addSeparator()
        a = opacity_menu.addAction("恢复 94%")
        a.triggered.connect(lambda: self.set_opacity(0.94))

        appearance.addSeparator()
        a = appearance.addAction("配色自动匹配壁纸")
        a.setCheckable(True)
        a.setChecked(bool(self.cfg.widget_auto_wallpaper))
        a.triggered.connect(self._toggle_auto_wallpaper)
        a = appearance.addAction("重新匹配壁纸颜色")
        a.setEnabled(bool(self.cfg.widget_auto_wallpaper))
        a.triggered.connect(self._rematch_wallpaper)
        a = appearance.addAction("配色与主界面一致")
        a.setCheckable(True)
        a.setChecked(bool(self.cfg.widget_follow_main) and not self.cfg.widget_auto_wallpaper)
        a.setEnabled(not self.cfg.widget_auto_wallpaper)
        a.triggered.connect(self._toggle_follow_main)
        a = appearance.addAction("单独设置小组件配色…")
        a.triggered.connect(self.app.open_settings_color)

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

    def _toggle_follow_main(self, checked: bool) -> None:
        self.cfg.widget_follow_main = bool(checked)
        self.apply_appearance()
        self.app.save_config()

    def _toggle_auto_wallpaper(self, checked: bool) -> None:
        """开启后取壁纸主色；换壁纸时右键「重新匹配壁纸颜色」强制刷新缓存。"""
        self.cfg.widget_auto_wallpaper = bool(checked)
        if checked:
            import wallpaper_color
            wallpaper_color.reset_cache()
        self.apply_appearance()
        self.app.save_config()

    def _rematch_wallpaper(self) -> None:
        import wallpaper_color
        wallpaper_color.reset_cache()
        wallpaper_color.auto_hues(force=True)
        self.apply_appearance()
        self.update()

    def _on_dock_toggled(self, checked: bool) -> None:
        ok = self.set_docked(checked)
        self.cfg.widget_dock_desktop = bool(ok and checked)
        self.app.save_config()

    def _reset_position(self) -> None:
        self.cfg.widget_pos = None
        self.restore_position()
        self.save_position()
