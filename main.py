# -*- coding: utf-8 -*-
"""今天摸了吗 · Windows 桌面应用入口

运行：
    python main.py
    python main.py --minimized          # 启动后只驻留托盘
    python main.py --at 2026-11-02T15:05:36   # 指定演示时间（复现参考数据）
    python main.py --quit-after 3       # N 秒后自动退出（冒烟测试用）

架构：core.py 只做纯计算；本文件负责 Qt 生命周期、定时器、托盘、
单实例、配置应用和系统集成。所有金额都以真实系统时钟为准，
定时器只负责「重画」，不负责「累加」，因此不会漂移。
"""
from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QEvent, QRect, QTimer, Qt, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMenu, QMessageBox, QSystemTrayIcon, QWidget,
)

import holiday_calendar as hc
import updater
import win32_extra as win
from core import (
    APP_NAME, APP_VERSION, AppState, Settings, app_data_dir, compute,
    effective_day, export_widget_data, format_hms, format_money,
)
from theme import palette_for, ui_font
from ui_main import MainWindow
from ui_settings import SettingsDialog
from ui_widget import DesktopWidget

SERVER_NAME = "JinTianMoLeMa_SingleInstance_v1"


class MoyuQApplication(QApplication):
    """macOS 专属行为：主窗口被隐藏后，点 Dock 图标 / Cmd+Tab 切回时自动恢复。

    Windows 上不做任何额外处理（托盘是主要入口）。
    """

    def event(self, e) -> bool:  # noqa: N802
        if (win.IS_MACOS and e.type() == QEvent.ApplicationStateChange):
            active = self.applicationState() == Qt.ApplicationActive
            controller = getattr(self, "_controller", None)
            if active and controller is not None:
                w = controller.window
                if w is not None and not w.isVisible():
                    w.show()
                    w.raise_()
                    w.activateWindow()
        return super().event(e)


def make_icon(size: int = 96) -> QIcon:
    """用代码画应用图标，免去外部资源文件，打包更省事。"""
    k = size / 96.0
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    g = QLinearGradient(0, 0, size, size)
    g.setColorAt(0, QColor("#FF9E76"))
    g.setColorAt(0.55, QColor("#F0744B"))
    g.setColorAt(1, QColor("#D9482B"))
    p.setBrush(g)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(3 * k, 3 * k, 90 * k, 90 * k, 24 * k, 24 * k)
    f = QFont()
    preferred = ui_font().split(",")[0].strip('"')
    f.setFamilies([preferred, "Microsoft YaHei UI", "PingFang SC", "Segoe UI", "sans-serif"])
    f.setPixelSize(max(8, int(52 * k)))
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(pm.rect(), Qt.AlignCenter, "摸")
    p.end()
    return QIcon(pm)


def setup_logging() -> logging.Logger:
    log = logging.getLogger(APP_NAME)
    log.setLevel(logging.INFO)
    try:
        path = app_data_dir() / "app.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(path, encoding="utf-8", mode="a")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(handler)
    except Exception:
        log.addHandler(logging.NullHandler())
    return log


