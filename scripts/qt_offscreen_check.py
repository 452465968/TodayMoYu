# -*- coding: utf-8 -*-
"""Qt 离屏 GUI 验证：自定义配色 / 小组件无级调节 / macOS 平台分支 / 设置对话框。

必须在项目目录下运行，且需先设 QT_QPA_PLATFORM=offscreen。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# 隔离配置目录，避免污染真实用户配置
_HOME = Path(tempfile.mkdtemp(prefix="moyu_home_"))
os.environ["HOME"] = str(_HOME)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import win32_extra as win  # noqa: E402
from core import WIDGET_OPACITY_MIN, WIDGET_SCALE_MAX, WIDGET_SCALE_MIN  # noqa: E402
from theme import palette_for  # noqa: E402

out: dict = {"ok": [], "fail": []}


def check(name: str, cond: bool, detail: str = "") -> None:
    (out["ok"] if cond else out["fail"]).append(f"{name}{(' · ' + detail) if detail else ''}")


def main() -> int:
    qapp = QApplication(sys.argv[:1])
    from main import MoyuApp

    app = MoyuApp(["--no-calendar", "--minimized"])
    qapp.processEvents()

    # ---------- 1. 主窗口配色即时生效 ---------- #
    w = app.window
    base = palette_for(app.cfg)
    base_money = base["accent"]
    app.cfg.accent_hue, app.cfg.accent2_hue, app.cfg.bg_hue = 210, 120, 280
    w.apply_theme()
    qapp.processEvents()
    pal = w.bg.t
    check("主窗口：主色变为目标色相",
          abs(QColor(pal["accent"]).hue() - 210) <= 2, pal["accent"])
    check("主窗口：副色变为目标色相",
          abs(QColor(pal["accent2"]).hue() - 120) <= 2, pal["accent2"])
    check("主窗口：样式表已重算（金额色跟着变）",
          pal["accent"] != base_money and pal["accent"] in w.styleSheet())
    check("主窗口：文字色不变（对比度不受影响）",
          pal["text"] == palette_for(app.cfg.__class__())["text"], pal["text"])
    check("主窗口：背景仍为高明度（不出现深色块）",
          all(QColor(s).lightness() >= 235 for s in pal["stops"].split("|")),
          pal["stops"])

    # ---------- 2. 小组件无级缩放 / 透明度 / 配色 ---------- #
    app.toggle_widget(True)
    qapp.processEvents()
    dw = app.widget
    check("小组件已创建", dw is not None)

    dw.set_scale(1.473)
    qapp.processEvents()
    check("小组件：无级缩放生效（1.473 不被归整到档位）",
          abs(dw._scale - 1.473) < 1e-6 and dw.width() == round(284 * 1.473),
          f"scale={dw._scale} size={dw.width()}x{dw.height()}")

    dw.set_scale(99)
    check("小组件：缩放上限被钳制", dw._scale == WIDGET_SCALE_MAX, str(dw._scale))
    dw.set_scale(-5)
    check("小组件：缩放下限被钳制", dw._scale == WIDGET_SCALE_MIN, str(dw._scale))

    dw.set_opacity(0.617)
    qapp.processEvents()
    check("小组件：透明度无级生效", abs(dw.cfg.widget_opacity - 0.617) < 1e-6,
          str(dw.cfg.widget_opacity))
    check("小组件：透明度写进绘制层（文字仍清晰）",
          abs(dw.bg.alpha - 0.617) < 1e-6, str(dw.bg.alpha))
    dw.set_opacity(0.01)
    check("小组件：透明度下限被钳制",
          dw.cfg.widget_opacity == WIDGET_OPACITY_MIN, str(dw.cfg.widget_opacity))

    # 滚轮：Shift 调透明度、不按 Shift 调缩放
    dw.set_scale(1.0)
    dw.set_opacity(0.9)
    before_scale = dw._scale
    ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
                     Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
    dw.wheelEvent(ev)
    check("小组件：滚轮缩放（1% 步进）", dw._scale > before_scale,
          f"{before_scale} → {dw._scale}")
    before_op = dw.cfg.widget_opacity
    ev2 = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, -120),
                      Qt.NoButton, Qt.ShiftModifier, Qt.NoScrollPhase, False)
    dw.wheelEvent(ev2)
    check("小组件：Shift+滚轮调透明度", dw.cfg.widget_opacity < before_op,
          f"{before_op} → {dw.cfg.widget_opacity}")

    # 配色：跟随 / 独立
    app.cfg.widget_follow_main = True
    app.cfg.accent_hue = 300
    dw.apply_appearance()
    follow_accent = dw.bg.t["accent"]
    app.cfg.widget_follow_main = False
    app.cfg.widget_accent_hue = 45
    dw.apply_appearance()
    check("小组件：配色可独立于主界面",
          follow_accent != dw.bg.t["accent"]
          and abs(QColor(dw.bg.t["accent"]).hue() - 45) <= 2,
          dw.bg.t["accent"])

    # 缩放热区判定
    check("小组件：右下角热区可命中",
          dw._on_grip(QPoint(dw.width() - 4, dw.height() - 4))
          and not dw._on_grip(QPoint(10, 10)))

    # ---------- 3. 设置对话框 ---------- #
    from ui_settings import HueRow, SettingsDialog

    dlg = SettingsDialog(app, tab=2)
    qapp.processEvents()
    check("设置对话框：可构造", dlg is not None)
    check("设置对话框：可直达「外观与系统」页", dlg.tabs.currentIndex() == 2,
          str(dlg.tabs.currentIndex()))
    check("设置对话框：色相控件齐全",
          all(isinstance(getattr(dlg, n, None), HueRow) for n in
              ("hue_accent", "hue_accent2", "hue_bg",
               "hue_w_accent", "hue_w_accent2", "hue_w_bg")))
    check("设置对话框：小组件滑块为无级 1% 步进",
          dlg.slider_scale.singleStep() == 1 and dlg.slider_opacity.singleStep() == 1
          and dlg.slider_scale.maximum() == int(WIDGET_SCALE_MAX * 100))

    dlg.hue_accent.slider.setValue(200)
    dlg.hue_accent._cb.setChecked(False)
    qapp.processEvents()
    check("设置对话框：拖动色相实时预览到主窗口",
          abs(QColor(app.window.bg.t["accent"]).hue() - 200) <= 2,
          app.window.bg.t["accent"])

    dlg.reject()
    qapp.processEvents()
    check("设置对话框：取消后配色回滚",
          app.cfg.accent_hue == 300, str(app.cfg.accent_hue))

    # ---------- 4. 平台分支 ---------- #
    check("平台：macOS 判定正确", win.IS_MACOS == (sys.platform == "darwin"))
    check("平台：macOS 菜单栏已创建",
          (not win.IS_MACOS) or (getattr(app, "_mac_menubar", None) is not None
                                 and len(app._mac_menubar.actions()) > 0))
    check("平台：非 Windows 时贴桌面安全降级",
          win.IS_WINDOWS or win.dock_to_desktop(0) is False)
    check("平台：开机自启命令可生成",
          bool(win.launch_argv()) and "--minimized" in win.launch_argv(),
          " ".join(win.launch_argv()))

    # ---------- 5. 截图（便于人工检查视觉） ---------- #
    app.cfg.accent_hue, app.cfg.accent2_hue, app.cfg.bg_hue = 210, 120, 280
    app.cfg.widget_follow_main = True
    app.window.apply_theme()
    if app.widget:
        app.widget.apply_appearance()
    app.window.resize(420, 640)
    app.window.show()
    qapp.processEvents()
    app.window.grab().save("/tmp/moyu_qt_main.png")
    if app.widget:
        app.widget.grab().save("/tmp/moyu_qt_widget.png")
    dlg2 = SettingsDialog(app, tab=2)
    dlg2.resize(560, 720)
    dlg2.show()
    qapp.processEvents()
    dlg2.grab().save("/tmp/moyu_qt_settings.png")
    dlg2.reject()

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
