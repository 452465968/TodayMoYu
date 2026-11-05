# -*- coding: utf-8 -*-
"""今天摸了吗 · 设置窗口"""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from PySide6.QtCore import QDate, QTime, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDateEdit, QDialog, QDoubleSpinBox, QFormLayout,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPlainTextEdit, QPushButton, QRadioButton, QScrollArea, QFrame,
    QSlider, QSpinBox, QTabWidget, QTimeEdit, QVBoxLayout, QWidget,
)

import win32_extra as win
from core import APP_NAME, DAY_NAMES, Settings, app_data_dir, full_work_seconds, hourly_rate
from theme import THEMES, settings_qss, theme

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


class SettingsDialog(QDialog):
    def __init__(self, app: "MoyuApp"):
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
        self.lb_scale_val.setText(f"{self.slider_scale.value()}%")
        self.lb_opacity_val.setText(f"{self.slider_opacity.value()}%")
        self.app.cfg.widget_scale = s
        self.app.cfg.widget_opacity = o
        self._apply_widget_appearance(s, o)

    def reject(self) -> None:  # noqa: N802
        """取消时把实时预览过的小组件外观还原。"""
        s, o = self._orig_widget
        self.app.cfg.widget_scale = s
        self.app.cfg.widget_opacity = o
        self._apply_widget_appearance(s, o)
        super().reject()

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
        self.ed_decimals.setRange(0, 6)
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

        self.ed_refresh = QSpinBox()
        self.ed_refresh.setRange(50, 5000)
        self.ed_refresh.setSingleStep(50)
        self.ed_refresh.setSuffix(" ms")
        self.ed_refresh.setValue(c.refresh_ms)
        f.addRow("刷新间隔", self.ed_refresh)
        L.addLayout(f)

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
        self.cb_autostart.setChecked(win.is_auto_start() if win.IS_WINDOWS else c.auto_start)
        self.cb_autostart.setEnabled(win.IS_WINDOWS)
        self.cb_widget = QCheckBox("启动时显示桌面小组件")
        self.cb_widget.setChecked(c.widget_visible)
        self.cb_dock = QCheckBox("小组件贴到桌面图层（Win+D 后仍可见）")
        self.cb_dock.setChecked(c.widget_dock_desktop)
        self.cb_dock.setEnabled(win.IS_WINDOWS)
        for cb in (self.cb_top, self.cb_tray, self.cb_autostart, self.cb_widget, self.cb_dock):
            v2.addWidget(cb)
        L.addWidget(g2)

        g3 = QGroupBox("桌面小组件外观（拖动即时预览）")
        v3 = QVBoxLayout(g3)
        self.slider_scale = QSlider(Qt.Horizontal)
        self.slider_scale.setRange(60, 200)
        self.slider_scale.setSingleStep(5)
        self.slider_scale.setPageStep(10)
        self.slider_scale.setValue(int(round(c.widget_scale * 100)))
        self.lb_scale_val = QLabel(f"{int(round(c.widget_scale * 100))}%")
        self.lb_scale_val.setFixedWidth(48)
        row_s = QHBoxLayout()
        row_s.addWidget(QLabel("大小"))
        row_s.addWidget(self.slider_scale, 1)
        row_s.addWidget(self.lb_scale_val)
        v3.addLayout(row_s)

        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(30, 100)
        self.slider_opacity.setSingleStep(5)
        self.slider_opacity.setPageStep(10)
        self.slider_opacity.setValue(int(round(c.widget_opacity * 100)))
        self.lb_opacity_val = QLabel(f"{int(round(c.widget_opacity * 100))}%")
        self.lb_opacity_val.setFixedWidth(48)
        row_o = QHBoxLayout()
        row_o.addWidget(QLabel("不透明度"))
        row_o.addWidget(self.slider_opacity, 1)
        row_o.addWidget(self.lb_opacity_val)
        v3.addLayout(row_o)
        tip3 = QLabel("文字始终按最高对比度渲染；这里调整的是整个小组件的通透度。"
                     "点「保存设置」后写入配置，取消则恢复原值。")
        tip3.setObjectName("Help")
        tip3.setWordWrap(True)
        v3.addWidget(tip3)
        self.slider_scale.valueChanged.connect(self._preview_widget_appearance)
        self.slider_opacity.valueChanged.connect(self._preview_widget_appearance)
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
        c.refresh_ms = self.ed_refresh.value()
        c.fun_enabled = self.cb_fun.isChecked()
        c.fun_rotate = self.cb_rotate.isChecked()
        c.fun_target_name = self.ed_target_name.text().strip() or "一件 T 恤"
        c.fun_target_amount = self.ed_target_amount.value()
        c.always_on_top = self.cb_top.isChecked()
        c.minimize_to_tray = self.cb_tray.isChecked()
        c.auto_start = self.cb_autostart.isChecked()
        c.widget_visible = self.cb_widget.isChecked()
        c.widget_dock_desktop = self.cb_dock.isChecked()
        c.widget_scale = self.slider_scale.value() / 100.0
        c.widget_opacity = self.slider_opacity.value() / 100.0
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
        c.settings_size = [self.width(), self.height()]
        self.app.apply_settings(c)
        self.accept()
