# -*- coding: utf-8 -*-
"""今天摸了吗 · 主窗口

布局对齐参考视频：日期时间 / 状态 / 倒计时 / 大号实时金额 / 速度 /
趣味文案 / 主按钮 / 进度 / 本月累计 / 时薪与满勤，
并把「今日混底薪【工资】」与「已摸鱼时长」提升为两大主数据。

窗口为无边框自绘窗口，支持从任意边缘 / 四角**连续拖拽**改变宽高：
没有档位限制，尺寸随拖动逐像素变化，并记住上次尺寸。
尺寸变化时字号、间距、卡片内边距、按钮与进度条高度按同一比例缩放，
文字启用换行，保证放大不空、缩小不裁切、控件始终可点击。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QRect, Qt, QPoint, QTimer
from PySide6.QtGui import QColor, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QProgressBar, QPushButton, QScrollArea, QScrollBar, QSizePolicy,
    QToolTip, QVBoxLayout, QWidget,
)

import win32_extra as win
from core import APP_NAME, APP_VERSION, Snapshot, day_kind_label, format_hms, format_money
from theme import SoftGradient, palette_for, qss

if TYPE_CHECKING:
    from main import MoyuApp

WIN_W, WIN_H = 432, 724          # 默认尺寸（可任意调整）
MIN_W, MIN_H = 300, 380          # 有滚动区兜底，允许缩得比内容最小尺寸更小
MAX_SCALE, MIN_SCALE = 1.60, 0.70
EDGE = 9                         # 边缘命中宽度（像素）
ZOOM_STEP = 0.05                 # Ctrl/⌘+滚轮每格缩放 5%
ZOOM_SAVE_DELAY_MS = 600         # 停止缩放后延迟落盘


class DragHandle(QWidget):
    """自绘标题栏：视觉上是标题条；拖动由主窗口的统一事件过滤器处理
    （整个窗口的空白区域都支持按住拖动）。"""

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.window = window
        self.setFixedHeight(38)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)


class MainWindow(QWidget):
    def __init__(self, app: "MoyuApp"):
        super().__init__()
        self.app = app
        cfg = app.cfg
        self.setWindowTitle(APP_NAME)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMinimumSize(MIN_W, MIN_H)
        self._scale = 1.0
        self._applying = False
        self._resize: dict | None = None
        self._drag_offset: QPoint | None = None
        self._spacers: list[tuple[object, int]] = []
        self._zoom_save = QTimer(self)
        self._zoom_save.setSingleShot(True)
        self._zoom_save.setInterval(ZOOM_SAVE_DELAY_MS)
        self._zoom_save.timeout.connect(self._save_size)

        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(11, 11, 11, 11)   # 给柔光阴影留出空间
        self.bg = SoftGradient(self, cfg.theme, radius=20, glow=True)
        self.outer.addWidget(self.bg)
        shadow = QGraphicsDropShadowEffect(self.bg)
        shadow.setBlurRadius(26)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(70, 78, 125, 48))
        self.bg.setGraphicsEffect(shadow)

        self.sL = QVBoxLayout(self.bg)
        self.sL.setContentsMargins(20, 8, 20, 12)
        self.sL.setSpacing(0)

        # ---------------- 固定头部（不随内容滚动，任何窗口尺寸都不裁切） ---------------- #
        # 标题栏与「日期 / 设置」行放在滚动区外面：窗口缩到很小时内容区出滚动条，
        # 置顶 / 最小化 / 关闭 / 设置按钮永远钉在顶部、位置固定、可点击（v1.5.0 修复）。
        self.header = QWidget()
        self.header.setObjectName("MainHeader")
        self.hL = QVBoxLayout(self.header)
        self.hL.setContentsMargins(0, 0, 0, 14)
        self.hL.setSpacing(0)

        self.handle = DragHandle(self)
        hl = QHBoxLayout(self.handle)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(2)
        brand = QLabel(f"◉  {APP_NAME}")
        brand.setObjectName("Title")
        brand.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        brand.setMinimumWidth(0)
        hl.addWidget(brand, 0, Qt.AlignLeft)
        hl.addStretch(1)
        self.btn_top = QPushButton("置顶")
        self.btn_top.setObjectName("WinBtn")
        self.btn_top.setCheckable(True)
        self.btn_top.setFixedSize(46, 30)
        self.btn_top.setToolTip("让主窗口始终显示在其他窗口之上")
        self.btn_top.toggled.connect(self.app.toggle_always_on_top)
        self.btn_min = QPushButton("—")
        self.btn_min.setObjectName("WinBtn")
        self.btn_min.setFixedSize(30, 30)
        self.btn_min.clicked.connect(self.app.minimize_main)
        self.btn_close = QPushButton("×")
        self.btn_close.setObjectName("WinBtn")
        self.btn_close.setFixedSize(30, 30)
        self.btn_close.setToolTip("关闭（可在设置里改为最小化到托盘）")
        self.btn_close.clicked.connect(self.app.close_main)
        hl.addWidget(self.btn_top)
        hl.addWidget(self.btn_min)
        hl.addWidget(self.btn_close)
        self.hL.addWidget(self.handle)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.lb_date = QLabel("—")
        self.lb_date.setObjectName("DateLine")
        self.lb_date.setWordWrap(True)
        self.lb_date.setMinimumWidth(0)
        self.btn_settings = QPushButton("⚙  设置")
        self.btn_settings.setObjectName("Ghost")
        self.btn_settings.setFixedHeight(28)
        self.btn_settings.setMinimumWidth(72)
        self.btn_settings.clicked.connect(self.app.open_settings)
        row.addWidget(self.lb_date, 1)
        row.addWidget(self.btn_settings, 0, Qt.AlignRight)
        self.hL.addLayout(row)
        self.sL.addWidget(self.header)

        # 内容放进透明滚动区：窗口被缩到比内容最小尺寸还小时出现滚动条，
        # 任何元素都不会再被裁切或遮挡（v1.3.0 前小窗口下文字会被硬裁）
        self.scroll = QScrollArea(self.bg)
        self.scroll.setObjectName("MainScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.body = QWidget()
        self.body.setObjectName("MainBody")
        self.scroll.setWidget(self.body)
        self.sL.addWidget(self.scroll)

        self.L = QVBoxLayout(self.body)
        self.L.setContentsMargins(0, 0, 0, 0)
        self.L.setSpacing(0)

        # ---------------- 状态 / 倒计时 ---------------- #
        self.lb_status = QLabel("摸鱼中")
        self.lb_status.setObjectName("Status")
        self.lb_status.setWordWrap(True)
        self.L.addWidget(self.lb_status)
        self.lb_countdown = QLabel("距离下班还有 —")
        self.lb_countdown.setObjectName("Countdown")
        self.lb_countdown.setWordWrap(True)
        self.L.addWidget(self.lb_countdown)
        self.lb_daykind = QLabel("今日：工作日")
        self.lb_daykind.setObjectName("Hint")
        self.lb_daykind.setWordWrap(True)
        self.L.addWidget(self.lb_daykind)
        self._space(16)

        # ---------------- 主数据 1：今日混底薪 ---------------- #
        card1 = QFrame()
        card1.setObjectName("Card")
        self.c1 = QVBoxLayout(card1)
        self.c1.setContentsMargins(16, 12, 16, 13)
        self.c1.setSpacing(2)
        lab = QLabel("今日混底薪【工资】")
        lab.setObjectName("FieldLabel")
        lab.setWordWrap(True)
        self.c1.addWidget(lab)
        money_row = QHBoxLayout()
        money_row.setSpacing(3)
        self.lb_sign = QLabel("¥")
        self.lb_sign.setObjectName("MoneySign")
        self.lb_money = QLabel("0.0000")
        self.lb_money.setObjectName("Money")
        self.lb_money.setWordWrap(True)
        money_row.addWidget(self.lb_sign)
        money_row.addWidget(self.lb_money)
        money_row.addStretch(1)
        self.c1.addLayout(money_row)
        self.lb_speed = QLabel("当前摸鱼进账 ¥0.0000 / 秒")
        self.lb_speed.setObjectName("Hint")
        self.lb_speed.setWordWrap(True)
        self.c1.addWidget(self.lb_speed)
        self.L.addWidget(card1)
        self._space(10)

        # ---------------- 主数据 2：已摸鱼时长 ---------------- #
        card2 = QFrame()
        card2.setObjectName("Card")
        self.c2 = QVBoxLayout(card2)
        self.c2.setContentsMargins(16, 12, 16, 13)
        self.c2.setSpacing(2)
        lab2 = QLabel("已摸鱼时长")
        lab2.setObjectName("FieldLabel")
        lab2.setWordWrap(True)
        self.c2.addWidget(lab2)
        self.lb_duration = QLabel("00:00:00")
        self.lb_duration.setObjectName("Duration")
        self.lb_duration.setWordWrap(True)
        self.c2.addWidget(self.lb_duration)
        self.lb_hours = QLabel("已摸 0.00 / 7.50 小时 · 0.0%")
        self.lb_hours.setObjectName("Hint")
        self.lb_hours.setWordWrap(True)
        self.c2.addWidget(self.lb_hours)
        self.c2.addSpacing(7)
        self.pb = QProgressBar()
        self.pb.setMaximum(1000)
        self.pb.setTextVisible(False)
        self.pb.setFixedHeight(8)
        self.c2.addWidget(self.pb)
        self.L.addWidget(card2)
        self._space(14)

        # ---------------- 趣味文案 / 主按钮 ---------------- #
        self.lb_fun = QLabel("再过 2 小时 54 分，一件 T 恤就摸回来了。")
        self.lb_fun.setObjectName("Fun")
        self.lb_fun.setWordWrap(True)
        self.L.addWidget(self.lb_fun)
        self._space(12)

        self.btn_pause = QPushButton("暂停摸鱼")
        self.btn_pause.setObjectName("Primary")
        self.btn_pause.setFixedHeight(44)
        self.btn_pause.clicked.connect(self.app.toggle_pause)
        self.L.addWidget(self.btn_pause)
        self._space(9)

        tools = QHBoxLayout()
        tools.setSpacing(7)
        self.btn_widget = QPushButton("桌面小组件")
        self.btn_widget.setObjectName("Ghost")
        self.btn_widget.setCheckable(True)
        self.btn_widget.setToolTip("开启 / 关闭可拖动的桌面小组件")
        self.btn_widget.toggled.connect(self.app.toggle_widget)
        btn_reset = QPushButton("重置今日")
        btn_reset.setObjectName("Ghost")
        btn_reset.setToolTip("清空今日暂停记录，从上班时间重新累计")
        btn_reset.clicked.connect(self.app.reset_today)
        btn_tray = QPushButton("收进托盘" if win.IS_WINDOWS else "隐藏窗口")
        btn_tray.setObjectName("Ghost")
        btn_tray.setToolTip("收进系统托盘，点托盘图标可再打开。" if win.IS_WINDOWS
                            else "隐藏主窗口；点程序坞（Dock）图标或菜单栏图标可再打开。")
        btn_tray.clicked.connect(self.app.minimize_main)
        tools.addWidget(self.btn_widget, 2)
        tools.addWidget(btn_reset, 1)
        tools.addWidget(btn_tray, 1)
        self.L.addLayout(tools)
        self._space(13)

        self.line = QFrame()
        self.line.setFrameShape(QFrame.HLine)
        self.line.setFixedHeight(1)
        self.line.setStyleSheet("background: rgba(120,132,170,0.22); border: none;")
        self.L.addWidget(self.line)
        self._space(11)

        # ---------------- 底部统计 ---------------- #
        stat = QHBoxLayout()
        k = QLabel("本月累计")
        k.setObjectName("StatKey")
        self.lb_month = QLabel("¥0.0000")
        self.lb_month.setObjectName("StatValue")
        stat.addWidget(k)
        stat.addStretch(1)
        stat.addWidget(self.lb_month)
        self.L.addLayout(stat)
        self.lb_note = QLabel("已过的日子按满勤补算。本月只计已赚，不含亏损。")
        self.lb_note.setObjectName("Hint")
        self.lb_note.setWordWrap(True)
        self.L.addWidget(self.lb_note)
        self._space(9)

        stat2 = QHBoxLayout()
        self.lb_rate = QLabel("时薪 ¥17.24 · 日薪 ¥129.30")
        self.lb_rate.setObjectName("Hint")
        self.lb_rate.setWordWrap(True)
        self.lb_full = QLabel("今日满勤可得 ¥129.30")
        self.lb_full.setObjectName("Hint")
        self.lb_full.setWordWrap(True)
        stat2.addWidget(self.lb_rate, 1)
        stat2.addStretch(1)
        stat2.addWidget(self.lb_full, 1)
        self.L.addLayout(stat2)
        self.L.addStretch(1)

        self.foot = QLabel(f"{APP_NAME} · 摸鱼是带薪的　v{APP_VERSION}")
        self.foot.setObjectName("Brand")
        self.foot.setWordWrap(True)
        self.L.addWidget(self.foot)

        self.apply_theme(cfg.theme)

        # ---- 尺寸与位置：无级可调，记忆上次尺寸，夹在可用屏幕内 ---- #
        screen = self.app.available_geometry()
        size = cfg.main_size
        w = max(MIN_W, min(1600, int(size[0]))) if size and len(size) == 2 else WIN_W
        h = max(MIN_H, min(1200, int(size[1]))) if size and len(size) == 2 else WIN_H
        w, h = min(w, max(MIN_W, screen.width())), min(h, max(MIN_H, screen.height()))
        self.resize(w, h)
        pos = cfg.main_pos
        if pos and len(pos) == 2:
            x, y = pos[0], pos[1]
        else:
            x, y = screen.center().x() - w // 2, screen.center().y() - h // 2
        x = max(screen.left(), min(x, screen.left() + screen.width() - w))
        y = max(screen.top(), min(y, screen.top() + screen.height() - h))
        self.move(x, y)

        # 所有子控件都把鼠标事件交给窗口过滤器，保证任意位置都能命中边缘
        self.setMouseTracking(True)
        for child in self.findChildren(QWidget):
            child.setMouseTracking(True)
            child.installEventFilter(self)
        self.installEventFilter(self)
        self.apply_responsive(force=True)

    def _space(self, base: int) -> None:
        """插入可随窗口尺寸缩放的间距。"""
        self.L.addSpacing(base)
        item = self.L.itemAt(self.L.count() - 1)
        self._spacers.append((item, base))

    # ------------------------------------------------------------------ #
    # 无级调整尺寸（边缘 / 四角连续拖拽）
    # ------------------------------------------------------------------ #
    def _edges_at(self, lp: QPoint) -> tuple[int, int]:
        """返回 (水平边, 垂直边)：-1 左/上，+1 右/下，0 不在边缘。"""
        h = -1 if lp.x() <= EDGE else (1 if lp.x() >= self.width() - EDGE else 0)
        v = -1 if lp.y() <= EDGE else (1 if lp.y() >= self.height() - EDGE else 0)
        # 顶部中间留给标题栏拖动，只有四角才允许向上缩放
        if v == -1 and h == 0:
            v = 0
        return h, v

    @staticmethod
    def _cursor_for(h: int, v: int) -> Qt.CursorShape:
        if h and v:
            return Qt.SizeFDiagCursor if h * v > 0 else Qt.SizeBDiagCursor
        if h:
            return Qt.SizeHorCursor
        if v:
            return Qt.SizeVerCursor
        return Qt.ArrowCursor

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        et = event.type()
        if et == QEvent.Wheel:
            # Ctrl(⌘)+滚轮：整体缩放；不带修饰键则把滚轮交给内容滚动
            if isinstance(event, QWheelEvent) and (event.modifiers() & Qt.ControlModifier):
                steps = event.angleDelta().y() / 120.0
                if steps:
                    self.zoom_by(steps * ZOOM_STEP)
                return True
            return False
        if et not in (QEvent.MouseButtonPress, QEvent.MouseMove,
                      QEvent.MouseButtonRelease, QEvent.Leave):
            return super().eventFilter(obj, event)
        if not isinstance(event, QMouseEvent):
            return super().eventFilter(obj, event)

        if et == QEvent.Leave:
            if not self._resize and not self._drag_offset:
                self.unsetCursor()
            return False

        gp = (event.globalPosition().toPoint() if hasattr(event, "globalPosition")
              else event.globalPos())
        h, v = self._edges_at(self.mapFromGlobal(gp))

        if et == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if h or v:
                self._resize = {"h": h, "v": v, "geo": QRect(self.geometry()), "gp": gp}
                return True
            # 整窗拖动：按在空白区域 / 标签 / 卡片上都直接拖窗口；
            # 按钮与滚动条保持原本的点击行为
            if isinstance(obj, (QAbstractButton, QScrollBar)):
                return False
            self._drag_offset = gp - self.frameGeometry().topLeft()
            return True
        if et == QEvent.MouseMove and self._drag_offset and (event.buttons() & Qt.LeftButton):
            screen = self.app.available_geometry()
            np = gp - self._drag_offset
            np.setX(max(screen.left() - self.width() + 60,
                        min(np.x(), screen.right() - 60)))
            np.setY(max(screen.top(), min(np.y(), screen.bottom() - 24)))
            self.move(np)
            return True
        if et == QEvent.MouseButtonRelease and self._drag_offset:
            self._drag_offset = None
            self._save_size()
            return True
        if et == QEvent.MouseButtonRelease and self._resize:
            self._resize = None
            self.unsetCursor()
            self._save_size()
            self.apply_responsive(force=True)
            return True
        if et == QEvent.MouseMove and self._resize:
            st = self._resize
            g = QRect(st["geo"])
            dx, dy = gp.x() - st["gp"].x(), gp.y() - st["gp"].y()
            screen = self.app.available_geometry()
            if st["h"] == -1:
                left = max(screen.left(), min(g.left() + dx, g.right() - MIN_W))
                g.setLeft(left)
            elif st["h"] == 1:
                right = min(screen.right(), max(g.right() + dx, g.left() + MIN_W))
                g.setRight(right)
            if st["v"] == -1:
                top = max(screen.top(), min(g.top() + dy, g.bottom() - MIN_H))
                g.setTop(top)
            elif st["v"] == 1:
                bottom = min(screen.bottom(), max(g.bottom() + dy, g.top() + MIN_H))
                g.setBottom(bottom)
            self.setGeometry(g)
            return True
        if et == QEvent.MouseMove:
            self.setCursor(self._cursor_for(h, v))
        return False

    def _save_size(self) -> None:
        self.app.cfg.main_size = [self.width(), self.height()]
        self.app.cfg.main_pos = [self.x(), self.y()]
        self.app.save_config()

    def zoom_by(self, factor: float) -> None:
        """Ctrl/⌘+滚轮整体缩放：等比改变窗口尺寸，布局按同一比例自适应。

        缩放即改窗口大小，因此字号、间距、卡片全部跟着变，
        不存在「内容被放大后溢出窗口」的遮挡问题。
        """
        s = max(MIN_SCALE, min(MAX_SCALE, self._scale * (1.0 + factor)))
        w = min(int(round(WIN_W * s)), max(MIN_W, self.app.available_geometry().width()))
        h = min(int(round(WIN_H * s)), max(MIN_H, self.app.available_geometry().height()))
        if (w, h) == (self.width(), self.height()):
            return
        screen = self.app.available_geometry()
        center = self.geometry().center()
        x = max(screen.left(), min(center.x() - w // 2, screen.right() - w))
        y = max(screen.top(), min(center.y() - h // 2, screen.bottom() - h))
        self.setGeometry(x, y, w, h)
        self._zoom_save.start()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.apply_responsive()

    # ------------------------------------------------------------------ #
    # 响应式布局：一个比例同时缩放字号、间距、内边距与固定高度
    # ------------------------------------------------------------------ #
    def apply_responsive(self, force: bool = False) -> None:
        if self._applying:
            return
        s = max(MIN_SCALE, min(MAX_SCALE,
                               min(self.width() / WIN_W, self.height() / WIN_H)))
        s = round(s, 3)
        if not force and abs(s - self._scale) < 0.012:
            return
        self._applying = True
        try:
            self._scale = s
            px = lambda v: max(1, int(round(v * s)))  # noqa: E731
            self.setStyleSheet(qss(palette_for(self.app.cfg), scale=s))
            self.outer.setContentsMargins(px(11), px(11), px(11), px(11))
            self.sL.setContentsMargins(px(20), px(8), px(20), px(12))
            # 头部：高度 / 按钮尺寸 / 与内容区的间距全部随缩放等比变化，
            # 保证放大后文字仍在按钮内、缩小后不变形
            self.handle.setFixedHeight(px(38))
            self.btn_top.setFixedSize(px(46), px(30))
            self.btn_min.setFixedSize(px(30), px(30))
            self.btn_close.setFixedSize(px(30), px(30))
            self.btn_settings.setFixedHeight(px(28))
            self.btn_settings.setMinimumWidth(px(72))
            self.hL.setContentsMargins(0, 0, 0, px(14))
            self.btn_pause.setFixedHeight(px(44))
            self.pb.setFixedHeight(px(8))
            self.line.setFixedHeight(1)
            self.c1.setContentsMargins(px(16), px(12), px(16), px(13))
            self.c2.setContentsMargins(px(16), px(12), px(16), px(13))
            self.c1.setSpacing(px(2))
            self.c2.setSpacing(px(2))
            for item, base in self._spacers:
                item.changeSize(0, max(2, px(base)),
                                QSizePolicy.Minimum, QSizePolicy.Fixed)
        finally:
            self._applying = False

    # ------------------------------------------------------------------ #
    def apply_theme(self, key: str | None = None) -> None:
        """重算主界面调色板：主题切换与自定义色相都走这里，立即重绘。"""
        pal = palette_for(self.app.cfg)
        self.bg.set_palette(pal)
        self.setStyleSheet(qss(pal, scale=self._scale))
        self.update()

    def clear_transient_button_state(self) -> None:
        """复位按钮上的悬停高亮 / 按下态 / 焦点框，并隐藏悬浮提示。

        模态对话框（设置、更新弹窗）盖住按钮时会吞掉 Leave 事件，
        关闭后按钮一直停留在 :hover 高亮，看起来像「按钮上多了个悬浮框」；
        在打开与关闭对话框后各调用一次，把状态手动复位并强制重绘。
        """
        QToolTip.hideText()
        self.unsetCursor()
        for btn in self.findChildren(QAbstractButton):
            btn.setDown(False)
            btn.setAttribute(Qt.WA_UnderMouse, False)
            btn.clearFocus()
            style = btn.style()
            style.unpolish(btn)
            style.polish(btn)
            btn.update()

    def set_always_on_top(self, flag: bool) -> None:
        base = Qt.FramelessWindowHint | Qt.Window
        if flag:
            base |= Qt.WindowStaysOnTopHint
        if self.windowFlags() != base:
            was_visible = self.isVisible()
            self.setWindowFlags(base)
            if was_visible:
                self.show()
        self.btn_top.blockSignals(True)
        self.btn_top.setChecked(flag)
        self.btn_top.blockSignals(False)

    def closeEvent(self, event) -> None:  # noqa: N802
        self.app.on_main_close(event)

    # ------------------------------------------------------------------ #
    def update_snapshot(self, snap: Snapshot, cfg, state) -> None:
        self.lb_date.setText(snap.date_text)
        self.lb_status.setText(snap.status_text)
        self.lb_countdown.setText(snap.countdown_text)
        sync = ("日历离线沿用" if getattr(self.app, "calendar_offline", False)
                else "日历已同步" if cfg.calendar_updated_at else "日历待同步")
        self.lb_daykind.setText(f"今日：{day_kind_label(snap.day_kind)}　·　{sync}")

        self.lb_money.setText(format_money(snap.earned_today, cfg.decimals))
        if snap.status == "lunch":
            self.lb_speed.setText(f"午休中 · 计费已暂停，{cfg.lunch_end} 恢复"
                                  f"　·　今日满勤 ¥{snap.full_pay:,.2f}")
        elif snap.status == "before":
            self.lb_speed.setText(f"还没上班 · 上班后开始累计"
                                  f"　·　今日满勤 ¥{snap.full_pay:,.2f}")
        elif snap.status == "rest":
            self.lb_speed.setText(f"休息日 · 不计薪（调休除外）"
                                  f"　·　今日满勤 ¥{snap.full_pay:,.2f}")
        else:
            self.lb_speed.setText(f"当前摸鱼进账 ¥{snap.per_second:.4f} / 秒"
                                  f"　·　今日满勤 ¥{snap.full_pay:,.2f}")

        self.lb_duration.setText(format_hms(snap.fished_seconds))
        self.lb_hours.setText(
            f"已摸 {snap.fished_hours:.2f} / {snap.full_hours:.2f} 小时"
            f"　·　今日工时进度 {snap.progress * 100:.1f}%"
        )
        self.pb.setValue(int(snap.progress * 1000))

        self.lb_fun.setText(snap.fun_text)
        self.btn_pause.setText("继续摸鱼" if state.paused else "暂停摸鱼")
        self.lb_month.setText(f"¥{format_money(snap.month_total, cfg.decimals)}")
        self.lb_rate.setText(f"时薪 ¥{snap.rate:,.2f} · 日薪 ¥{cfg.daily_salary:,.2f}")
        self.lb_full.setText(f"今日满勤可得 ¥{snap.full_pay:,.2f}")

        self.btn_widget.blockSignals(True)
        self.btn_widget.setChecked(bool(self.app.widget and self.app.widget.isVisible()))
        self.btn_widget.blockSignals(False)
