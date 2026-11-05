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
import sys
import traceback
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QRect, QTimer, Qt
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMenu, QMessageBox, QSystemTrayIcon, QWidget,
)

import win32_extra as win
from core import (
    APP_NAME, APP_VERSION, AppState, Settings, app_data_dir, compute,
    effective_day, export_widget_data, format_hms, format_money,
)
from theme import theme, ui_font
from ui_main import MainWindow
from ui_settings import SettingsDialog
from ui_widget import DesktopWidget

SERVER_NAME = "JinTianMoLeMa_SingleInstance_v1"


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

        self.timer = QTimer(self)
        self.timer.setInterval(self.cfg.refresh_ms)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

        self._tick()

        if self.cfg.widget_visible:
            self.toggle_widget(True)

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
        menu.setStyleSheet(f"""
            QMenu {{ background: #FFFFFF; color: {theme(self.cfg.theme)['text']};
                     border: 1px solid rgba(120,132,170,0.25); border-radius: 10px;
                     padding: 6px; font-size: 12px; }}
            QMenu::item {{ padding: 7px 18px; border-radius: 6px; }}
            QMenu::item:selected {{ background: {theme(self.cfg.theme)['accent2_soft']};
                                    color: {theme(self.cfg.theme)['accent2']}; }}
            QMenu::separator {{ height: 1px; background: rgba(120,132,170,0.18); margin: 4px 8px; }}
        """)
        menu.addAction("打开「今天摸了吗」", self.show_main_window)
        self.act_widget = menu.addAction("显示桌面小组件")
        self.act_widget.setCheckable(True)
        self.act_widget.setChecked(self.cfg.widget_visible)
        self.act_widget.triggered.connect(self.toggle_widget)
        self.act_pause = menu.addAction("暂停摸鱼")
        self.act_pause.triggered.connect(self.toggle_pause)
        menu.addSeparator()
        menu.addAction("设置", self.open_settings)
        menu.addAction("重置今日", self.reset_today)
        menu.addSeparator()
        menu.addAction("退出", self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()

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
        if self.window:
            self.window.showMinimized()

    def close_main(self) -> None:
        if self.cfg.minimize_to_tray:
            if self.window:
                self.window.hide()
            self.notify(APP_NAME, "已收进系统托盘，点托盘图标可以再打开。")
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
        self._really_quit = True
        try:
            self.cfg.save()
            self.state.save()
            if self.widget:
                self.widget.hide()
            if getattr(self, "tray", None):
                self.tray.hide()
        except Exception as exc:
            self.log.warning("退出清理失败: %s", exc)
        QApplication.quit()

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
        except Exception as exc:
            # 单次刷新出错不能让整个应用崩掉
            self.log.error("刷新失败: %s\n%s", exc, traceback.format_exc())

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
        self.state.reset_today(self.now())
        self.state.save()
        self.notify(APP_NAME, "今日数据已重置，重新从上班时间开始摸鱼。")
        self._tick()

    def toggle_widget(self, flag: bool) -> None:
        flag = bool(flag)
        self.cfg.widget_visible = flag
        if flag:
            if self.widget is None:
                self.widget = DesktopWidget(self)
            self.widget.cfg = self.cfg
            self.widget.show()
            self.widget.raise_()
        elif self.widget:
            self.widget.hide()
        if hasattr(self, "act_widget"):
            self.act_widget.blockSignals(True)
            self.act_widget.setChecked(flag)
            self.act_widget.blockSignals(False)
        self.save_config()
        self._tick()

    def toggle_always_on_top(self, flag: bool) -> None:
        self.cfg.always_on_top = bool(flag)
        if self.window:
            self.window.set_always_on_top(self.cfg.always_on_top)
        if self.widget:
            self.widget.set_on_top(self.cfg.always_on_top)
        self.save_config()

    def open_settings(self) -> None:
        dlg = SettingsDialog(self)
        dlg.exec()

    def apply_settings(self, new_cfg: Settings) -> None:
        old = self.cfg
        self.cfg = new_cfg
        self.save_config()
        if self.window:
            self.window.apply_theme(new_cfg.theme)
            self.window.set_always_on_top(new_cfg.always_on_top)
        if self.widget:
            self.widget.cfg = new_cfg
            self.widget.bg.set_theme(new_cfg.theme)
            self.widget.set_on_top(new_cfg.always_on_top)
            self.widget.set_opacity(new_cfg.widget_opacity)
            self.widget.set_scale(new_cfg.widget_scale)
            self.widget.apply_appearance()
            if new_cfg.widget_dock_desktop != old.widget_dock_desktop:
                ok = self.widget.set_docked(new_cfg.widget_dock_desktop)
                self.cfg.widget_dock_desktop = bool(ok and new_cfg.widget_dock_desktop)
        self.timer.setInterval(new_cfg.refresh_ms)

        if win.IS_WINDOWS and new_cfg.auto_start != old.auto_start:
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
    app = QApplication(sys.argv)
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
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
