# -*- coding: utf-8 -*-
"""今天摸了吗 · 设置窗口"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate, QTime, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDateEdit, QDialog,
    QDoubleSpinBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QFrame,
    QSlider, QSpinBox, QTabWidget, QTimeEdit, QVBoxLayout, QWidget,
)

import wallpaper_color
import win32_extra as win
from core import (
    APP_NAME, APP_VERSION, DAY_NAMES, REFRESH_UNITS, WIDGET_SCALE_MAX, WIDGET_SCALE_MIN,
    Settings, app_data_dir,
    calendar_sync_interval_ms, day_kind_label, full_work_seconds, hourly_rate,
    validate_refresh_interval,
)
from theme import THEMES, palette, recolor, settings_qss, theme

if TYPE_CHECKING:
    from main import MoyuApp

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _spin(value: float, lo: float, hi: float, step: float, decimals: int = 2,
          suffix: str = "") -> QDoubleSpinBox:
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setSingleStep(step)
    w.setDecimals(decimals)
    w.setValue(value)
    if suffix:
        w.setSuffix(suffix)
    return w


def _time(value: str) -> QTimeEdit:
    h, m = value.split(":")
    w = QTimeEdit()
    w.setDisplayFormat("HH:mm")
    w.setTime(QTime(int(h), int(m)))
    return w


def _hhmm(w: QTimeEdit) -> str:
    return w.time().toString("HH:mm")


class HueRow(QWidget):
    """一行「色相」调节：色板 + 连续滑块 + 度数。

    只改色相、不改明度饱和度，因此无论选什么颜色，文字对比度都不会被破坏；
    点色板会打开系统取色器，取到的颜色只提取色相，其余保持主题设定。
    """

    def __init__(self, label: str, base_color: str, hue: int,
                 on_change=None, parent=None):
        super().__init__(parent)
        self.base_color = base_color
        self._label = label
        self._cb = QCheckBox("跟随")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        name = QLabel(label)
        name.setMinimumWidth(46)
        self.swatch = QPushButton()
        self.swatch.setFixedSize(38, 22)
        self.swatch.setToolTip("点这里打开取色器（只取色相）")
        self.swatch.clicked.connect(self._pick)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 359)
        self.slider.setSingleStep(1)
        self.slider.setPageStep(12)
        self.val = QLabel("")
        self.val.setFixedWidth(38)
        row.addWidget(name)
        row.addWidget(self.swatch)
        row.addWidget(self.slider, 1)
        row.addWidget(self.val)
        row.addWidget(self._cb)

        self._base_hue = max(0, QColor(base_color).hue())
        self._on_change = on_change
        self.slider.valueChanged.connect(self._refresh)
        self._cb.toggled.connect(self._refresh)
        self.set_hue(hue)

    # -- 内部 -- #
    def _refresh(self, *_args) -> None:
        follow = self._cb.isChecked()
        self.slider.setEnabled(not follow)
        hue = self._base_hue if follow else self.slider.value()
        color = recolor(self.base_color, hue)
        self.swatch.setStyleSheet(
            f"QPushButton {{ background: {color}; border: 1px solid rgba(120,132,170,0.35);"
            f" border-radius: 6px; }}")
        self.val.setText("跟随" if follow else f"{hue}°")
        if self._on_change:
            self._on_change()

    def _pick(self) -> None:
        start = QColor(recolor(self.base_color, self.hue()))
        color = QColorDialog.getColor(start, self, "选择颜色（只取色相）")
        # 取色器是模态窗口，会吞掉色板的 Leave 事件；关闭后手动复位悬停态
        self.swatch.setDown(False)
        self.swatch.setAttribute(Qt.WA_UnderMouse, False)
        style = self.swatch.style()
        style.unpolish(self.swatch)
        style.polish(self.swatch)
        self.swatch.update()
        if not color.isValid():
            return
        hue = color.hue()
        if hue < 0:                       # 灰色没有色相，保持原值
            return
        self._cb.setChecked(False)
        self.slider.setValue(hue)

    # -- 对外 -- #
    def hue(self) -> int:
        return -1 if self._cb.isChecked() else self.slider.value()

    def set_hue(self, hue: int) -> None:
        follow = hue is None or hue < 0
        self._cb.blockSignals(True)
        self._cb.setChecked(follow)
        self._cb.blockSignals(False)
        if not follow:
            self.slider.blockSignals(True)
            self.slider.setValue(int(hue))
            self.slider.blockSignals(False)
        self._refresh()

    def set_enabled(self, flag: bool) -> None:
        self.setEnabled(bool(flag))

    def set_base(self, color: str) -> None:
        """主题切换后更新基准色：跟随态直接显示新主题的颜色。"""
        self.base_color = color
        self._base_hue = max(0, QColor(color).hue())
        self._refresh()


class SettingsDialog(QDialog):
    def __init__(self, app: "MoyuApp", tab: int | None = None):
        super().__init__(app.window)
        self.app = app
        c = app.cfg
        self.setWindowTitle(f"{APP_NAME} · 设置")
        # 允许自由调整大小：内容放进可滚动区域，窗口最小尺寸不再被内容撑死
        self.setMinimumSize(500, 460)
        self.setSizeGripEnabled(True)
        self.setStyleSheet(settings_qss(theme(c.theme)))
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.MSWindowsFixedSizeDialogHint, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(12)

        header = QLabel(f"{APP_NAME} · 设置")
        header.setObjectName("GroupTitle")
        header.setStyleSheet("font-size: 19px; font-weight: 700;")
        root.addWidget(header)
        sub = QLabel("把底薪、工时和小组件按自己的节奏调好，主界面的数字会立刻重算。")
        sub.setObjectName("Help")
        root.addWidget(sub)

        tabs = QTabWidget()
        tabs.addTab(self._scroll(self._tab_salary(c)), "薪资")
        tabs.addTab(self._scroll(self._tab_schedule(c)), "工时")
        tabs.addTab(self._scroll(self._tab_display(c)), "外观与系统")
        if tab is not None:
            tabs.setCurrentIndex(max(0, min(tabs.count() - 1, int(tab))))
        self.tabs = tabs
        root.addWidget(tabs, 1)

        self.preview = QLabel("")
        self.preview.setObjectName("Help")
        self.preview.setWordWrap(True)
        root.addWidget(self.preview)

        footer = QHBoxLayout()
        btn_reset = QPushButton("重置今日")
        btn_reset.setToolTip("清空今天的暂停记录，重新从上班时间开始计算")
        btn_reset.clicked.connect(self._reset_today)
        btn_dir = QPushButton("打开数据目录")
        btn_dir.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(app_data_dir()))))
        btn_cancel = QPushButton("取消")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("保存设置")
        btn_save.setObjectName("Save")
        btn_save.setDefault(True)
        btn_save.clicked.connect(self._save)
        footer.addWidget(btn_reset)
        footer.addWidget(btn_dir)
        footer.addStretch(1)
        footer.addWidget(btn_cancel)
        footer.addWidget(btn_save)
        root.addLayout(footer)

        self._orig_widget = (c.widget_scale, c.widget_opacity)
        self._orig_colors = (c.accent_hue, c.accent2_hue, c.bg_hue,
                             c.widget_follow_main, c.widget_auto_wallpaper,
                             c.widget_accent_hue,
                             c.widget_accent2_hue, c.widget_bg_hue)
        self._connect_preview()
        self._update_preview()

        # 恢复上次调整过的尺寸，并限制在合理范围内，避免超出屏幕
        size = getattr(c, "settings_size", None)
        w = max(500, min(1100, size[0])) if size and len(size) == 2 else 566
        h = max(460, min(940, size[1])) if size and len(size) == 2 else 690
        screen = app.available_geometry()
        self.resize(min(w, screen.width() - 40), min(h, screen.height() - 80))

    @staticmethod
    def _scroll(inner: QWidget) -> QScrollArea:
        """每个标签页独立滚动：内容再长也不会把整个对话框撑到屏幕外。"""
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        area.setFrameShape(QFrame.NoFrame)
        area.setWidget(inner)
        return area

    def _set_refresh_range(self, unit: str) -> None:
        """按单位切换输入框的合法范围与步进，越界值自动夹回。"""
        label, factor, lo, hi = REFRESH_UNITS.get(unit, REFRESH_UNITS["ms"])
        # v1.5.0：毫秒档步进 10ms，最低 10ms（原先 50ms 起）
        step = {"ms": 10.0, "s": 0.1, "min": 0.1, "h": 0.01}.get(unit, 1.0)
        decimals = {"ms": 0, "s": 2, "min": 3, "h": 3}.get(unit, 0)
        self.ed_refresh.blockSignals(True)
        self.ed_refresh.setDecimals(decimals)
        self.ed_refresh.setRange(lo, hi)
        self.ed_refresh.setSingleStep(step)
        self.ed_refresh.setSuffix(f" {label}")
        self.ed_refresh.blockSignals(False)

    def update_calendar_status(self, text: str | None = None) -> None:
        """接收后台同步结果 / 手动刷新时更新状态标签。"""
        if hasattr(self, "lb_calendar"):
            self.lb_calendar.setText(text or getattr(self.app, "calendar_status_text", ""))

    def _remember_size(self) -> None:
        self.app.cfg.settings_size = [self.width(), self.height()]
        self.app.save_config()

    def _apply_widget_appearance(self, scale: float, opacity: float) -> None:
        w = self.app.widget
        if w is not None and w.isVisible():
            w.set_scale(scale, persist=False)
            w.set_opacity(opacity, persist=False)

    def _preview_widget_appearance(self) -> None:
        s = self.slider_scale.value() / 100.0
        o = self.slider_opacity.value() / 100.0
        self.lb_scale_val.setText(f"{s * 100:.0f}%")
        self.lb_opacity_val.setText(f"{o * 100:.0f}%")
        self.app.cfg.widget_scale = s
        self.app.cfg.widget_opacity = o
        self._apply_widget_appearance(s, o)
        self._preview_colors()

    def reject(self) -> None:  # noqa: N802
        """取消时把实时预览过的小组件外观与配色还原。"""
        s, o = self._orig_widget
        self.app.cfg.widget_scale = s
        self.app.cfg.widget_opacity = o
        (self.app.cfg.accent_hue, self.app.cfg.accent2_hue, self.app.cfg.bg_hue,
         self.app.cfg.widget_follow_main, self.app.cfg.widget_auto_wallpaper,
         self.app.cfg.widget_accent_hue,
         self.app.cfg.widget_accent2_hue, self.app.cfg.widget_bg_hue) = self._orig_colors
        self._apply_widget_appearance(s, o)
        if self.app.window:
            self.app.window.apply_theme()
        if self.app.widget:
            self.app.widget.apply_appearance()
        super().reject()

    # ------------------------------------------------------------------ #
    # 配色：实时预览 / 恢复默认
    # ------------------------------------------------------------------ #
    def _collect_colors(self) -> None:
        """把色相控件的值写进当前配置（预览用，保存时再随草稿落盘）。"""
        c = self.app.cfg
        for row, attr in ((self.hue_accent, "accent_hue"),
                          (self.hue_accent2, "accent2_hue"),
                          (self.hue_bg, "bg_hue")):
            setattr(c, attr, row.hue())
        c.widget_follow_main = self.cb_widget_follow.isChecked()
        c.widget_auto_wallpaper = self.cb_widget_auto.isChecked()
        c.widget_accent_hue = self.hue_w_accent.hue()
        c.widget_accent2_hue = self.hue_w_accent2.hue()
        c.widget_bg_hue = self.hue_w_bg.hue()

    def _preview_colors(self) -> None:
        # 控件是逐个构造的：任何一个还没建好就先跳过，避免构造期回调炸掉
        if not all(hasattr(self, n) for n in
                   ("hue_accent", "hue_accent2", "hue_bg", "hue_w_accent",
                    "hue_w_accent2", "hue_w_bg", "cb_widget_follow",
                    "cb_widget_auto")):
            return
        self._collect_colors()
        if self.app.window:
            self.app.window.apply_theme()
        if self.app.widget:
            self.app.widget.apply_appearance()

    def _on_color_changed(self) -> None:
        self._preview_colors()
        if hasattr(self, "preview"):
            self.preview.setText("配色已实时预览：保存后写入配置，取消则恢复原样。")

    def _reset_colors(self) -> None:
        for row in (self.hue_accent, self.hue_accent2, self.hue_bg,
                    self.hue_w_accent, self.hue_w_accent2, self.hue_w_bg):
            row.set_hue(-1)
        self.cb_widget_auto.setChecked(False)
        self.cb_widget_follow.setChecked(True)
        self.preview.setText("已恢复主题默认配色，保存后生效。")

    def _update_wallpaper_label(self) -> None:
        if not hasattr(self, "lb_wallpaper"):
            return
        if not self.cb_widget_auto.isChecked():
            self.lb_wallpaper.setText("勾选后自动取桌面壁纸主色；换壁纸点「重新匹配」。")
            return
        self.lb_wallpaper.setText(wallpaper_color.describe())

    def _on_widget_auto_toggled(self, checked: bool) -> None:
        """壁纸自动配色开启后，跟随主界面与手动色相都让位（优先级低于自动）。"""
        if hasattr(self, "cb_widget_follow"):
            self.cb_widget_follow.setEnabled(not checked)
        self._on_widget_follow_toggled(self.cb_widget_follow.isChecked()
                                       if hasattr(self, "cb_widget_follow") else False)
        self._update_wallpaper_label()

    def _rematch_wallpaper(self) -> None:
        """换壁纸后手动重取一次主色（清缓存 → 重新解析 → 立即预览）。"""
        wallpaper_color.reset_cache()
        hues = wallpaper_color.auto_hues(force=True)
        if not self.cb_widget_auto.isChecked():
            self.cb_widget_auto.setChecked(True)
        self._update_wallpaper_label()
        self._preview_colors()
        self.preview.setText(
            f"已重新匹配壁纸颜色：主色相 {hues[0]}°，副色相 {hues[1]}°。保存后生效。"
            if hues else "壁纸没有明显主色（纯灰或读取失败），将沿用当前配色。")

    def _check_updates_now(self) -> None:
        """设置页里的「检查更新」：直接走主程序的检查流程（含弹窗）。"""
        self.app.check_updates(manual=True)

    def _on_widget_follow_toggled(self, checked: bool) -> None:
        auto = getattr(self, "cb_widget_auto", None)
        auto_on = bool(auto and auto.isChecked())
        for row in (getattr(self, "hue_w_accent", None),
                    getattr(self, "hue_w_accent2", None),
                    getattr(self, "hue_w_bg", None)):
            if row is None:
                continue
            # 自动匹配壁纸时，手动色相与「跟随主界面」都不生效，控件置灰
            row.set_enabled(not checked and not auto_on)
        if hasattr(self, "hue_accent"):
            self._preview_colors()

    def _on_theme_changed(self) -> None:
        """切换主题时刷新基准色与对话框自身的配色，色相滑块保持不变。"""
        key = self.cb_theme.currentData()
        pal = palette(key)
        for row, base in ((self.hue_accent, pal["accent"]),
                          (self.hue_accent2, pal["accent2"]),
                          (self.hue_bg, pal["glow2"]),
                          (self.hue_w_accent, pal["accent"]),
                          (self.hue_w_accent2, pal["accent2"]),
                          (self.hue_w_bg, pal["glow2"])):
            row.set_base(base)
        self.setStyleSheet(settings_qss(palette(
            key, self.hue_accent.hue(), self.hue_accent2.hue(), self.hue_bg.hue())))
        self._preview_colors()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._remember_size()
        super().closeEvent(event)

    # ------------------------------------------------------------------ #
    # 薪资页
    # ------------------------------------------------------------------ #
    def _tab_salary(self, c: Settings) -> QWidget:
        page = QWidget()
        L = QVBoxLayout(page)
        L.setContentsMargins(10, 14, 10, 10)
        L.setSpacing(12)

        self.mode_group = QButtonGroup(page)
        modes = [("daily", "按日薪（默认，精确复现视频中的 ¥129.30 / ¥17.24）"),
                 ("monthly", "按月薪（月薪 ÷ 计薪天数 ÷ 每日折算工时）"),
                 ("hourly", "按时薪（直接填写每小时多少钱）")]
        for key, text in modes:
            r = QRadioButton(text)
            r.setProperty("mode", key)
            r.setChecked(c.salary_mode == key)
            self.mode_group.addButton(r)
            L.addWidget(r)
        self.mode_group.buttonClicked.connect(lambda _: self._update_preview())

        self.day_box = QGroupBox("日薪（派生值）")
        f1 = QFormLayout(self.day_box)
        self.ed_daily = _spin(c.daily_salary, 0, 1_000_000, 10, 2, " 元 / 天")
        f1.addRow("每日底薪", self.ed_daily)
        day_tip = QLabel("按月薪 / 时薪模式时，日薪由「时薪 × 每日有效工时」自动换算并写入配置，不会保留旧值。")
        day_tip.setObjectName("Help")
        day_tip.setWordWrap(True)
        f1.addRow(day_tip)
        L.addWidget(self.day_box)

        self.month_box = QGroupBox("月薪")
        f2 = QFormLayout(self.month_box)
        self.ed_monthly = _spin(c.monthly_salary, 0, 100_000_000, 100, 2, " 元 / 月")
        self.ed_paydays = _spin(c.pay_days_per_month, 1, 31, 0.25, 2, " 天")
        self.ed_divisor = _spin(c.hourly_divisor_hours, 0.5, 24, 0.5, 2, " 小时")
        f2.addRow("月薪", self.ed_monthly)
        f2.addRow("月计薪天数", self.ed_paydays)
        f2.addRow("时薪折算工时", self.ed_divisor)
        tip = QLabel("中国法定月计薪天数为 21.75 天；折算工时通常填 8 小时。")
        tip.setObjectName("Help")
        tip.setWordWrap(True)
        f2.addRow(tip)
        L.addWidget(self.month_box)

        self.hour_box = QGroupBox("时薪")
        f3 = QFormLayout(self.hour_box)
        self.ed_hourly = _spin(c.hourly_rate, 0, 1_000_000, 1, 2, " 元 / 小时")
        f3.addRow("时薪", self.ed_hourly)
        L.addWidget(self.hour_box)

        self.ed_decimals = QSpinBox()
        self.ed_decimals.setRange(0, 8)          # v1.5.0：支持到小数点后 8 位
        self.ed_decimals.setValue(c.decimals)
        f4 = QFormLayout()
        f4.addRow("金额显示小数位", self.ed_decimals)
        L.addLayout(f4)
        L.addStretch(1)
        return page

    # ------------------------------------------------------------------ #
    # 工时页
    # ------------------------------------------------------------------ #
    def _tab_schedule(self, c: Settings) -> QWidget:
        page = QWidget()
        L = QVBoxLayout(page)
        L.setContentsMargins(10, 14, 10, 10)
        L.setSpacing(12)

        g1 = QGroupBox("上下班时间")
        f1 = QFormLayout(g1)
        self.ed_start = _time(c.work_start)
        self.ed_end = _time(c.work_end)
        f1.addRow("上班时间", self.ed_start)
        f1.addRow("下班时间", self.ed_end)
        hint = QLabel("下班时间早于上班时间时按「跨零点夜班」处理。")
        hint.setObjectName("Help")
        f1.addRow(hint)
        L.addWidget(g1)

        g2 = QGroupBox("午休")
        v2 = QVBoxLayout(g2)
        self.cb_lunch = QCheckBox("扣除午休（午休期间不计薪、不计摸鱼时长）")
        self.cb_lunch.setChecked(c.lunch_enabled)
        v2.addWidget(self.cb_lunch)
        row = QHBoxLayout()
        self.ed_lunch_start = _time(c.lunch_start)
        self.ed_lunch_end = _time(c.lunch_end)
        row.addWidget(QLabel("从"))
        row.addWidget(self.ed_lunch_start)
        row.addWidget(QLabel("到"))
        row.addWidget(self.ed_lunch_end)
        row.addStretch(1)
        v2.addLayout(row)
        L.addWidget(g2)

        g3 = QGroupBox("工作日")
        v3 = QVBoxLayout(g3)
        row3 = QHBoxLayout()
        self.cb_weekdays: list[QCheckBox] = []
        for i, name in enumerate(DAY_NAMES):
            cb = QCheckBox(name)
            cb.setChecked(i in c.workdays)
            self.cb_weekdays.append(cb)
            row3.addWidget(cb)
        v3.addLayout(row3)
        L.addWidget(g3)

        g4 = QGroupBox("特殊日期（每行一个 YYYY-MM-DD）")
        f4 = QFormLayout(g4)
        self.ed_holidays = QPlainTextEdit("\n".join(c.holidays))
        self.ed_holidays.setFixedHeight(66)
        self.ed_makeup = QPlainTextEdit("\n".join(c.makeup_workdays))
        self.ed_makeup.setFixedHeight(66)
        f4.addRow("额外休息日", self.ed_holidays)
        f4.addRow("调休上班日", self.ed_makeup)
        tip = QLabel("调休上班日优先级最高，可覆盖周末与额外休息日。")
        tip.setObjectName("Help")
        f4.addRow(tip)
        L.addWidget(g4)

        g5 = QGroupBox("调休安排（休息日 ↔ 补班日）")
        v5 = QVBoxLayout(g5)
        row5 = QHBoxLayout()
        self.ed_rest_day = QDateEdit()
        self.ed_rest_day.setCalendarPopup(True)
        self.ed_rest_day.setDisplayFormat("yyyy-MM-dd")
        self.ed_rest_day.setDate(QDate.currentDate())
        self.ed_work_day = QDateEdit()
        self.ed_work_day.setCalendarPopup(True)
        self.ed_work_day.setDisplayFormat("yyyy-MM-dd")
        self.ed_work_day.setDate(QDate.currentDate().addDays(7))
        row5.addWidget(QLabel("休息"))
        row5.addWidget(self.ed_rest_day)
        row5.addWidget(QLabel("→ 补班"))
        row5.addWidget(self.ed_work_day)
        btn_add = QPushButton("添加")
        btn_add.setObjectName("Save")
        btn_add.clicked.connect(self._add_makeup_pair)
        row5.addWidget(btn_add)
        v5.addLayout(row5)

        self.list_makeup = QListWidget()
        self.list_makeup.setFixedHeight(84)
        v5.addWidget(self.list_makeup)
        for rest, work in getattr(c, "makeup_pairs", []):
            self._insert_makeup_item(rest, work)

        row5b = QHBoxLayout()
        btn_del = QPushButton("删除选中")
        btn_del.clicked.connect(self._del_makeup_pair)
        btn_quick = QPushButton("今天休息 + 下周六补班")
        btn_quick.clicked.connect(self._quick_makeup)
        row5b.addWidget(btn_del)
        row5b.addWidget(btn_quick)
        row5b.addStretch(1)
        v5.addLayout(row5b)
        tip5 = QLabel("调休休息日不计摸鱼时长，但本月累计按满勤补算（不扣薪）；补班日正常实时计薪。"
                      "主界面会显示「调休休息中 / 调休补班中」。")
        tip5.setObjectName("Help")
        tip5.setWordWrap(True)
        v5.addWidget(tip5)
        L.addWidget(g5)

        g6 = QGroupBox("中国法定节假日与调休日历（自动获取）")
        v6 = QVBoxLayout(g6)
        self.cb_calendar = QCheckBox("自动获取国务院办公厅发布的节假日与调休安排")
        self.cb_calendar.setChecked(c.calendar_auto_sync)
        v6.addWidget(self.cb_calendar)
        self.lb_calendar = QLabel("")
        self.lb_calendar.setObjectName("Help")
        self.lb_calendar.setWordWrap(True)
        v6.addWidget(self.lb_calendar)
        cal_row = QHBoxLayout()
        btn_sync = QPushButton("立即同步")
        btn_sync.setToolTip("立刻联网刷新一次节假日与调休安排")
        btn_sync.clicked.connect(lambda: self.app.sync_calendar_now(force=True))
        cal_row.addWidget(btn_sync)
        cal_row.addStretch(1)
        v6.addLayout(cal_row)
        legend = QLabel(
            "日期判定：" + " / ".join(day_kind_label(k) for k in
                                     ("work", "weekend", "holiday", "makeup_work")) +
            "。放假休息日不计摸鱼时长；调休上班日按正常工作日实时计薪。"
            "网络异常时沿用最近一次成功数据；手动填写的日期优先级更高。"
        )
        legend.setObjectName("Help")
        legend.setWordWrap(True)
        v6.addWidget(legend)
        L.addWidget(g6)
        self.update_calendar_status()
        L.addStretch(1)
        return page

    # ---- 调休列表 ---- #
    def _insert_makeup_item(self, rest: str, work: str) -> None:
        item = QListWidgetItem(f"{rest} 休息  →  {work} 补班")
        item.setData(Qt.UserRole, [rest, work])
        self.list_makeup.addItem(item)

    def _add_makeup_pair(self, rest: str | None = None, work: str | None = None) -> None:
        r = rest or self.ed_rest_day.date().toString("yyyy-MM-dd")
        w = work or self.ed_work_day.date().toString("yyyy-MM-dd")
        if r == w:
            self.preview.setText("调休的休息日与补班日不能是同一天。")
            return
        for i in range(self.list_makeup.count()):
            if self.list_makeup.item(i).data(Qt.UserRole) == [r, w]:
                return
        self._insert_makeup_item(r, w)
        self._update_preview()

    def _del_makeup_pair(self) -> None:
        for it in self.list_makeup.selectedItems():
            self.list_makeup.takeItem(self.list_makeup.row(it))
        self._update_preview()

    def _quick_makeup(self) -> None:
        today = QDate.currentDate()
        days = (6 - today.dayOfWeek() + 7) % 7 or 7   # 下一个周六
        self._add_makeup_pair(today.toString("yyyy-MM-dd"),
                              today.addDays(days).toString("yyyy-MM-dd"))

    # ------------------------------------------------------------------ #
    # 外观与系统页
    # ------------------------------------------------------------------ #
    def _tab_display(self, c: Settings) -> QWidget:
        page = QWidget()
        L = QVBoxLayout(page)
        L.setContentsMargins(10, 14, 10, 10)
        L.setSpacing(10)

        f = QFormLayout()
        self.cb_theme = QComboBox()
        for key, t in THEMES.items():
            self.cb_theme.addItem(t["name"], key)
        idx = self.cb_theme.findData(c.theme)
        self.cb_theme.setCurrentIndex(max(0, idx))
        f.addRow("配色主题", self.cb_theme)
        self.cb_theme.currentIndexChanged.connect(lambda _: self._on_theme_changed())

        self.ed_refresh = QDoubleSpinBox()
        self.ed_refresh.setDecimals(3)
        self.ed_refresh_value = self.ed_refresh          # 兼容旧代码引用
        self.ed_refresh_unit = QComboBox()
        for key, (label, _factor, lo, hi) in REFRESH_UNITS.items():
            self.ed_refresh_unit.addItem(label, key)
        idx = self.ed_refresh_unit.findData(c.refresh_unit)
        self.ed_refresh_unit.setCurrentIndex(max(0, idx))
        self._set_refresh_range(c.refresh_unit)
        self.ed_refresh.setValue(c.refresh_value)
        refresh_row = QHBoxLayout()
        refresh_row.setSpacing(8)
        refresh_row.addWidget(self.ed_refresh, 1)
        refresh_row.addWidget(self.ed_refresh_unit)
        refresh_wrap = QWidget()
        refresh_wrap.setLayout(refresh_row)
        f.addRow("数据刷新间隔", refresh_wrap)
        self.lb_refresh_hint = QLabel("")
        self.lb_refresh_hint.setObjectName("Help")
        self.lb_refresh_hint.setWordWrap(True)
        f.addRow(self.lb_refresh_hint)
        self.ed_refresh_unit.currentIndexChanged.connect(
            lambda _: (self._set_refresh_range(self.ed_refresh_unit.currentData()),
                       self._update_preview()))
        self.ed_refresh.valueChanged.connect(lambda _: self._update_preview())
        L.addLayout(f)

        # ---------------- 自定义配色（主界面） ---------------- #
        base = palette(c.theme)
        g0 = QGroupBox("自定义配色（主界面，拖动即时预览）")
        v0 = QVBoxLayout(g0)
        tip0 = QLabel("只改色相，不改明度与饱和度，因此文字对比度始终达标；"
                      "点色块可打开系统取色器。")
        tip0.setObjectName("Help")
        tip0.setWordWrap(True)
        v0.addWidget(tip0)
        self.hue_accent = HueRow("主色", base["accent"], c.accent_hue, self._on_color_changed)
        self.hue_accent2 = HueRow("副色", base["accent2"], c.accent2_hue, self._on_color_changed)
        self.hue_bg = HueRow("背景", base["glow2"], c.bg_hue, self._on_color_changed)
        for row in (self.hue_accent, self.hue_accent2, self.hue_bg):
            v0.addWidget(row)
        row_reset = QHBoxLayout()
        self.btn_color_reset = QPushButton("恢复主题默认配色")
        self.btn_color_reset.clicked.connect(self._reset_colors)
        row_reset.addWidget(self.btn_color_reset)
        row_reset.addStretch(1)
        v0.addLayout(row_reset)
        L.addWidget(g0)

        g1 = QGroupBox("趣味文案（对应视频里「一件 T 恤」那句）")
        f1 = QFormLayout(g1)
        self.cb_fun = QCheckBox("显示趣味文案")
        self.cb_fun.setChecked(c.fun_enabled)
        self.cb_rotate = QCheckBox("每 20 秒轮换目标（T 恤 / 奶茶 / 电影票 / 火锅 / 球鞋）")
        self.cb_rotate.setChecked(c.fun_rotate)
        self.ed_target_name = QLineEdit(c.fun_target_name)
        self.ed_target_amount = _spin(c.fun_target_amount, 0.01, 1_000_000, 10, 2, " 元")
        f1.addRow(self.cb_fun)
        f1.addRow(self.cb_rotate)
        f1.addRow("目标名称", self.ed_target_name)
        f1.addRow("目标金额", self.ed_target_amount)
        L.addWidget(g1)

        g2 = QGroupBox("窗口与系统")
        v2 = QVBoxLayout(g2)
        self.cb_top = QCheckBox("主窗口置顶")
        self.cb_top.setChecked(c.always_on_top)
        self.cb_tray = QCheckBox("关闭主窗口时最小化到系统托盘（不退出）")
        self.cb_tray.setChecked(c.minimize_to_tray)
        self.cb_autostart = QCheckBox("开机自动启动")
        self.cb_autostart.setChecked(win.is_auto_start() if win.SUPPORTS_AUTOSTART else c.auto_start)
        self.cb_autostart.setEnabled(win.SUPPORTS_AUTOSTART)
        self.cb_widget = QCheckBox("启动时显示桌面小组件")
        self.cb_widget.setChecked(c.widget_visible)
        self.cb_dock = QCheckBox("小组件贴到桌面图层（Win+D 后仍可见）")
        self.cb_dock.setChecked(c.widget_dock_desktop)
        self.cb_dock.setEnabled(win.IS_WINDOWS)
        if not win.IS_WINDOWS:
            self.cb_dock.setChecked(False)
            self.cb_dock.setToolTip("「贴到桌面」依赖 Windows 的 WorkerW 图层；macOS 请用「主窗口置顶」。")
        for cb in (self.cb_top, self.cb_tray, self.cb_autostart, self.cb_widget, self.cb_dock):
            v2.addWidget(cb)

        # ---------------- 自动更新 ---------------- #
        self.cb_auto_update = QCheckBox("启动时自动检查更新（来自 GitHub Releases）")
        self.cb_auto_update.setChecked(c.auto_check_update)
        v2.addWidget(self.cb_auto_update)
        row_up = QHBoxLayout()
        self.lb_version = QLabel(f"当前版本 v{APP_VERSION}")
        self.lb_version.setObjectName("Help")
        self.btn_check_update = QPushButton("检查更新…")
        self.btn_check_update.clicked.connect(self._check_updates_now)
        row_up.addWidget(self.lb_version)
        row_up.addStretch(1)
        row_up.addWidget(self.btn_check_update)
        v2.addLayout(row_up)
        L.addWidget(g2)

        g3 = QGroupBox("桌面小组件外观（拖动即时预览）")
        v3 = QVBoxLayout(g3)
        self.slider_scale = QSlider(Qt.Horizontal)
        # 无级缩放：50%–300% 连续可调，步进 1%
        self.slider_scale.setRange(int(WIDGET_SCALE_MIN * 100), int(WIDGET_SCALE_MAX * 100))
        self.slider_scale.setSingleStep(1)
        self.slider_scale.setPageStep(5)
        self.slider_scale.setValue(int(round(c.widget_scale * 100)))
        self.lb_scale_val = QLabel(f"{int(round(c.widget_scale * 100))}%")
        self.lb_scale_val.setFixedWidth(48)
        row_s = QHBoxLayout()
        row_s.addWidget(QLabel("大小"))
        row_s.addWidget(self.slider_scale, 1)
        row_s.addWidget(self.lb_scale_val)
        v3.addLayout(row_s)

        self.slider_opacity = QSlider(Qt.Horizontal)
        # 透明度同样连续：15%–100%，步进 1%
        self.slider_opacity.setRange(15, 100)
        self.slider_opacity.setSingleStep(1)
        self.slider_opacity.setPageStep(5)
        self.slider_opacity.setValue(int(round(c.widget_opacity * 100)))
        self.lb_opacity_val = QLabel(f"{int(round(c.widget_opacity * 100))}%")
        self.lb_opacity_val.setFixedWidth(48)
        row_o = QHBoxLayout()
        row_o.addWidget(QLabel("不透明度"))
        row_o.addWidget(self.slider_opacity, 1)
        row_o.addWidget(self.lb_opacity_val)
        v3.addLayout(row_o)
        self.cb_widget_auto = QCheckBox("配色自动匹配桌面壁纸（取壁纸主色相）")
        self.cb_widget_auto.setChecked(c.widget_auto_wallpaper)
        v3.addWidget(self.cb_widget_auto)
        row_auto = QHBoxLayout()
        row_auto.setSpacing(8)
        self.lb_wallpaper = QLabel("")
        self.lb_wallpaper.setObjectName("Help")
        self.lb_wallpaper.setWordWrap(True)
        self.btn_wallpaper = QPushButton("重新匹配")
        self.btn_wallpaper.setToolTip("重新读取当前桌面壁纸并提取主色（换壁纸后点这里）")
        self.btn_wallpaper.clicked.connect(self._rematch_wallpaper)
        row_auto.addWidget(self.lb_wallpaper, 1)
        row_auto.addWidget(self.btn_wallpaper)
        v3.addLayout(row_auto)

        self.cb_widget_follow = QCheckBox("配色与主界面一致")
        self.cb_widget_follow.setChecked(c.widget_follow_main)
        v3.addWidget(self.cb_widget_follow)

        self.hue_w_accent = HueRow("主色", base["accent"], c.widget_accent_hue,
                                   self._on_color_changed)
        self.hue_w_accent2 = HueRow("副色", base["accent2"], c.widget_accent2_hue,
                                    self._on_color_changed)
        self.hue_w_bg = HueRow("背景", base["glow2"], c.widget_bg_hue,
                               self._on_color_changed)
        for row in (self.hue_w_accent, self.hue_w_accent2, self.hue_w_bg):
            v3.addWidget(row)

        tip3 = QLabel("文字始终按最高对比度渲染；这里调整的是整个小组件的通透度。"
                     "小组件上还可以用右下角拖拽 / 滚轮连续缩放，Shift+滚轮调透明度。"
                     "点「保存设置」后写入配置，取消则恢复原值。")
        tip3.setObjectName("Help")
        tip3.setWordWrap(True)
        v3.addWidget(tip3)
        self.slider_scale.valueChanged.connect(self._preview_widget_appearance)
        self.slider_opacity.valueChanged.connect(self._preview_widget_appearance)
        self.cb_widget_follow.toggled.connect(self._on_widget_follow_toggled)
        self.cb_widget_auto.toggled.connect(self._on_widget_auto_toggled)
        self._on_widget_auto_toggled(c.widget_auto_wallpaper)
        L.addWidget(g3)

        note = QLabel("提示：小组件也可以在主窗口点「桌面小组件」一键开启，"
                      "拖动移动、右键菜单可调整大小 / 透明度 / 贴桌面。")
        note.setObjectName("Help")
        note.setWordWrap(True)
        L.addWidget(note)
        L.addStretch(1)
        return page

    # ------------------------------------------------------------------ #
    def _connect_preview(self) -> None:
        widgets = [self.ed_daily, self.ed_monthly, self.ed_paydays, self.ed_divisor,
                   self.ed_hourly, self.ed_start, self.ed_end, self.ed_lunch_start,
                   self.ed_lunch_end]
        for w in widgets:
            if hasattr(w, "valueChanged"):
                w.valueChanged.connect(lambda _: self._update_preview())
            elif hasattr(w, "timeChanged"):
                w.timeChanged.connect(lambda _: self._update_preview())
        self.cb_lunch.stateChanged.connect(lambda _: self._update_preview())
        for r in self.mode_group.buttons():
            r.toggled.connect(lambda _: self._update_preview())

    def _draft(self) -> Settings:
        """把界面上的值收集成一份 Settings（不直接改运行中的配置）。"""
        c = Settings.from_dict(vars(self.app.cfg).copy())
        checked = self.mode_group.checkedButton()
        c.salary_mode = checked.property("mode") if checked else "daily"
        c.daily_salary = self.ed_daily.value()
        c.monthly_salary = self.ed_monthly.value()
        c.pay_days_per_month = self.ed_paydays.value()
        c.hourly_divisor_hours = self.ed_divisor.value()
        c.hourly_rate = self.ed_hourly.value()
        c.decimals = self.ed_decimals.value()

        c.work_start = _hhmm(self.ed_start)
        c.work_end = _hhmm(self.ed_end)
        c.lunch_enabled = self.cb_lunch.isChecked()
        c.lunch_start = _hhmm(self.ed_lunch_start)
        c.lunch_end = _hhmm(self.ed_lunch_end)
        c.workdays = [i for i, cb in enumerate(self.cb_weekdays) if cb.isChecked()] or [0, 1, 2, 3, 4]
        c.holidays = self._dates(self.ed_holidays)
        c.makeup_workdays = self._dates(self.ed_makeup)
        c.makeup_pairs = [self.list_makeup.item(i).data(Qt.UserRole)
                          for i in range(self.list_makeup.count())]

        c.theme = self.cb_theme.currentData()
        c.refresh_value = self.ed_refresh.value()
        c.refresh_unit = self.ed_refresh_unit.currentData()
        c.normalize_refresh()          # 以「数值 + 单位」为真值推导 refresh_ms
        c.calendar_auto_sync = self.cb_calendar.isChecked()
        c.fun_enabled = self.cb_fun.isChecked()
        c.fun_rotate = self.cb_rotate.isChecked()
        c.fun_target_name = self.ed_target_name.text().strip() or "一件 T 恤"
        c.fun_target_amount = self.ed_target_amount.value()
        c.always_on_top = self.cb_top.isChecked()
        c.minimize_to_tray = self.cb_tray.isChecked()
        c.auto_start = self.cb_autostart.isChecked()
        c.auto_check_update = self.cb_auto_update.isChecked()
        c.widget_visible = self.cb_widget.isChecked()
        c.widget_dock_desktop = self.cb_dock.isChecked()
        c.widget_scale = self.slider_scale.value() / 100.0
        c.widget_opacity = self.slider_opacity.value() / 100.0
        c.accent_hue = self.hue_accent.hue()
        c.accent2_hue = self.hue_accent2.hue()
        c.bg_hue = self.hue_bg.hue()
        c.widget_follow_main = self.cb_widget_follow.isChecked()
        c.widget_auto_wallpaper = self.cb_widget_auto.isChecked()
        c.widget_accent_hue = self.hue_w_accent.hue()
        c.widget_accent2_hue = self.hue_w_accent2.hue()
        c.widget_bg_hue = self.hue_w_bg.hue()
        # 关键：按当前薪资模式重新推导日薪，界面 / 保存 / 再次读取用的是同一个值
        return c.sync_salary()

    @staticmethod
    def _dates(edit: QPlainTextEdit) -> list[str]:
        out = []
        for line in edit.toPlainText().splitlines():
            value = line.strip()
            if DATE_RE.match(value):
                out.append(value)
        return sorted(set(out))

    def _update_preview(self) -> None:
        try:
            c = self._draft()
            rate = hourly_rate(c)
            full_h = full_work_seconds(c) / 3600
            # 日薪是派生值：改月薪（或计薪天数 / 折算工时 / 每日工时）后立刻回填显示
            self.ed_daily.blockSignals(True)
            self.ed_daily.setReadOnly(c.salary_mode != "daily")
            self.ed_daily.setValue(round(c.daily_salary, 2))
            self.ed_daily.blockSignals(False)
            self.day_box.setTitle(
                "日薪（由月薪自动换算）" if c.salary_mode == "monthly"
                else "日薪（由时薪自动换算）" if c.salary_mode == "hourly"
                else "日薪（可直接填写）")
            self.preview.setText(
                f"预览：日薪 ¥{c.daily_salary:,.2f}　时薪 ¥{rate:.2f}　每秒 ¥{rate / 3600:.4f}<br>"
                f"每日有效工时 {full_h:.2f} 小时　今日满勤可得 ¥{rate * full_h:,.2f}"
            )
            ok, msg, ms = validate_refresh_interval(self.ed_refresh.value(),
                                                    self.ed_refresh_unit.currentData())
            check_ms = calendar_sync_interval_ms(ms)
            period = (f"{check_ms / 60000:.0f} 分钟" if check_ms < 3_600_000
                      else f"{check_ms / 3_600_000:.1f} 小时")
            prefix = "刷新间隔超出范围，将自动修正为 " if not ok else ""
            self.lb_refresh_hint.setText(
                f"{prefix}{msg}主界面每 {ms} 毫秒刷新一次；同一个间隔也驱动调休日历同步检查"
                f"（约每 {period} 一次，下限 15 分钟 / 上限 24 小时）。保存后立即生效。"
            )
        except Exception as exc:
            self.preview.setText(f"参数有误：{exc}")

    # ------------------------------------------------------------------ #
    def _reset_today(self) -> None:
        self.app.reset_today()
        self.preview.setText("已重置今日数据，主界面数字将从头开始累计。")

    def _save(self) -> None:
        c = self._draft()
        if full_work_seconds(c) <= 0:
            self.preview.setText("保存失败：有效工时为 0，请检查上下班时间与午休区间。")
            return
        ok, msg, _ms = validate_refresh_interval(c.refresh_value, c.refresh_unit)
        if not ok:
            self.preview.setText(f"保存失败：刷新间隔{msg}")
            return
        c.settings_size = [self.width(), self.height()]
        self.app.apply_settings(c)
        self.accept()
