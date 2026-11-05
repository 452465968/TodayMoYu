# -*- coding: utf-8 -*-
"""自动更新 UI 端到端验证（真实 GUI，隔离 HOME 与单实例名）。

覆盖：发现新版本弹窗内容 / 「稍后」不下载 / 「跳过此版本」写入配置 / 退出不崩。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ["HOME"] = tempfile.mkdtemp(prefix="moyu_upd_home_")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

import main as main_mod  # noqa: E402
import updater  # noqa: E402

main_mod.SERVER_NAME += f"_upd_{os.getpid()}"

out: dict = {"ok": [], "fail": []}


def check(name: str, cond: bool, detail: str = "") -> None:
    (out["ok"] if cond else out["fail"]).append(f"{name}{(' · ' + detail) if detail else ''}")


def click_modal(text: str) -> bool:
    """在模态框里点指定文字的按钮。"""
    w = QApplication.activeModalWidget()
    if not isinstance(w, QMessageBox):
        return False
    for b in w.buttons():
        if text in b.text():
            b.click()
            return True
    return False


def main() -> int:
    app = main_mod.MoyuQApplication(sys.argv[:1])
    c = main_mod.MoyuApp(["--no-calendar", "--no-update"])
    app._controller = c

    info = updater.UpdateInfo(
        version="9.9.9", tag="v9.9.9",
        notes="## 新增\n- 测试用更新条目",
        page_url="https://example.com/release",
        asset_name="TodayMoYu-macOS-v9.9.9.zip",
        asset_url="https://example.com/mac.zip", asset_size=30 * 1024 * 1024)

    captured: dict = {}

    def grab() -> None:
        w = QApplication.activeModalWidget()
        if isinstance(w, QMessageBox):
            captured["text"] = w.text()
            captured["info"] = w.informativeText()
            click_modal("稍后")

    def run_offer() -> None:
        QTimer.singleShot(400, grab)
        c._offer_update(info)

    QTimer.singleShot(200, run_offer)

    # 随后验证「跳过此版本」
    def run_skip() -> None:
        QTimer.singleShot(400, lambda: click_modal("跳过此版本"))
        c._offer_update(info)

    QTimer.singleShot(1500, run_skip)

    def verify_and_quit() -> None:
        check("弹窗显示目标版本号", "v9.9.9" in captured.get("text", ""), captured.get("text", ""))
        check("弹窗显示当前版本", "当前 v" in captured.get("text", ""))
        check("弹窗带下载体积提示", "MB" in captured.get("info", "") or "MB" in captured.get("text", ""))
        check("「跳过此版本」写入配置", c.cfg.skipped_version == "9.9.9", c.cfg.skipped_version)
        # 退出：v1.2.0 在 closeEvent / quit 里同步 quit 会 SIGSEGV，这里验证不崩
        c.quit_app()

    QTimer.singleShot(2800, verify_and_quit)
    QTimer.singleShot(9000, app.quit)
    app.exec()

    print("\n== PASS ==")
    for line in out["ok"]:
        print("  ✓", line)
    print("== FAIL ==")
    for line in out["fail"]:
        print("  ✗", line)
    return 0 if not out["fail"] else 1


if __name__ == "__main__":
    sys.exit(main())
