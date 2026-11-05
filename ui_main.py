# -*- coding: utf-8 -*-
"""今天摸了吗 · 主窗口

布局对齐参考视频：日期时间 / 状态 / 倒计时 / 大号实时金额 / 速度 /
趣味文案 / 主按钮 / 进度 / 本月累计 / 时薪与满勤，
并把「今日混底薪【工资】」与「已摸鱼时长」提升为两大主数据。
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from core import APP_NAME, APP_VERSION, Snapshot, format_hms, format_money
from theme import SoftGradient, qss, theme

if TYPE_CHECKING:
    from main import MoyuApp

WIN_W, WIN_H = 432, 706


class DragHandle(QWidget):
    """自绘标题栏：按住可拖动无边框窗口。"""

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
        self.setFixedSize(WIN_W, WIN_H)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(11, 11, 11, 11)   # 给柔光阴影留出空间
        self.bg = SoftGradient(self, cfg.theme, radius=20, glow=True)
        outer.addWidget(self.bg)
        shadow = QGraphicsDropShadowEffect(self.bg)
        shadow.setBlurRadius(26)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(70, 78, 125, 48))
        self.bg.setGraphicsEffect(shadow)

        L = QVBoxLayout(self.bg)
        L.setContentsMargins(20, 8, 20, 12)
        L.setSpacing(0)

        # ---------------- 标题栏 ---------------- #
        handle = DragHandle(self)
        hl = QHBoxLayout(handle)
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
        btn_min = QPushButton("—")
        btn_min.setObjectName("WinBtn")
        btn_min.setFixedWidth(30)
        btn_min.clicked.connect(self.app.minimize_main)
        btn_close = QPushButton("×")
        btn_close.setObjectName("WinBtn")
        btn_close.setFixedWidth(30)
        btn_close.setToolTip("关闭（可在设置里改为最小化到托盘）")
        btn_close.clicked.connect(self.app.close_main)
        hl.addWidget(self.btn_top)
        hl.addWidget(btn_min)
        hl.addWidget(btn_close)
        L.addWidget(handle)

        # ---------------- 日期 / 设置 ---------------- #
        row = QHBoxLayout()
        self.lb_date = QLabel("—")
        self.lb_date.setObjectName("DateLine")
        self.btn_settings = QPushButton("⚙  设置")
        self.btn_settings.setObjectName("Ghost")
        self.btn_settings.setFixedHeight(28)
        self.btn_settings.clicked.connect(self.app.open_settings)
        row.addWidget(self.lb_date)
        row.addStretch(1)
        row.addWidget(self.btn_settings)
        L.addLayout(row)
        L.addSpacing(14)

        # ---------------- 状态 / 倒计时 ---------------- #
        self.lb_status = QLabel("摸鱼中")
        self.lb_status.setObjectName("Status")
        L.addWidget(self.lb_status)
        self.lb_countdown = QLabel("距离下班还有 —")
        self.lb_countdown.setObjectName("Countdown")
        L.addWidget(self.lb_countdown)
        L.addSpacing(16)

        # ---------------- 主数据 1：今日混底薪 ---------------- #
        card1 = QFrame()
        card1.setObjectName("Card")
        c1 = QVBoxLayout(card1)
        c1.setContentsMargins(16, 12, 16, 13)
        c1.setSpacing(2)
        lab = QLabel("今日混底薪【工资】")
        lab.setObjectName("FieldLabel")
        c1.addWidget(lab)
        money_row = QHBoxLayout()
        money_row.setSpacing(3)
        sign = QLabel("¥")
        sign.setObjectName("MoneySign")
        self.lb_money = QLabel("0.0000")
        self.lb_money.setObjectName("Money")
        money_row.addWidget(sign)
        money_row.addWidget(self.lb_money)
        money_row.addStretch(1)
        c1.addLayout(money_row)
        self.lb_speed = QLabel("当前摸鱼进账 ¥0.0000 / 秒")
        self.lb_speed.setObjectName("Hint")
        c1.addWidget(self.lb_speed)
        L.addWidget(card1)
        L.addSpacing(10)

        # ---------------- 主数据 2：已摸鱼时长 ---------------- #
        card2 = QFrame()
        card2.setObjectName("Card")
        c2 = QVBoxLayout(card2)
        c2.setContentsMargins(16, 12, 16, 13)
        c2.setSpacing(2)
        lab2 = QLabel("已摸鱼时长")
        lab2.setObjectName("FieldLabel")
        c2.addWidget(lab2)
        self.lb_duration = QLabel("00:00:00")
        self.lb_duration.setObjectName("Duration")
        c2.addWidget(self.lb_duration)
        self.lb_hours = QLabel("已摸 0.00 / 7.50 小时 · 0.0%")
        self.lb_hours.setObjectName("Hint")
        c2.addWidget(self.lb_hours)
        c2.addSpacing(7)
        self.pb = QProgressBar()
        self.pb.setMaximum(1000)
        self.pb.setTextVisible(False)
        self.pb.setFixedHeight(8)
        c2.addWidget(self.pb)
        L.addWidget(card2)
        L.addSpacing(14)

        # ---------------- 趣味文案 / 主按钮 ---------------- #
        self.lb_fun = QLabel("再过 2 小时 54 分，一件 T 恤就摸回来了。")
        self.lb_fun.setObjectName("Fun")
        self.lb_fun.setWordWrap(True)
        L.addWidget(self.lb_fun)
        L.addSpacing(12)

        self.btn_pause = QPushButton("暂停摸鱼")
        self.btn_pause.setObjectName("Primary")
        self.btn_pause.setFixedHeight(44)
        self.btn_pause.clicked.connect(self.app.toggle_pause)
        L.addWidget(self.btn_pause)
        L.addSpacing(9)

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
        L.addLayout(tools)
        L.addSpacing(13)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFixedHeight(1)
        line.setStyleSheet("background: rgba(120,132,170,0.22); border: none;")
        L.addWidget(line)
        L.addSpacing(11)

        # ---------------- 底部统计 ---------------- #
        stat = QHBoxLayout()
        k = QLabel("本月累计")
        k.setObjectName("StatKey")
        self.lb_month = QLabel("¥0.0000")
        self.lb_month.setObjectName("StatValue")
        stat.addWidget(k)
        stat.addStretch(1)
        stat.addWidget(self.lb_month)
        L.addLayout(stat)
        note = QLabel("已过的日子按满勤补算。本月只计已赚，不含亏损。")
        note.setObjectName("Hint")
        L.addWidget(note)
        L.addSpacing(9)

        stat2 = QHBoxLayout()
        self.lb_rate = QLabel("时薪 ¥17.24 · 日薪 ¥129.30")
        self.lb_rate.setObjectName("Hint")
        self.lb_full = QLabel("今日满勤可得 ¥129.30")
        self.lb_full.setObjectName("Hint")
        stat2.addWidget(self.lb_rate)
        stat2.addStretch(1)
        stat2.addWidget(self.lb_full)
        L.addLayout(stat2)
        L.addStretch(1)

        foot = QLabel(f"{APP_NAME} · 摸鱼是带薪的　v{APP_VERSION}")
        foot.setObjectName("Brand")
        L.addWidget(foot)

        self.apply_theme(cfg.theme)
        pos = cfg.main_pos
        screen = self.app.available_geometry()
        if pos and len(pos) == 2:
            x, y = pos[0], pos[1]
        else:
            x, y = screen.center().x() - WIN_W // 2, screen.center().y() - WIN_H // 2
        # 窗口固定 432x706，位置必须夹在可用屏幕内，避免小屏 / 改分辨率后跑到屏幕外
        x = max(screen.left(), min(x, screen.left() + screen.width() - WIN_W))
        y = max(screen.top(), min(y, screen.top() + screen.height() - WIN_H))
        self.move(x, y)

    # ------------------------------------------------------------------ #
    def apply_theme(self, key: str) -> None:
        self.bg.set_theme(key)
        self.setStyleSheet(qss(theme(key)))

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
