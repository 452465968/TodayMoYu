# -*- coding: utf-8 -*-
"""今天摸了吗 · 中国法定节假日与调休安排日历

数据来源：国务院办公厅发布的节假日安排通知，由开源项目 holiday-cn 整理成
按年份的 JSON（文件内含 gov.cn 原文链接）。本模块只做三件事：

1. **获取**：按年拉取「当年 + 次年」，主源 jsDelivr CDN、备源 GitHub Raw /
   Fastly 镜像，逐个超时重试；某个年度尚未公布安排视为「未公布」而非失败。
2. **解析**：`isOffDay: true` → 放假（休息日），`false` → 调休上班日；
   其余日期按每周工作日设置判定，三者严格区分。
3. **缓存与回退**：每次成功都把「最近一次成功数据」原子写入
   `%APPDATA%/今天摸了吗/holiday_calendar.json`；网络异常时沿用该缓存，
   首次运行且从未成功过则退回随程序附带的出厂基线（2026 年）。

本模块只用标准库，可脱离 GUI 独立测试；`fetcher` 参数可注入假网络便于单测。
"""
from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from core import (APP_NAME, _atomic_write, app_data_dir,
                  calendar_sync_interval_ms)

CALENDAR_FILE = "holiday_calendar.json"
BASELINE_FILE = "holiday_cn_2026.json"          # resources/ 下随程序附带
SOURCE_LABEL = "国务院办公厅节假日安排（holiday-cn 整理）"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# {year} 会替换成要获取的年份；顺序即优先级
URL_TEMPLATES = (
    "https://cdn.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
    "https://fastly.jsdelivr.net/gh/NateScarlet/holiday-cn@master/{year}.json",
    "https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json",
)

Fetcher = Callable[[str, float], dict[str, Any]]


class CalendarFetchError(RuntimeError):
    """所有数据源都不可用（网络异常 / 数据格式异常）。"""


