# -*- coding: utf-8 -*-
"""真实 GUI 环境诊断：确认 QTimer 驱动 / 数据刷新 / 状态判定是否正常。

用法：.venv/bin/python scripts/diagnose_live.py [--seconds 12]
不设 QT_QPA_PLATFORM，窗口会真实出现在屏幕上（这是有意的：复现用户所见）。
"""
from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from core import compute  # noqa: E402

SECONDS = 12
if "--seconds" in sys.argv:
    SECONDS = float(sys.argv[sys.argv.index("--seconds") + 1])


def main() -> int:
    app_qt = QApplication(sys.argv[:1])
    from main import MoyuApp

    app = MoyuApp(["--no-calendar"])

    ticks = {"n": 0}
    orig_tick = app._tick

    def counted() -> None:
        ticks["n"] += 1
        orig_tick()

    app._tick = counted
    app.timer.timeout.disconnect()
    app.timer.timeout.connect(counted)
    app.timer.start()

    print(f"timer interval = {app.timer.interval()} ms, active={app.timer.isActive()}")
    print(f"refresh_ms={app.cfg.refresh_ms} value={app.cfg.refresh_value}{app.cfg.refresh_unit}")
    print(f"work {app.cfg.work_start}-{app.cfg.work_end}, lunch "
          f"{app.cfg.lunch_enabled} {app.cfg.lunch_start}-{app.cfg.lunch_end}")
    print(f"paused={app.state.paused}, day={app.state.day}")
    print("-" * 70)

    last = {"t": time.time(), "n": 0}
    samples: list[tuple[str, str, str, str]] = []

    def probe() -> None:
        s = compute(app.cfg, app.state)
        now = time.time()
        dt = now - last["t"]
        dn = ticks["n"] - last["n"]
        last["t"], last["n"] = now, ticks["n"]
        w = app.window
        samples.append((s.status_text, w.lb_duration.text(), w.lb_money.text(),
                        w.lb_status.text()))
        print(f"[{datetime.now():%H:%M:%S}] ticks={ticks['n']:+d}({dn}) "
              f"status={s.status_text!r} fished={s.fished_seconds:.3f}s "
              f"UI时长={w.lb_duration.text()} UI金额={w.lb_money.text()} "
              f"UI状态={w.lb_status.text()!r} 频率={dn / dt if dt else 0:.1f}Hz")

    p = QTimer()
    p.timeout.connect(probe)
    p.start(2000)
    QTimer.singleShot(int(SECONDS * 1000), app_qt.quit)
    app_qt.exec()

    print("-" * 70)
    print(f"总 tick 次数：{ticks['n']}（约 {ticks['n'] / SECONDS:.1f} 次/秒）")
    uniq = {s[1] for s in samples}
    print(f"UI 时长取值集合：{sorted(uniq)}")
    print("判定：" + ("数据在动 ✓" if len(uniq) > 1 else
                    "数据冻结 ✗（若状态为午休/暂停/下班则属设计行为）"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
