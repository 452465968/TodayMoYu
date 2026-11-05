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

from PySide6.QtCore import QEvent, QRect, Qt, QPoint
from PySide6.QtGui import QColor, QMouseEvent
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from core import APP_NAME, APP_VERSION, Snapshot, day_kind_label, format_hms, format_money
from theme import SoftGradient, qss, theme

if TYPE_CHECKING:
    from main import MoyuApp

WIN_W, WIN_H = 432, 724          # 默认尺寸（可任意调整）
MIN_W, MIN_H = 340, 500          # 再小会牺牲可读性
MAX_SCALE, MIN_SCALE = 1.60, 0.70
EDGE = 9                         # 边缘命中宽度（像素）


class DragHandle(QWidget):
    """自绘标题栏：按住可拖动无边框窗口（顶部中间不参与缩放）。"""

    def __init__(self, window: "MainWindow"):
        super().__init__(window)
        self.window = window
        self._offset: QPoint | None = None
        self.setFixedHeight(38)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._offset = event.globalPosition().toPoint() - self.window.frameGeometry().topLeft()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._offset and (event.buttons() & Qt.LeftButton):
            self.window.move(event.globalPosition().toPoint() - self._offset)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._offset:
            g = self.window.frameGeometry()
            self.window.app.cfg.main_pos = [g.x(), g.y()]
            self.window.app.save_config()
        self._offset = None
        super().mouseReleaseEvent(event)


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
        self._spacers: list[tuple[object, int]] = []

        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(11, 11, 11, 11)   # 给柔光阴影留出空间
        self.bg = SoftGradient(self, cfg.theme, radius=20, glow=True)
        self.outer.addWidget(self.bg)
        shadow = QGraphicsDropShadowEffect(self.bg)
        shadow.setBlurRadius(26)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(70, 78, 125, 48))
        self.bg.setGraphicsEffect(shadow)

        self.L = QVBoxLayout(self.bg)
        self.L.setContentsMargins(20, 8, 20, 12)
        self.L.setSpacing(0)

        # ---------------- 标题栏 ---------------- #
        self.handle = DragHandle(self)
        hl = QHBoxLayout(self.handle)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(2)
        brand = QLabel(f"◉  {APP_NAME}")
        brand.setObjectName("Title")
        brand.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        hl.addWidget(brand)
        hl.addStretch(1)
        self.btn_top = QPushButton("置顶")
        self.btn_top.setObjectName("WinBtn")
        self.btn_top.setCheckable(True)
        self.btn_top.setFixedWidth(46)
        self.btn_top.setToolTip("让主窗口始终显示在其他窗口之上")
        self.btn_top.toggled.connect(self.app.toggle_always_on_top)
        self.btn_min = QPushButton("—")
        self.btn_min.setObjectName("WinBtn")
        self.btn_min.setFixedWidth(30)
        self.btn_min.clicked.connect(self.app.minimize_main)
        self.btn_close = QPushButton("×")
        self.btn_close.setObjectName("WinBtn")
        self.btn_close.setFixedWidth(30)
        self.btn_close.setToolTip("关闭（可在设置里改为最小化到托盘）")
        self.btn_close.clicked.connect(self.app.close_main)
        hl.addWidget(self.btn_top)
        hl.addWidget(self.btn_min)
        hl.addWidget(self.btn_close)
        self.L.addWidget(self.handle)

        # ---------------- 日期 / 设置 ---------------- #
        row = QHBoxLayout()
        self.lb_date = QLabel("—")
        self.lb_date.setObjectName("DateLine")
        self.lb_date.setWordWrap(True)
        self.btn_settings = QPushButton("⚙  设置")
        self.btn_settings.setObjectName("Ghost")
        self.btn_settings.setFixedHeight(28)
        self.btn_settings.clicked.connect(self.app.open_settings)
        row.addWidget(self.lb_date, 1)
        row.addStretch(1)
        row.addWidget(self.btn_settings)
        self.L.addLayout(row)
        self._space(14)

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
        btn_tray = QPushButton("收进托盘")
        btn_tray.setObjectName("Ghost")
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
        if et not in (QEvent.MouseButtonPress, QEvent.MouseMove,
                      QEvent.MouseButtonRelease, QEvent.Leave):
            return super().eventFilter(obj, event)
        if not isinstance(event, QMouseEvent):
            return super().eventFilter(obj, event)

        if et == QEvent.Leave:
            if not self._resize:
                self.unsetCursor()
            return False

        gp = (event.globalPosition().toPoint() if hasattr(event, "globalPosition")
              else event.globalPos())
        h, v = self._edges_at(self.mapFromGlobal(gp))

        if et == QEvent.MouseButtonPress and event.button() == Qt.LeftButton and (h or v):
            self._resize = {"h": h, "v": v, "geo": QRect(self.geometry()), "gp": gp}
            return True
        if et == QEvent.MouseButtonRelease and self._resize:
            self._resize = None
            self.unsetCursor()
            self.app.cfg.main_size = [self.width(), self.height()]
            self.app.cfg.main_pos = [self.x(), self.y()]
            self.app.save_config()
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
            self.setStyleSheet(qss(theme(self.app.cfg.theme), scale=s))
            self.outer.setContentsMargins(px(11), px(11), px(11), px(11))
            self.L.setContentsMargins(px(20), px(8), px(20), px(12))
            self.handle.setFixedHeight(px(38))
            self.btn_top.setFixedWidth(px(46))
            self.btn_min.setFixedWidth(px(30))
            self.btn_close.setFixedWidth(px(30))
            self.btn_settings.setFixedHeight(px(28))
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
    def apply_theme(self, key: str) -> None:
        self.bg.set_theme(key)
        self.setStyleSheet(qss(theme(key), scale=self._scale))

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