class MoyuApp(QWidget):
    # 后台线程把结果投递回 Qt 主线程，避免网络请求卡住界面
    calendar_result = Signal(object)
    calendar_changed = Signal(str)
    update_checked = Signal(object)
    update_downloaded = Signal(object)

    def __init__(self, args: list[str]):
        super().__init__()
        self.log = setup_logging()
        self.cfg: Settings = Settings.load()
        self.state: AppState = AppState.load()
        self.widget: DesktopWidget | None = None
        self.window: MainWindow | None = None
        self._last_snap = None
        self._last_export = datetime.min
        self._really_quit = False
        self._time_offset = timedelta(0)
        self._calendar_disabled = ("--no-calendar" in args
                                   or bool(os.environ.get("MOYU_NO_CALENDAR")))
        self._calendar_inflight = False
        self._last_calendar_attempt: datetime | None = None
        self.calendar_offline = False

        # 启动即用「最近一次成功数据 / 出厂基线」，网络还没回来也不会缺日历
        cached = hc.load_cache()
        hc.apply_to_settings(self.cfg, cached)
        self.calendar_status_text = hc.status_text(
            cached, refresh_ms=self.cfg.refresh_ms)
        self.calendar_result.connect(self._on_calendar_result)
        self.update_checked.connect(self._on_update_checked)
        self.update_downloaded.connect(self._on_update_downloaded)
        self._update_inflight = False

        if "--at" in args:
            try:
                idx = args.index("--at")
                fixed = datetime.fromisoformat(args[idx + 1])
                self._time_offset = fixed - datetime.now()
            except (IndexError, ValueError) as exc:
                self.log.warning("忽略无效的 --at 参数: %s", exc)

        self.icon = make_icon()
        QApplication.setWindowIcon(self.icon)

        # 单实例：第二个实例只负责唤起已有窗口，然后退出
        self.server: QLocalServer | None = None
        self._init_single_instance()

        self.window = MainWindow(self)
        self.window.set_always_on_top(self.cfg.always_on_top)
        self._init_tray()
        if win.IS_MACOS:
            self._init_macos_menubar()

        self.timer = QTimer(self)
        self.timer.setInterval(self.cfg.refresh_ms)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self._tick()

        if self.cfg.widget_visible:
            self.toggle_widget(True)

        # 启动后异步同步一次；后续同步由同一个刷新定时器按周期检查
        if self.cfg.calendar_auto_sync and not self._calendar_disabled:
            QTimer.singleShot(1200, lambda: self.sync_calendar_now(force=True))

        # 自动更新：启动 4 秒后检查一次（每天最多一次，失败静默，不打扰）
        if "--no-update" not in args and not os.environ.get("MOYU_NO_UPDATE"):
            QTimer.singleShot(4000, self._maybe_check_updates)

        if "--minimized" in args:
            self.window.hide()
        else:
            self.window.show()

        if "--quit-after" in args:
            try:
                secs = float(args[args.index("--quit-after") + 1])
                QTimer.singleShot(int(secs * 1000), self.quit_app)
            except (IndexError, ValueError):
                pass

    def _init_macos_menubar(self) -> None:
        """macOS 的菜单栏是系统级入口：没有它连 ⌘Q / ⌘, 都不好用。

        Windows / Linux 上不创建，保持原有的无菜单栏外观。
        """
        try:
            from PySide6.QtGui import QAction, QKeySequence
            from PySide6.QtWidgets import QMenuBar
            # macOS 上无父级的 QMenuBar 即为系统全局菜单栏（QApplication 没有 menuBar()）
            bar = QMenuBar()
            self._mac_menubar = bar          # 保持引用，避免被 GC 后菜单栏消失
            app_menu = bar.addMenu(APP_NAME)
            act_show = QAction("打开主窗口", self)
            act_show.setShortcut(QKeySequence("Ctrl+1"))
            act_show.triggered.connect(self.show_main_window)
            app_menu.addAction(act_show)

            act_settings = QAction("设置…", self)
            act_settings.setShortcut(QKeySequence("Ctrl+,"))
            act_settings.setMenuRole(QAction.PreferencesRole)
            act_settings.triggered.connect(lambda: self.open_settings())
            app_menu.addAction(act_settings)

            act_pause = QAction("暂停 / 继续摸鱼", self)
            act_pause.setShortcut(QKeySequence("Ctrl+P"))
            act_pause.triggered.connect(self.toggle_pause)
            app_menu.addAction(act_pause)

            act_widget = QAction("显示桌面小组件", self)
            act_widget.setCheckable(True)
            act_widget.setChecked(self.cfg.widget_visible)
            act_widget.triggered.connect(self.toggle_widget)
            app_menu.addAction(act_widget)
            self.act_widget_mac = act_widget

            act_update = QAction("检查更新…", self)
            act_update.triggered.connect(lambda: self.check_updates(manual=True))
            app_menu.addAction(act_update)

            act_quit = QAction(f"退出 {APP_NAME}", self)
            act_quit.setShortcut(QKeySequence.Quit)
            act_quit.setMenuRole(QAction.QuitRole)
            act_quit.triggered.connect(self.quit_app)
            app_menu.addAction(act_quit)

            # 菜单栏条目同时挂到主窗口上，菜单动作的快捷键才能在窗口内生效
            if self.window is not None:
                self.window.addActions(app_menu.actions())
        except Exception as exc:
            self.log.warning("macOS 菜单栏创建失败: %s", exc)

    # ------------------------------------------------------------------ #
    # 生命周期 / 单实例
    # ------------------------------------------------------------------ #
    def _init_single_instance(self) -> None:
        sock = QLocalSocket()
        sock.connectToServer(SERVER_NAME)
        if sock.waitForConnected(250):
            sock.write(b"show")
            sock.flush()
            sock.waitForBytesWritten(300)
            sock.disconnectFromServer()
            self.log.info("检测到已有实例，唤起后退出")
            sys.exit(0)
        QLocalServer.removeServer(SERVER_NAME)
        self.server = QLocalServer(self)
        if self.server.listen(SERVER_NAME):
            self.server.newConnection.connect(self._on_new_instance)
        else:
            self.log.warning("单实例服务启动失败：%s", self.server.errorString())

    def _on_new_instance(self) -> None:
        if not self.server:
            return
        conn = self.server.nextPendingConnection()
        if conn:
            conn.readyRead.connect(lambda: (conn.readAll(), self.show_main_window()))

    def now(self) -> datetime:
        return datetime.now() + self._time_offset

    def available_geometry(self) -> QRect:
        screen = QApplication.primaryScreen()
        return screen.availableGeometry() if screen else QRect(0, 0, 1920, 1080)

    # ------------------------------------------------------------------ #
    # 托盘
    # ------------------------------------------------------------------ #
    def _init_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = None
            self.log.warning("系统托盘不可用")
            return
        self.tray = QSystemTrayIcon(self.icon, self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        menu.setStyleSheet(self._menu_qss())
        menu.addAction("打开「今天摸了吗」", self.show_main_window)
        self.act_widget = menu.addAction("显示桌面小组件")
        self.act_widget.setCheckable(True)
        self.act_widget.setChecked(self.cfg.widget_visible)
        self.act_widget.triggered.connect(self.toggle_widget)
        self.act_pause = menu.addAction("暂停摸鱼")
        self.act_pause.triggered.connect(self.toggle_pause)
        menu.addSeparator()
        menu.addAction("设置", self.open_settings)
        menu.addAction("同步节假日日历", lambda: self.sync_calendar_now(force=True))
        menu.addAction("检查更新…", lambda: self.check_updates(manual=True))
        menu.addAction("重置今日", self.reset_today)
        menu.addSeparator()
        menu.addAction("退出", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

    def _menu_qss(self) -> str:
        pal = palette_for(self.cfg)
        return f"""
            QMenu {{ background: #FFFFFF; color: {pal['text']};
                     border: 1px solid rgba(120,132,170,0.25); border-radius: 10px;
                     padding: 6px; font-size: 12px; }}
            QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
            QMenu::item:selected {{ background: {pal['accent2_soft']};
                                    color: {pal['accent2']}; }}
            QMenu::separator {{ height: 1px; background: rgba(120,132,170,0.18); margin: 4px 8px; }}
        """

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.show_main_window()

    def show_main_window(self) -> None:
        if not self.window:
            return
        self.window.showNormal()
        self.window.raise_()
        self.window.activateWindow()
        if win.IS_WINDOWS:
            try:
                ctypes.windll.user32.SetForegroundWindow(int(self.window.winId()))
            except Exception:
                pass

    def minimize_main(self) -> None:
        if not self.window:
            return
        if win.IS_WINDOWS:
            self.window.showMinimized()
        else:
            # macOS：最小化到 Dock 不符合「收起来」的直觉；直接隐藏，
            # 由 Dock / 菜单栏图标点击恢复（见 MoyuQApplication.event）。
            self.window.hide()

    def close_main(self) -> None:
        if self.cfg.minimize_to_tray:
            if self.window:
                self.window.hide()
            where = "系统托盘" if win.IS_WINDOWS else "菜单栏 / 程序坞（Dock）"
            self.notify(APP_NAME, f"已收进{where}，点图标可以再打开。")
        else:
            self.quit_app()

    def on_main_close(self, event) -> None:
        if self._really_quit or not self.cfg.minimize_to_tray:
            event.accept()
            self.quit_app()
        else:
            event.ignore()
            self.close_main()

    def quit_app(self) -> None:
        """退出：先落盘 + 拆界面，再**异步**结束事件循环。

        macOS 上在 closeEvent / 槽函数里同步调用 QApplication.quit() 会走
        NSApplication terminate: -> exit()，此时 PySide6 的 BindingManager
        在 C++ 静态析构里销毁 QWidget 包装对象，会踩到已失效的信号追踪器，
        直接 SIGSEGV（v1.2.0 实测：关闭窗口 / 菜单退出必崩）。
        因此这里只做清理，真正的 quit 交给下一轮事件循环。
        """
        if getattr(self, "_really_quit", False):
            return
        self._really_quit = True
        try:
            self.cfg.save()
            self.state.save()
            if self.timer.isActive():
                self.timer.stop()
            if self.widget:
                self.widget.hide()
            if getattr(self, "tray", None):
                self.tray.hide()
            if self.window:
                self.window.hide()
        except Exception as exc:
            self.log.warning("退出清理失败: %s", exc)
        QTimer.singleShot(0, QApplication.quit)

    # ------------------------------------------------------------------ #
    # 实时刷新
    # ------------------------------------------------------------------ #
    def _tick(self) -> None:
        try:
            now = self.now()
            day = effective_day(self.cfg, now)
            if self.state.day != day.isoformat():
                self.state.rollover(day)
                self.state.save()
                self.log.info("进入新的一天：%s", day)

            snap = compute(self.cfg, self.state, now)
            self._last_snap = snap
            # 主窗口始终更新：托盘模式下打开窗口的第一帧就是最新数据
            if self.window:
                self.window.update_snapshot(snap, self.cfg, self.state)
            if self.widget and self.widget.isVisible():
                self.widget.update_snapshot(snap)

            # 给 Rainmeter / 第三方组件的数据，1 秒节流
            if (now - self._last_export).total_seconds() >= 1:
                export_widget_data(self.cfg, snap)
                self._last_export = now

            if getattr(self, "tray", None):
                self.tray.setToolTip(
                    f"{APP_NAME}\n"
                    f"今日混底薪 ¥{format_money(snap.earned_today, self.cfg.decimals)}\n"
                    f"已摸鱼时长 {format_hms(snap.fished_seconds)}\n"
                    f"{snap.status_text}"
                )
            if hasattr(self, "act_pause"):
                self.act_pause.setText("继续摸鱼" if self.state.paused else "暂停摸鱼")

            # 同一个刷新间隔同时驱动主界面重画与调休日历同步检查
            self._maybe_sync_calendar()
        except Exception as exc:
            # 单次刷新出错不能让整个应用崩掉
            self.log.error("刷新失败: %s\n%s", exc, traceback.format_exc())

    # ------------------------------------------------------------------ #
    # 法定节假日 / 调休日历自动同步
    # ------------------------------------------------------------------ #
    def _maybe_sync_calendar(self) -> None:
        if self._calendar_disabled or not self.cfg.calendar_auto_sync:
            return
        if self._calendar_inflight:
            return
        every_ms = hc.calendar_sync_interval_ms(self.cfg.refresh_ms)
        last = self._last_calendar_attempt
        if last and (datetime.now() - last).total_seconds() * 1000 < every_ms:
            return
        self.sync_calendar_now(force=False)

    def sync_calendar_now(self, force: bool = True) -> None:
        """手动 / 定时触发同步；网络请求放在守护线程，绝不阻塞 UI。"""
        if self._calendar_inflight:
            if force:
                self.notify(APP_NAME, "日历正在同步中，请稍候。")
            return
        self._calendar_inflight = True
        self._calendar_seq = getattr(self, "_calendar_seq", 0) + 1
        seq = self._calendar_seq
        # 墙上时钟计时（而非 --at 模拟时钟），避免加速时钟导致反复联网
        self._last_calendar_attempt = datetime.now()
        self.calendar_status_text = "正在获取法定节假日与调休安排…"
        self.calendar_changed.emit(self.calendar_status_text)

        # watchdog：网络栈异常挂死（如代理假连）时最多等 45s 就解锁，
        # 否则 _calendar_inflight 永远为 True，后续同步全部被吞（v1.2.0 实测隐患）。
        def _unlock() -> None:
            if self._calendar_inflight and self._calendar_seq == seq:
                self._calendar_inflight = False
                self.calendar_offline = True
                self.calendar_status_text = "同步超时 · 沿用最近一次成功数据"
                self.calendar_changed.emit(self.calendar_status_text)
                self.log.warning("日历同步超时（>45s），已解锁并沿用缓存")

        QTimer.singleShot(45_000, _unlock)

        years = hc.target_years()

        def worker() -> None:
            try:
                fresh, failed = hc.fetch_years(years, timeout=6.0)
                self.calendar_result.emit({"ok": fresh.published,
                                           "data": fresh, "failed": failed,
                                           "seq": seq})
            except Exception as exc:
                self.calendar_result.emit({"ok": False, "data": hc.CalendarData(),
                                           "failed": list(years), "error": str(exc),
                                           "seq": seq})

        threading.Thread(target=worker, daemon=True, name="moyu-calendar").start()

    def _on_calendar_result(self, res: dict) -> None:
        # 过期响应（watchdog 已解锁后迟到的结果）直接丢弃，避免状态错乱
        if res.get("seq") is not None and res["seq"] != getattr(self, "_calendar_seq", 0):
            return
        self._calendar_inflight = False
        cached = hc.load_cache()
        fresh: hc.CalendarData = res.get("data") or hc.CalendarData()
        failed: list[int] = res.get("failed") or []
        if res.get("ok"):
            merged = hc.merge_calendar(cached, fresh)
            hc.save_cache(merged)                     # 更新「最近一次成功数据」
            hc.apply_to_settings(self.cfg, merged)    # 同步写回 config.json
            self.calendar_offline = bool(failed)
            self.calendar_status_text = hc.status_text(
                merged, offline=bool(failed), failed_years=failed,
                refresh_ms=self.cfg.refresh_ms)
            self.save_config()
            self.log.info("日历同步成功：放假 %d 天 / 调休上班 %d 天；未更新年份 %s",
                          len(merged.holidays), len(merged.makeup_workdays), failed)
        else:
            # 网络异常：沿用最近一次成功数据（缓存 + 配置双重兜底）
            if cached.published:
                hc.apply_to_settings(self.cfg, cached)
            self.calendar_offline = True
            self.calendar_status_text = hc.status_text(
                cached, offline=True, failed_years=failed,
                refresh_ms=self.cfg.refresh_ms)
            self.log.warning("日历同步失败，沿用缓存：%s", res.get("error") or failed)
        self.calendar_changed.emit(self.calendar_status_text)
        self._tick()

    # ------------------------------------------------------------------ #
    # 自动更新（GitHub Releases）
    # ------------------------------------------------------------------ #
    def _maybe_check_updates(self) -> None:
        """启动后自动检查：每天最多一次，失败静默。"""
        if not self.cfg.auto_check_update:
            return
        if not updater.needs_check(self.cfg.last_update_check):
            return
        self.check_updates(manual=False)

    def check_updates(self, manual: bool = False) -> None:
        if getattr(self, "_update_inflight", False):
            if manual:
                self.notify(APP_NAME, "正在检查更新，请稍候…")
            return
        self._update_inflight = True
        if manual:
            self.notify(APP_NAME, "正在检查更新…")

        def worker() -> None:
            try:
                info = updater.check_latest(APP_VERSION)
                self.update_checked.emit({"ok": True, "info": info, "manual": manual})
            except Exception as exc:            # noqa: BLE001
                self.update_checked.emit({"ok": False, "error": str(exc),
                                          "manual": manual})

        threading.Thread(target=worker, daemon=True, name="moyu-update").start()

    def _on_update_checked(self, res: dict) -> None:
        self._update_inflight = False
        manual = bool(res.get("manual"))
        self.cfg.last_update_check = datetime.now().isoformat(timespec="seconds")
        self.save_config()

        if not res.get("ok"):
            self.log.warning("检查更新失败：%s", res.get("error"))
            if manual:
                QMessageBox.information(
                    self.window, "检查更新",
                    f"暂时无法连接更新服务器。\n\n{res.get('error')}\n\n"
                    f"也可以手动访问：{updater.RELEASES_PAGE}")
            return

        info = res.get("info")
        if info is None:
            if manual:
                QMessageBox.information(
                    self.window, "检查更新",
                    f"已是最新版本（v{APP_VERSION}）。")
            return
        if not manual and info.version == self.cfg.skipped_version:
            return                              # 用户选过「跳过此版本」
        self.log.info("发现新版本：%s（当前 %s）", info.version, APP_VERSION)
        self._offer_update(info)

    def _offer_update(self, info) -> None:
        box = QMessageBox(self.window)
        box.setWindowTitle("发现新版本")
        box.setIcon(QMessageBox.Information)
        notes = (info.notes or "").strip()
        if len(notes) > 600:
            notes = notes[:600] + "…"
        size = f"（{info.asset_mb:.1f} MB）" if info.asset_size else ""
        head = f"{notes}\n\n" if notes else ""
        if info.asset_url:
            tail = f"可直接下载安装包{size}，下载完成后会提示替换步骤。"
        else:
            tail = "本次发布没有适用于当前系统的安装包，可打开发布页手动下载。"
        box.setText(f"发现新版本 v{info.version}，当前 v{APP_VERSION}")
        box.setInformativeText(head + tail)
        btn_download = box.addButton("下载更新" if info.asset_url else "打开发布页",
                                     QMessageBox.AcceptRole)
        btn_skip = box.addButton("跳过此版本", QMessageBox.DestructiveRole)
        box.addButton("稍后", QMessageBox.RejectRole)
        if self.window:
            self.window.clear_transient_button_state()
        box.exec()
        if self.window:
            self.window.clear_transient_button_state()
        clicked = box.clickedButton()
        if clicked is btn_download:
            if info.asset_url:
                self._download_update(info)
            else:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl
                QDesktopServices.openUrl(QUrl(info.page_url))
        elif clicked is btn_skip:
            self.cfg.skipped_version = info.version
            self.save_config()
            self.notify(APP_NAME, f"已跳过 v{info.version}，下个版本会再提醒。")

    def _download_update(self, info) -> None:
        from PySide6.QtWidgets import QProgressDialog

        dlg = QProgressDialog(f"正在下载 v{info.version}…", "取消", 0, 100, self.window)
        dlg.setWindowTitle("下载更新")
        dlg.setWindowModality(Qt.WindowModal)
        dlg.setMinimumDuration(0)
        dlg.setAutoClose(False)
        dlg.setValue(0)
        self._update_cancelled = False
        dlg.canceled.connect(lambda: setattr(self, "_update_cancelled", True))

        dest = app_data_dir() / "updates"

        def on_progress(done: int, total: int) -> None:
            if total > 0:
                pct = int(done * 100 / total)
                QTimer.singleShot(0, lambda: dlg.setValue(min(99, pct)))

        def worker() -> None:
            try:
                path = updater.download(info.asset_url, dest,
                                        progress=on_progress,
                                        filename=info.asset_name or None)
                self.update_downloaded.emit({"ok": True, "path": str(path),
                                             "version": info.version})
            except Exception as exc:            # noqa: BLE001
                self.update_downloaded.emit({"ok": False, "error": str(exc)})

        threading.Thread(target=worker, daemon=True, name="moyu-update-dl").start()
        self._update_dlg = dlg
        dlg.exec()

    def _on_update_downloaded(self, res: dict) -> None:
        dlg = getattr(self, "_update_dlg", None)
        if dlg is not None:
            dlg.close()
            self._update_dlg = None
        if res.get("ok"):
            path = Path(res["path"])
            self.log.info("更新包已下载：%s", path)
            updater.reveal(path)
            QMessageBox.information(
                self.window, "下载完成",
                f"v{res.get('version')} 已下载到：\n{path}\n\n"
                f"{updater.install_hint()}")
        else:
            self.log.warning("更新包下载失败：%s", res.get("error"))
            QMessageBox.warning(self.window, "下载失败",
                                f"没能下载更新包：\n{res.get('error')}")

    # ------------------------------------------------------------------ #
    # 操作
    # ------------------------------------------------------------------ #
    def save_config(self) -> None:
        try:
            self.cfg.save()
        except Exception as exc:
            self.log.warning("配置保存失败: %s", exc)

    def notify(self, title: str, message: str) -> None:
        if getattr(self, "tray", None) and QSystemTrayIcon.supportsMessages():
            self.tray.showMessage(title, message, self.icon, 3500)
        else:
            self.log.info("%s %s", title, message)

    def toggle_pause(self) -> None:
        now = self.now()
        self.state.rollover(effective_day(self.cfg, now))
        self.state.set_paused(not self.state.paused, now)
        self.state.save()
        self._tick()

    def reset_today(self) -> None:
        # 有破坏性（清空今日暂停记录并重算），先确认，防误触
        if self.window is not None and self.window.isVisible():
            ret = QMessageBox.question(
                self.window, APP_NAME,
                "确定重置今日数据吗？\n今日的暂停记录会被清空，"
                "摸鱼时长与金额将从上班时间重新累计。",
                QMessageBox.Ok | QMessageBox.Cancel, QMessageBox.Cancel)
            if ret != QMessageBox.Ok:
                return
        self.state.reset_today(self.now())
        self.state.save()
        self.notify(APP_NAME, "今日数据已重置，重新从上班时间开始摸鱼。")
        self._tick()

    def toggle_widget(self, flag: bool) -> None:
        flag = bool(flag)
        self.cfg.widget_visible = flag
        self.save_config()
        if flag:
            if self.widget is None:
                self.widget = DesktopWidget(self)
            self.widget.cfg = self.cfg
            self.widget.show()
            self.widget.raise_()
        elif self.widget:
            self.widget.hide()
        for name in ("act_widget", "act_widget_mac"):
            act = getattr(self, name, None)
            if act is not None:
                act.blockSignals(True)
                act.setChecked(flag)
                act.blockSignals(False)
        self.save_config()
        self._tick()

    def toggle_always_on_top(self, flag: bool) -> None:
        self.cfg.always_on_top = bool(flag)
        if self.window:
            self.window.set_always_on_top(self.cfg.always_on_top)
        if self.widget:
            self.widget.set_on_top(self.cfg.always_on_top)
        self.save_config()

    def open_settings(self, tab: int | None = None) -> None:
        # 模态对话框会吞掉按钮的 Leave 事件：打开前清一次，关闭后再清一次，
        # 否则「⚙ 设置」按钮上会一直留着悬停高亮（像多了个悬浮框）
        if self.window:
            self.window.clear_transient_button_state()
        dlg = SettingsDialog(self, tab=tab)
        self.calendar_changed.connect(dlg.update_calendar_status)
        try:
            dlg.exec()
        finally:
            try:
                self.calendar_changed.disconnect(dlg.update_calendar_status)
            except (RuntimeError, TypeError):
                pass
            if self.window:
                self.window.clear_transient_button_state()

    def open_settings_color(self) -> None:
        """小组件右键入口：直接打开「外观与系统」页调整配色。"""
        self.open_settings(tab=2)

    def apply_settings(self, new_cfg: Settings) -> None:
        old = self.cfg
        self.cfg = new_cfg
        self.save_config()
        if self.window:
            self.window.apply_theme()
            self.window.set_always_on_top(new_cfg.always_on_top)
            self.window.apply_responsive(force=True)
        if self.widget:
            self.widget.cfg = new_cfg
            self.widget.set_on_top(new_cfg.always_on_top)
            self.widget.set_opacity(new_cfg.widget_opacity)
            self.widget.set_scale(new_cfg.widget_scale)
            self.widget.apply_appearance()
            if new_cfg.widget_dock_desktop != old.widget_dock_desktop:
                ok = self.widget.set_docked(new_cfg.widget_dock_desktop)
                self.cfg.widget_dock_desktop = bool(ok and new_cfg.widget_dock_desktop)
        if getattr(self, "tray", None) and self.tray.contextMenu():
            self.tray.contextMenu().setStyleSheet(self._menu_qss())
        self.timer.setInterval(new_cfg.refresh_ms)

        # 刷新间隔与自动同步开关修改后立即生效：
        # 定时器周期已重设，日历同步检查周期也随下一个 tick 一起变化。
        calendar_toggled_on = new_cfg.calendar_auto_sync and not old.calendar_auto_sync
        self.calendar_status_text = hc.status_text(
            hc.load_cache(), offline=self.calendar_offline,
            refresh_ms=new_cfg.refresh_ms)
        self.calendar_changed.emit(self.calendar_status_text)
        if calendar_toggled_on and not self._calendar_disabled:
            self._last_calendar_attempt = None
            self.sync_calendar_now(force=True)

        if win.SUPPORTS_AUTOSTART and new_cfg.auto_start != old.auto_start:
            ok, msg = win.set_auto_start(new_cfg.auto_start)
            if not ok:
                self.notify(APP_NAME, msg)

        if new_cfg.widget_visible != old.widget_visible or new_cfg.widget_visible:
            self.toggle_widget(new_cfg.widget_visible)
        self._tick()
        self.log.info("设置已更新：%s / %s ~ %s", new_cfg.salary_mode,
                      new_cfg.work_start, new_cfg.work_end)


def main() -> int:
    args = sys.argv[1:]
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = MoyuQApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)   # 关窗后仍驻留托盘

    if win.IS_WINDOWS:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Shu1nm.TodayMoYu.Desktop.1")
        except Exception:
            pass

    def _hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            (app_data_dir() / "crash.log").write_text(text, encoding="utf-8")
        except Exception:
            pass
        logging.getLogger(APP_NAME).error("未捕获异常:\n%s", text)
        QMessageBox.critical(None, APP_NAME, f"程序遇到异常：\n{exc_value}\n\n详情见 crash.log")
    sys.excepthook = _hook

    controller = MoyuApp(args)
    app._controller = controller          # 供 macOS Dock 点击恢复窗口
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
