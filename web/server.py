# -*- coding: utf-8 -*-
"""今天摸了吗 · 网页预览服务（macOS 调试用）

只依赖 Python 标准库 + 项目里的 core.py，不需要 PySide6 / 不需要虚拟环境：

    python3 web/server.py              # 然后打开 http://127.0.0.1:8765
    python3 web/server.py --open       # 自动打开浏览器
    python3 web/server.py --port 9000

作用：
  1. 托管 web/preview.html（也可直接双击该 HTML，纯 JS 模式即可运行）
  2. 暴露 /api/snapshot，用「真实 core.py」算一份快照，
     供网页一键对照浏览器 JS 版算法是否一致（排查折算逻辑 bug）
"""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from core import (  # noqa: E402
    APP_NAME, AppState, Settings, compute, format_hms, format_money,
    full_work_seconds, hourly_rate, work_segments,
)


def build_state(raw: dict) -> AppState:
    st = AppState()
    st.day = raw.get("day") if isinstance(raw.get("day"), str) else ""
    st.paused = bool(raw.get("paused", False))
    ps = raw.get("pause_start")
    st.pause_start = ps if isinstance(ps, str) else None
    spans = raw.get("pause_spans", [])
    st.pause_spans = [list(x) for x in spans
                      if isinstance(x, (list, tuple)) and len(x) == 2
                      and all(isinstance(v, str) for v in x)] if isinstance(spans, list) else []
    return st


def snapshot_payload(cfg: Settings, st: AppState, at: str | None) -> dict:
    now = datetime.fromisoformat(at) if at else datetime.now()
    snap = compute(cfg, st, now)
    return {
        "app": APP_NAME,
        "at": now.isoformat(timespec="seconds"),
        "money": format_money(snap.earned_today, cfg.decimals),
        "money_raw": round(snap.earned_today, 6),
        "duration": format_hms(snap.fished_seconds),
        "duration_seconds": round(snap.fished_seconds, 2),
        "progress": round(snap.progress, 4),
        "rate": round(snap.rate, 4),
        "per_second": round(snap.per_second, 6),
        "full_pay": round(snap.full_pay, 2),
        "month_total": round(snap.month_total, 2),
        "worked_seconds": round(snap.worked_seconds, 2),
        "paused_seconds": round(snap.paused_seconds, 2),
        "full_seconds": round(snap.full_seconds, 2),
        "status": snap.status_text,
        "day_kind": snap.day_kind,
        "daily_salary": round(cfg.daily_salary, 4),
        "countdown": snap.countdown_text,
        "fun": snap.fun_text,
        "day": snap.day.isoformat(),
        "segments": [[a, b] for a, b in work_segments(cfg, snap.day)],
        # 便于在网页里直接看到服务端实际采用的参数
        "echo": {
            "salary_mode": cfg.salary_mode,
            "hourly_rate_effective": round(hourly_rate(cfg), 6),
            "full_work_seconds": full_work_seconds(cfg),
            "decimals": cfg.decimals,
        },
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "TodayMoYuPreview/1.0"

    def log_message(self, fmt: str, *args) -> None:
        if "/api/" in (self.path or ""):
            sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api/ping":
            self._json({"ok": True, "app": APP_NAME, "engine": "core.py"})
            return
        if parsed.path == "/api/snapshot":
            qs = parse_qs(parsed.query)
            try:
                cfg = Settings.from_dict(json.loads(qs.get("cfg", ["{}"])[0]))
                self._json(snapshot_payload(cfg, AppState(), qs.get("at", [None])[0]))
            except Exception as exc:
                self._json({"error": str(exc)}, 400)
            return
        path = "/preview.html" if parsed.path in ("/", "") else parsed.path
        target = (HERE / path.lstrip("/")).resolve()
        if not str(target).startswith(str(HERE)) or not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        ctype = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8",
                 ".png": "image/png", ".ico": "image/x-icon"}.get(target.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path != "/api/snapshot":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            payload = json.loads(self.rfile.read(length) or b"{}")
            cfg = Settings.from_dict(payload.get("cfg") or {})
            st = build_state(payload.get("state") or {})
            self._json(snapshot_payload(cfg, st, payload.get("at")))
        except Exception as exc:
            self._json({"error": str(exc)}, 400)


def main() -> None:
    ap = argparse.ArgumentParser(description=f"{APP_NAME} 网页预览服务")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="启动后自动打开浏览器")
    args = ap.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"{APP_NAME} · 网页预览服务已启动")
    print(f"  浏览器打开：{url}")
    print(f"  对照接口：  POST {url}api/snapshot   （真实 core.py 计算）")
    print("  Ctrl+C 停止")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
