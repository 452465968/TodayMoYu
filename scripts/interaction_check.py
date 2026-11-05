# -*- coding: utf-8 -*-
"""真实 GUI 交互回归：小组件开关 / 暂停继续 / 隐藏恢复 / 设置取消回滚。

* HOME 重定向到临时目录 + 单实例名加随机后缀：绝不触碰真实用户数据。
* 窗口会真实显示约 8 秒（复现用户交互路径），结束自动退出。
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

os.environ["HOME"] = tempfile.mkdtemp(prefix="moyu_it_home_")

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import main as main_mod  # noqa: E402
import win32_extra as win  # noqa: E402

# 单实例名隔离：避免与用户正在运行的实例互相顶掉
main_mod.SERVER_NAME += f"_it_{os.getpid()}"

out: dict = {"ok": [], "fail": []}


def check(name: str, cond: bool, detail: str = "") -> None:
    (out["ok"] if cond else out["fail"]).append(f"{name}{(' · ' + detail) if detail else ''}")


def main() -> int:
    app = main_mod.MoyuQApplication(sys.argv[:1])
    controller = main_mod.MoyuApp(["--no-calendar"])
    app._controller = controller
    steps: list[tuple] = []

    def step(name: str, fn) -> None:
        def run() -> None:
            try:
                fn()
                check(name, True)
            except Exception as exc:  # noqa: BLE001
                check(name, False, repr(exc))
            finally:
                if steps:
                    QTimer.singleShot(400, steps.pop(0))
        steps.append(run)

    # 1. 桌面小组件开关
    def t_widget_on() -> None:
        controller.toggle_widget(True)
        app.processEvents()
        assert controller.widget and controller.widget.isVisible(), "小组件未显示"
        assert controller.cfg.widget_visible is True

    def t_widget_off() -> None:
        controller.toggle_widget(False)
        app.processEvents()
        assert not controller.widget.isVisible(), "小组件未隐藏"

    # 2. 暂停 / 继续（state 在隔离 HOME 里，随便动）
    def t_pause() -> None:
        controller.toggle_pause()
        assert controller.state.paused is True
        app.processEvents()
        assert "继续摸鱼" in controller.window.btn_pause.text()

    def t_resume() -> None:
        controller.toggle_pause()
        assert controller.state.paused is False

    # 3. 隐藏窗口 → 恢复（macOS 走 hide + Dock 激活恢复逻辑）
    def t_hide() -> None:
        controller.minimize_main()
        app.processEvents()
        assert not controller.window.isVisible(), "窗口未隐藏"

    def t_restore() -> None:
        controller.show_main_window()
        app.processEvents()
        assert controller.window.isVisible(), "窗口未恢复"

    # 4. 设置对话框：改色相 → 取消 → 回滚
    def t_settings_reject() -> None:
        from ui_settings import SettingsDialog
        dlg = SettingsDialog(controller)
        dlg.show()
        app.processEvents()
        before = (controller.cfg.accent_hue, controller.cfg.widget_scale)
        dlg.hue_accent.slider.setValue(210)
        dlg.hue_accent._cb.setChecked(False)
        dlg.slider_scale.setValue(250)
        dlg.reject()
        app.processEvents()
        after = (controller.cfg.accent_hue, controller.cfg.widget_scale)
        assert before == after, f"取消后未回滚：{before} -> {after}"

    # 5. 主题切换即时生效
    def t_theme() -> None:
        old = controller.cfg.theme
        controller.cfg.theme = "mint"
        controller.window.apply_theme()
        app.processEvents()
        assert controller.window.bg.t["accent"] != "" and controller.cfg.theme == "mint"
        controller.cfg.theme = old
        controller.window.apply_theme()

    # 6. 退出流程（隔离环境，直接退）
    def t_quit() -> None:
        controller.quit_app()

    step("小组件：开启显示", t_widget_on)
    step("小组件：关闭隐藏", t_widget_off)
    step("暂停：状态切换", t_pause)
    step("继续：状态恢复", t_resume)
    step("隐藏窗口", t_hide)
    step("恢复窗口", t_restore)
    step("设置：取消回滚配色", t_settings_reject)
    step("主题切换即时生效", t_theme)
    step("退出清理", t_quit)

    QTimer.singleShot(300, steps.pop(0))
    QTimer.singleShot(12_000, app.quit)
    print(f"[debug] 进入事件循环，steps={len(steps)}", flush=True)
    rc = app.exec()
    print(f"[debug] 事件循环退出 rc={rc}", flush=True)

    print("\n== PASS ==")
    for line in out["ok"]:
        print("  ✓", line)
    print("== FAIL ==")
    for line in out["fail"]:
        print("  ✗", line)
    return 0 if not out["fail"] else 1


if __name__ == "__main__":
    sys.exit(main())