@dataclass
class CalendarData:
    """按日期索引的日历；off=True 放假，off=False 调休上班。"""

    schema: int = 1
    updated_at: str = ""
    source: str = ""
    years: list[int] = field(default_factory=list)
    days: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def published(self) -> bool:
        return bool(self.days)

    @property
    def holidays(self) -> list[str]:
        return sorted(k for k, v in self.days.items() if v.get("off"))

    @property
    def makeup_workdays(self) -> list[str]:
        return sorted(k for k, v in self.days.items() if not v.get("off"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "app": APP_NAME,
            "updated_at": self.updated_at,
            "source": self.source,
            "years": sorted(self.years),
            "days": [{"date": k, "name": v.get("name", ""), "off": bool(v.get("off"))}
                     for k, v in sorted(self.days.items())],
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "CalendarData":
        if not isinstance(raw, dict):
            return cls()
        days: dict[str, dict[str, Any]] = {}
        items = raw.get("days")
        if isinstance(items, list):
            for it in items:
                if not isinstance(it, dict):
                    continue
                key = it.get("date")
                if isinstance(key, str) and DATE_RE.match(key):
                    days[key] = {"name": str(it.get("name") or "")[:24],
                                 "off": bool(it.get("off", it.get("isOffDay", True)))}
        years = raw.get("years")
        return cls(
            schema=int(raw.get("schema", 1) or 1),
            updated_at=str(raw.get("updated_at") or "")[:40],
            source=str(raw.get("source") or SOURCE_LABEL)[:160],
            years=sorted({int(y) for y in years if isinstance(y, int) and 1990 <= y <= 2100})
            if isinstance(years, list) else sorted({int(k[:4]) for k in days}),
            days=days,
        )


def parse_holiday_cn(payload: Any, source: str = "") -> CalendarData:
    """解析 holiday-cn 的年度 JSON：`days[].isOffDay` 决定放假 / 补班。"""
    if not isinstance(payload, dict):
        raise ValueError("日历数据不是 JSON 对象")
    year = payload.get("year")
    raw_days = payload.get("days")
    if not isinstance(year, int) or not isinstance(raw_days, list):
        raise ValueError("日历数据缺少 year / days 字段")
    if not (1990 <= year <= 2100):
        raise ValueError("日历年份超出范围")

    days: dict[str, dict[str, Any]] = {}
    for it in raw_days:
        if not isinstance(it, dict):
            continue
        key, off = it.get("date"), it.get("isOffDay")
        if (isinstance(key, str) and DATE_RE.match(key)
                and isinstance(off, bool) and key.startswith(f"{year}-")):
            days[key] = {"name": str(it.get("name") or "")[:24], "off": off}
    if raw_days and len(days) < len(raw_days) // 2:
        raise ValueError("日历有效日期过少，疑似数据损坏")
    return CalendarData(
        updated_at=datetime.now().isoformat(timespec="seconds"),
        source=source or SOURCE_LABEL,
        years=[year],
        days=days,
    )


# HTTP 头只能放 latin-1，中文应用名会让 urllib 抛 UnicodeEncodeError，
# 因此 User-Agent 固定用 ASCII 标识（应用名只用于本地展示，不进请求头）。
USER_AGENT = "TodayMoYu/1.1 (+holiday-cn)"


def _default_fetch(url: str, timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT,
                      "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read(1_000_000)
    return json.loads(raw.decode("utf-8-sig"))


def fetch_year(year: int, timeout: float = 6.0,
               fetcher: Fetcher | None = None) -> CalendarData:
    """获取单个年份；逐个尝试数据源，全失败抛 CalendarFetchError。"""
    errors: list[str] = []
    for template in URL_TEMPLATES:
        url = template.format(year=year)
        host = url.split("/")[2]
        try:
            payload = (fetcher or _default_fetch)(url, timeout)
            return parse_holiday_cn(payload, source=host)
        except Exception as exc:                       # 单个源失败继续换下一个
            errors.append(f"{host}: {type(exc).__name__}")
    raise CalendarFetchError(f"{year} 年日历获取失败（{'；'.join(errors)}）")


def fetch_years(years: list[int], timeout: float = 6.0,
                fetcher: Fetcher | None = None) -> tuple[CalendarData, list[int]]:
    """批量获取；返回（成功年度合并结果, 失败年度列表）。

    允许部分成功：某一年失败不影响已拿到的其它年份，失败年份继续使用缓存。
    """
    merged = CalendarData()
    failed: list[int] = []
    for year in sorted(set(years)):
        try:
            data = fetch_year(year, timeout, fetcher)
            if not data.published:
                continue                              # 官方尚未公布，不算网络异常
            merged.days.update(data.days)
            merged.years = sorted(set(merged.years + [year]))
            merged.updated_at = data.updated_at
            merged.source = data.source
        except CalendarFetchError:
            failed.append(year)
    return merged, failed


def merge_calendar(old: CalendarData, fresh: CalendarData) -> CalendarData:
    """成功年份整体替换（官方可能修订），失败年份保留旧数据。"""
    days = dict(old.days)
    for year in fresh.years:
        prefix = f"{year}-"
        days = {k: v for k, v in days.items() if not k.startswith(prefix)}
    days.update(fresh.days)
    return CalendarData(
        updated_at=fresh.updated_at or old.updated_at,
        source=fresh.source or old.source,
        years=sorted(set(old.years + fresh.years)),
        days=days,
    )


def cache_path(directory: Path | None = None) -> Path:
    return (directory or app_data_dir()) / CALENDAR_FILE


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def load_cache(directory: Path | None = None) -> CalendarData:
    """读取「最近一次成功数据」；没有缓存时用出厂基线兜底。"""
    data = CalendarData.from_dict(_read_json(cache_path(directory)))
    if data.published:
        return data
    baseline = Path(__file__).resolve().parent / "resources" / BASELINE_FILE
    if baseline.is_file():
        return CalendarData.from_dict(_read_json(baseline))
    return CalendarData()


def save_cache(data: CalendarData, directory: Path | None = None) -> None:
    """原子写入；空数据绝不覆盖已有的成功缓存。"""
    if not data.published:
        return
    _atomic_write(cache_path(directory),
                  json.dumps(data.to_dict(), ensure_ascii=False, indent=2))


def apply_to_settings(cfg: Any, data: CalendarData) -> None:
    """把日历结果写进 Settings（同时落盘到 config.json 作为第二重兜底）。"""
    cfg.calendar_holidays = data.holidays
    cfg.calendar_makeup_workdays = data.makeup_workdays
    cfg.calendar_updated_at = data.updated_at
    cfg.calendar_source = data.source
    cfg.calendar_years = sorted(data.years)


def status_text(data: CalendarData, *, offline: bool = False,
                failed_years: list[int] | None = None,
                refresh_ms: int = 100) -> str:
    """给设置页 / 主窗口看的日历状态文案。"""
    if not data.published:
        return "暂无日历数据：联网后会自动获取，当前按每周工作日判定。"
    when = (data.updated_at or "未知时间").replace("T", " ")[:16]
    tip = (f"已同步 {when} · 覆盖 {', '.join(str(y) for y in data.years) or '—'} 年 · "
           f"放假 {len(data.holidays)} 天 / 调休上班 {len(data.makeup_workdays)} 天 · "
           f"来源 {data.source or SOURCE_LABEL}")
    if offline:
        miss = f"（{'、'.join(str(y) for y in (failed_years or []))} 年未更新）" if failed_years else ""
        tip = f"网络异常{miss}，正在沿用上述最近一次成功数据 · " + tip
    minutes = calendar_sync_interval_ms(refresh_ms) / 60000
    period = f"{minutes:.0f} 分钟" if minutes < 60 else f"{minutes / 60:.1f} 小时"
    return tip + f" · 同步检查周期约 {period}"


def target_years(today: datetime | None = None) -> list[int]:
    """默认抓「当年 + 次年」，跨年时仍能提前拿到下一年的安排。"""
    today = today or datetime.now()
    return [today.year, today.year + 1]
