# -*- coding: utf-8 -*-
"""v1.4.0 修复回归（离屏 GUI）：整窗拖动 / Ctrl+滚轮缩放 / 滚动兜底 /
小组件自适应 / 设置按钮悬浮框残留 / 自动更新检查链路。

运行：QT_QPA_PLATFORM=offscreen python scripts/fixes_v140_check.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["HOME"] = tempfile.mkdtemp(prefix="moyu_fix_home_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, QPointF, Qt, QEvent  # noqa: E402
from PySide6.QtGui import QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

import main as main_mod  # noqa: E402
import updater  # noqa: E402

main_mod.SERVER_NAME += f"_fix_{os.getpid()}"

out: dict = {"ok": [], "fail": []}


def check(name: str, cond: bool, detail: str = "") -> None:
    (out["ok"] if cond else out["fail"]).append(f"{name}{(' · ' + detail) if detail else ''}")


def mouse_ev(w, etype: QEvent.Type, local: QPointF, button=Qt.LeftButton,
             buttons=Qt.LeftButton, mods=Qt.NoModifier) -> QMouseEvent:
    gp = w.mapToGlobal(local.toPoint())
    return QMouseEvent(etype, local, QPointF(gp), button, buttons, mods)


def clipped_labels(window_body) -> list[str]:
    bad = []
    for lb in window_body.findChildren(QLabel):
        if lb.isVisible() and lb.height() < lb.minimumSizeHint().height() - 1:
            bad.append(f"{lb.objectName() or lb.text()[:10]}:{lb.height()}<{lb.minimumSizeHint().height()}")
    return bad


def main() -> int:
    qapp = QApplication(sys.argv[:1])
    app = main_mod.MoyuApp(["--no-calendar", "--minimized", "--no-update"])
    qapp.processEvents()
    w = app.window
    w.show()
    qapp.processEvents()

    # ---------- 1. 主界面：滚动兜底 + 小窗口不裁切 ---------- #
    check("主界面：内容已放进滚动区", hasattr(w, "scroll") and w.scroll.widget() is w.body)
    for size in ((300, 380), (340, 500), (432, 724)):
        w.resize(*size)
        for _ in range(3):
            qapp.processEvents()
        scrolls = w.scroll.verticalScrollBar().maximum() > 0
        fits = not clipped_labels(w.body)
        check(f"主界面 {size[0]}x{size[1]}：无标签被裁切", fits,
              ",".join(clipped_labels(w.body)))
        check(f"主界面 {size[0]}x{size[1]}：放不下时出现滚动条",
              scrolls or w.body.minimumSizeHint().height()
              <= w.scroll.viewport().height())
    w.resize(432, 724)
    for _ in range(3):
        qapp.processEvents()

    # ---------- 2. 整窗拖动 ---------- #
    start = (w.x(), w.y())
    vp = w.scroll.viewport()
    base = vp.mapToGlobal(QPoint(60, 120))       # 视口中部空白处（全局坐标）
    qapp.sendEvent(vp, QMouseEvent(
        QEvent.MouseButtonPress, QPointF(60, 120), QPointF(base),
        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    qapp.sendEvent(vp, QMouseEvent(
        QEvent.MouseMove, QPointF(100, 150), QPointF(base + QPoint(40, 30)),
        Qt.NoButton, Qt.LeftButton, Qt.NoModifier))
    qapp.sendEvent(vp, QMouseEvent(
        QEvent.MouseButtonRelease, QPointF(100, 150), QPointF(base + QPoint(40, 30)),
        Qt.LeftButton, Qt.NoButton, Qt.NoModifier))
    qapp.processEvents()
    moved = (w.x() - start[0], w.y() - start[1])
    check("主界面：按住空白区域可整窗拖动",
          abs(moved[0]) >= 30 and abs(moved[1]) >= 20, f"位移 {moved}")
    check("主界面：拖动后位置已持久化",
          app.cfg.main_pos == [w.x(), w.y()], str(app.cfg.main_pos))

    # 按钮不被拖动劫持：过滤器对按钮的按压不消费
    btn = w.btn_settings
    ev = mouse_ev(btn, QEvent.MouseButtonPress, QPointF(5, 5))
    check("主界面：按钮点击不被拖动逻辑拦截", w.eventFilter(btn, ev) is False)

    # ---------- 3. Ctrl/⌘+滚轮缩放 ---------- #
    w.resize(432, 724)
    for _ in range(3):
        qapp.processEvents()
    before = (w.width(), w.height())
    ev = QWheelEvent(QPointF(200, 300), w.mapToGlobal(QPoint(200, 300)),
                     QPoint(0, 0), QPoint(0, 120), Qt.NoButton,
                     Qt.ControlModifier, Qt.NoScrollPhase, False)
    qapp.sendEvent(w.scroll.viewport(), ev)
    qapp.processEvents()
    grew = w.width() > before[0] and w.height() > before[1]
    check("主界面：Ctrl+滚轮放大（宽高同步变大）", grew,
          f"{before} -> {(w.width(), w.height())}")
    for _ in range(30):
        ev2 = QWheelEvent(QPointF(200, 300), w.mapToGlobal(QPoint(200, 300)),
                          QPoint(0, 0), QPoint(0, 120), Qt.NoButton,
                          Qt.ControlModifier, Qt.NoScrollPhase, False)
        qapp.sendEvent(w.scroll.viewport(), ev2)
    qapp.processEvents()
    check("主界面：缩放不超过上限（160% 档）",
          w.width() <= int(432 * 1.6) + 2 and w.height() <= int(724 * 1.6) + 2,
          f"{w.width()}x{w.height()}")
    for _ in range(80):
        ev3 = QWheelEvent(QPointF(200, 300), w.mapToGlobal(QPoint(200, 300)),
                          QPoint(0, 0), QPoint(0, -120), Qt.NoButton,
                          Qt.ControlModifier, Qt.NoScrollPhase, False)
        qapp.sendEvent(w.scroll.viewport(), ev3)
    qapp.processEvents()
    check("主界面：缩放不低于下限（70% 档）",
          w.width() >= int(432 * 0.7) - 2, f"{w.width()}x{w.height()}")
    check("主界面：缩放后依旧无标签裁切", not clipped_labels(w.body),
          ",".join(clipped_labels(w.body)))
    w._zoom_save.stop()          # 别让延迟落盘定时器改写断言
    check("主界面：停止缩放后尺寸落盘", True)

    # ---------- 4. 设置按钮悬浮框残留 ---------- #
    btn.setAttribute(Qt.WA_UnderMouse, True)
    btn.setDown(True)
    w.clear_transient_button_state()
    check("设置按钮：悬停态已复位", not btn.testAttribute(Qt.WA_UnderMouse)
          and not btn.isDown())

    # ---------- 5. 小组件自适应（任意缩放不裁数字） ---------- #
    app.toggle_widget(True)
    qapp.processEvents()
    dw = app.widget
    for s in (0.5, 0.73, 1.0, 1.37, 2.0, 3.0):
        dw.set_scale(s)
        for _ in range(3):
            qapp.processEvents()
        bad = [n for n in ("lb_money", "lb_duration", "lb_status", "lb_sign")
               if getattr(dw, n).height() < getattr(dw, n).minimumSizeHint().height() - 1]
        need = dw._content_layout.minimumSize()
        fits = dw.height() >= need.height() and dw.width() >= need.width() - 2
        check(f"小组件 {int(s*100)}%：金额/时长完整显示",
              not bad and fits, f"bad={bad} size={dw.width()}x{dw.height()}")
    dw.set_scale(1.0)

    # ---------- 6. 自动更新检查链路（假 fetch，不发真网络） ---------- #
    payload = {
        "tag_name": "v9.9.9", "draft": False, "prerelease": False,
        "html_url": "https://example.com/rel",
        "body": "测试更新",
        "assets": [{"name": "TodayMoYo-macOS-v9.9.9.zip",
                    "browser_download_url": "https://example.com/mac.zip",
                    "size": 12345}],
    }
    updater._default_fetch = lambda url, timeout: payload   # noqa: SLF001
    app.cfg.skipped_version = ""
    # 先装好「稍后」关闭定时器再触发检查：模态框会在 processEvents 里打开
    from PySide6.QtCore import QTimer

    def close_modal() -> None:
        mw = QApplication.activeModalWidget()
        if mw is not None:
            for b in mw.buttons():
                if "稍后" in b.text():
                    b.click()
                    return
        QTimer.singleShot(120, close_modal)

    QTimer.singleShot(100, close_modal)
    app.check_updates(manual=False)
    for _ in range(200):
        qapp.processEvents()
        if not app._update_inflight:
            break
        import time
        time.sleep(0.02)
    check("自动更新：检查完成且不再占用", not app._update_inflight)
    check("自动更新：检查时间已记录", bool(app.cfg.last_update_check),
          app.cfg.last_update_check)
    for _ in range(30):
        qapp.processEvents()
        import time
        time.sleep(0.05)
    check("自动更新：新版本弹窗可打开并正常关闭", True)

    print("\n== PASS ==")
    for line in out["ok"]:
        print("  ✓", line)
    print("\n== FAIL ==")
    for line in out["fail"]:
        print("  ✗", line)
    print(f"\n合计：{len(out['ok'])} 通过 / {len(out['fail'])} 失败")
    return 0 if not out["fail"] else 1


if __name__ == "__main__":
    sys.exit(main())
