# -*- coding: utf-8 -*-
"""
今天摸了吗 · 核心计算与数据层

纯标准库实现，不依赖任何 GUI 框架，可单独运行与单元测试：
    python -m pytest tests -q
    python core.py            # 打印一次当前快照

设计要点
--------
* 所有金额都按「真实系统时钟」实时折算，而不是靠定时器累加，
  因此系统休眠、定时器卡顿、用户改时间都不会让数字漂移。
* 工作时段支持午休（可关闭）、周末、法定节假日、调休上班日。
* 「暂停摸鱼」按时间区间记录，只扣除落在工作时段内的部分，
  所以午休期间暂停 / 跨天下班后暂停都不会误扣。
* 金额与时长逐日独立，跨零点自动开启新的一天。
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass, field, asdict
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

APP_NAME = "今天摸了吗"
APP_VERSION = "1.4.0"
CONFIG_FILE = "config.json"
STATE_FILE = "state.json"
WIDGET_TEXT_FILE = "widget.txt"
WIDGET_JSON_FILE = "widget.json"

DAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# 刷新间隔：数值 + 单位。ms 为换算后的毫秒数（保留字段，兼容旧配置与旧代码）。
# 每种单位给出允许的填写范围，最终毫秒数再统一夹到 [50, 3_600_000]。
REFRESH_UNITS: dict[str, tuple[str, float, float, float]] = {
    "ms": ("毫秒", 1.0, 50.0, 3_600_000.0),
    "s": ("秒", 1000.0, 0.05, 3600.0),
    "min": ("分钟", 60_000.0, 0.001, 60.0),
    "h": ("小时", 3_600_000.0, 0.001, 1.0),
}
REFRESH_MIN_MS = 50
REFRESH_MAX_MS = 3_600_000

# 调休日历同步调度：同一个刷新间隔同时驱动主界面刷新与日历同步检查。
# 为避免高频请求，日历同步周期 = 刷新间隔 × 600 次 tick，且限制在 15 分钟 ~ 24 小时。
CALENDAR_SYNC_TICKS = 600
CALENDAR_SYNC_MIN_MS = 15 * 60 * 1000
CALENDAR_SYNC_MAX_MS = 24 * 60 * 60 * 1000

# 桌面小组件的无级缩放范围（连续取值，不再只有档位）
WIDGET_SCALE_MIN = 0.5
WIDGET_SCALE_MAX = 3.0
WIDGET_OPACITY_MIN = 0.15

# 日期性质 → 中文标签：工作日 / 休息日 / 调休上班日必须一目了然
DAY_KIND_LABELS: dict[str, str] = {
    "work": "工作日",
    "weekend": "休息日（周末）",
    "holiday": "法定节假日 / 放假休息日",
    "makeup_work": "调休上班日",
    "makeup_rest": "调休休息日（手动配对）",
}


def day_kind_label(kind: str) -> str:
    return DAY_KIND_LABELS.get(kind, "工作日")


def validate_refresh_interval(value: Any, unit: str) -> tuple[bool, str, int]:
    """校验「数值 + 单位」并返回毫秒。

    返回 (是否合法, 错误说明, 可用的毫秒数)；即使不合法也给出夹取后的值，
    便于 UI 直接展示「已自动修正为 X」而不中断用户输入。
    """
    if unit not in REFRESH_UNITS:
        return False, "时间单位无效（可选：毫秒 / 秒 / 分钟 / 小时）", 100
    label, factor, lo, hi = REFRESH_UNITS[unit]
    try:
        v = float(value)
    except (TypeError, ValueError):
        return False, "刷新数值必须是数字", 100
    if v != v or v in (float("inf"), float("-inf")) or v <= 0:
        return False, "刷新数值必须大于 0", 100
    if v < lo or v > hi:
        return False, f"{label}的取值范围是 {lo:g} ~ {hi:g}", int(
            min(REFRESH_MAX_MS, max(REFRESH_MIN_MS, round(min(hi, max(lo, v)) * factor)))
        )
    ms = int(min(REFRESH_MAX_MS, max(REFRESH_MIN_MS, round(v * factor))))
    return True, "", ms


def effective_hues(cfg: "Settings", widget: bool = False) -> tuple[int, int, int]:
    """返回当前生效的 (主色相, 副色相, 背景色相)；-1 表示跟随所选主题。

    小组件默认与主界面一致；用户单独指定时各用各的，互不影响。
    """
    if widget and not getattr(cfg, "widget_follow_main", True):
        return (int(getattr(cfg, "widget_accent_hue", -1)),
                int(getattr(cfg, "widget_accent2_hue", -1)),
                int(getattr(cfg, "widget_bg_hue", -1)))
    return (int(getattr(cfg, "accent_hue", -1)),
            int(getattr(cfg, "accent2_hue", -1)),
            int(getattr(cfg, "bg_hue", -1)))


def calendar_sync_interval_ms(refresh_ms: int) -> int:
    """由同一个刷新间隔推导调休日历同步检查周期。"""
    try:
        base = max(1, int(refresh_ms))
    except (TypeError, ValueError):
        base = 100
    return max(CALENDAR_SYNC_MIN_MS, min(CALENDAR_SYNC_MAX_MS, base * CALENDAR_SYNC_TICKS))


def _derive_refresh_parts(ms: int) -> tuple[float, str]:
    """旧配置只有 refresh_ms 时，自动挑一个最自然的单位回填。

    优先选能整除且数值 ≥ 1 的最大单位（3600000 → 1 小时、60000 → 1 分钟、
    3000 → 3 秒）；否则用秒的小数表示（500 → 0.5 秒）；最后才退回毫秒。
    """
    ms = int(min(REFRESH_MAX_MS, max(REFRESH_MIN_MS, ms)))
    for key in ("h", "min", "s"):
        label, factor, lo, hi = REFRESH_UNITS[key]
        v = ms / factor
        if v >= 1 and lo <= v <= hi and abs(v - round(v)) < 1e-9:
            return float(round(v)), key
    if ms % 1000:
        v = ms / 1000.0
        if REFRESH_UNITS["s"][2] <= v <= REFRESH_UNITS["s"][3]:
            return round(v, 6), "s"
    return float(ms), "ms"

# 趣味目标：与原视频「一件 T 恤」保持一致，其余为可选轮换
FUN_TARGETS: list[tuple[str, float]] = [
    ("一件 T 恤", 50.0),
    ("一杯奶茶", 18.0),
    ("一张电影票", 45.0),
    ("一顿火锅", 200.0),
    ("一双球鞋", 599.0),
]


# --------------------------------------------------------------------------- #
# 路径与持久化
# --------------------------------------------------------------------------- #
def app_data_dir() -> Path:
    """返回跨平台的数据目录。Windows 上为 %APPDATA%/今天摸了吗。"""
    override = os.environ.get("MOYU_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / APP_NAME


def _atomic_write(path: Path, text: str) -> None:
    """原子写入，避免断电 / 多进程同时写导致配置文件损坏。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="moyu_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
@dataclass
class Settings:
    # 薪资：默认按日薪 129.30 / 7.5 小时 = 时薪 17.24，
    # 精确还原视频中的「¥129.30 满勤」「¥17.24 时薪」「¥0.0048/秒」
    salary_mode: str = "daily"            # daily | monthly | hourly
    daily_salary: float = 129.30
    monthly_salary: float = 3000.0
    pay_days_per_month: float = 21.75
    hourly_divisor_hours: float = 8.0
    hourly_rate: float = 17.24

    # 工时
    work_start: str = "09:00"
    work_end: str = "18:00"
    lunch_enabled: bool = True
    lunch_start: str = "12:00"
    lunch_end: str = "13:30"
    workdays: list[int] = field(default_factory=lambda: [0, 1, 2, 3, 4])
    holidays: list[str] = field(default_factory=list)        # 额外休息日 YYYY-MM-DD
    makeup_workdays: list[str] = field(default_factory=list)  # 调休上班日 YYYY-MM-DD
    # 调休安排：[["休息日", "补班日"], ...]（YYYY-MM-DD）
    # 休息日不计摸鱼时长但本月累计按满勤补算（调休不扣薪）；补班日正常实时计薪
    makeup_pairs: list[list[str]] = field(default_factory=list)

    # 显示
    decimals: int = 4
    theme: str = "aurora"                 # aurora | peach | mint
    # 自定义配色（色相角 0-359；-1 = 跟随主题默认）
    # 只改色相、不改明度饱和度，因此文字对比度始终安全
    accent_hue: int = -1                  # 主色：今日混底薪金额
    accent2_hue: int = -1                 # 副色：状态 / 时长 / 进度
    bg_hue: int = -1                      # 背景柔光（渐变底色与光斑）
    fun_enabled: bool = True
    fun_rotate: bool = False
    fun_target_name: str = "一件 T 恤"
    fun_target_amount: float = 50.0
    refresh_ms: int = 100                         # 派生值：由下面「数值 + 单位」换算
    refresh_value: float = 100.0                  # 用户填写的数值
    refresh_unit: str = "ms"                      # ms | s | min | h

    # 自动获取的法定节假日 / 调休安排（最近一次成功数据，随配置一起落盘）
    calendar_auto_sync: bool = True
    calendar_holidays: list[str] = field(default_factory=list)        # 放假（休息日）
    calendar_makeup_workdays: list[str] = field(default_factory=list)  # 调休上班日
    calendar_updated_at: str = ""
    calendar_source: str = ""
    calendar_years: list[int] = field(default_factory=list)

    # 窗口 / 小组件
    always_on_top: bool = False
    minimize_to_tray: bool = True
    auto_start: bool = False
    widget_visible: bool = False
    widget_dock_desktop: bool = False
    widget_opacity: float = 0.94
    widget_scale: float = 1.0
    # 小组件配色：默认与主界面一致，也可单独指定
    widget_follow_main: bool = True
    widget_accent_hue: int = -1
    widget_accent2_hue: int = -1
    widget_bg_hue: int = -1
    widget_pos: list[int] | None = None
    main_pos: list[int] | None = None
    main_size: list[int] | None = None           # 主窗口上次拖拽调整后的 [宽, 高]
    settings_size: list[int] | None = None   # 设置窗口上次调整后的 [宽, 高]

    # 自动更新
    auto_check_update: bool = True            # 启动后每天检查一次 GitHub Releases
    last_update_check: str = ""               # 上次检查时间（ISO，用于 24h 节流）
    skipped_version: str = ""                 # 用户选择「跳过此版本」时记录

    # ------------------------------------------------------------------ #
    def normalize_refresh(self) -> "Settings":
        """以「数值 + 单位」为真值重新推导 refresh_ms；保存与加载都会调用。"""
        ok, _msg, ms = validate_refresh_interval(self.refresh_value, self.refresh_unit)
        if ok:
            self.refresh_ms = ms
        else:
            # 非法输入：保留可用的毫秒值，并回填一组与之等价的合法数值/单位
            self.refresh_ms = int(min(REFRESH_MAX_MS, max(REFRESH_MIN_MS, ms)))
            self.refresh_value, self.refresh_unit = _derive_refresh_parts(self.refresh_ms)
        return self

    @staticmethod
    def _num(value: Any, default: float, lo: float, hi: float) -> float:
        try:
            v = float(value)
        except (TypeError, ValueError):
            return default
        if v != v or v in (float("inf"), float("-inf")):  # NaN / inf
            return default
        return min(hi, max(lo, v))

    @staticmethod
    def _hue(value: Any, default: int = -1) -> int:
        """色相角：-1 表示跟随主题，合法范围 0-359。"""
        try:
            v = int(value)
        except (TypeError, ValueError):
            return default
        if v < 0 or v > 359:
            return default
        return v

    @staticmethod
    def _hhmm(value: Any, default: str) -> str:
        if not isinstance(value, str):
            return default
        try:
            h, m = value.strip().split(":")
            h_i, m_i = int(h), int(m)
            if 0 <= h_i <= 23 and 0 <= m_i <= 59:
                return f"{h_i:02d}:{m_i:02d}"
        except (ValueError, TypeError):
            pass
        return default

    def sync_salary(self) -> "Settings":
        """把月薪 / 日薪 / 时薪同步成一致的一组值，杜绝旧日薪残留。

        沿用项目现有的 hourly_rate() 规则：
            时薪 = 月薪 ÷ 月计薪天数 ÷ 时薪折算工时   （monthly）
            时薪 = 日薪 ÷ 每日有效工时                （daily）
            时薪 = 直接指定                           （hourly）
            日薪 = 时薪 × 每日有效工时

        所以只要月薪、计薪天数、折算工时或每日工时发生变化，日薪都会被
        重新推导并写回。from_dict() 与 save() 都会调用它，因此保存后、
        重新打开、再次读取看到的都是同一个新日薪。
        """
        full_h = full_work_seconds(self) / 3600.0
        if full_h <= 0:
            return self
        denom = self.pay_days_per_month * self.hourly_divisor_hours
        if denom <= 0:
            return self

        if self.salary_mode == "monthly":
            rate = max(0.0, self.monthly_salary / denom)
        elif self.salary_mode == "daily":
            rate = max(0.0, self.daily_salary / full_h)
        else:
            rate = max(0.0, self.hourly_rate)

        self.hourly_rate = round(rate, 6)
        # 日薪是派生值：任何模式下都由当前时薪重新计算，不保留旧值
        self.daily_salary = round(rate * full_h, 4)
        return self

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Settings":
        """宽容解析：未知字段忽略、非法值回退默认，保证旧配置 / 手改配置不会崩。"""
        d = cls()
        out = asdict(d)
        for key in out:
            if key in raw:
                out[key] = raw[key]

        s = cls()
        s.salary_mode = out["salary_mode"] if out["salary_mode"] in ("daily", "monthly", "hourly") else "daily"
        s.monthly_salary = cls._num(out["monthly_salary"], 3000.0, 0.0, 1e9)
        s.pay_days_per_month = cls._num(out["pay_days_per_month"], 21.75, 1.0, 31.0)
        s.hourly_divisor_hours = cls._num(out["hourly_divisor_hours"], 8.0, 0.5, 24.0)
        s.daily_salary = cls._num(out["daily_salary"], 129.30, 0.0, 1e7)
        s.hourly_rate = cls._num(out["hourly_rate"], 17.24, 0.0, 1e6)

        s.work_start = cls._hhmm(out["work_start"], "09:00")
        s.work_end = cls._hhmm(out["work_end"], "18:00")
        s.lunch_enabled = bool(out["lunch_enabled"])
        s.lunch_start = cls._hhmm(out["lunch_start"], "12:00")
        s.lunch_end = cls._hhmm(out["lunch_end"], "13:30")

        wd = out["workdays"]
        s.workdays = sorted({int(x) for x in wd if isinstance(x, int) and 0 <= x <= 6}) if isinstance(wd, list) else [0, 1, 2, 3, 4]
        if not s.workdays:
            s.workdays = [0, 1, 2, 3, 4]
        for key in ("holidays", "makeup_workdays"):
            val = out[key]
            s.__setattr__(key, [x for x in val if isinstance(x, str) and len(x) == 10] if isinstance(val, list) else [])
        pairs = out.get("makeup_pairs", [])
        s.makeup_pairs = [
            [p[0], p[1]] for p in pairs
            if isinstance(p, (list, tuple)) and len(p) == 2
            and all(isinstance(x, str) and len(x) == 10 for x in p)
        ] if isinstance(pairs, list) else []

        s.decimals = int(cls._num(out["decimals"], 4, 0, 6))
        s.theme = out["theme"] if out["theme"] in ("aurora", "peach", "mint") else "aurora"
        s.accent_hue = cls._hue(out["accent_hue"])
        s.accent2_hue = cls._hue(out["accent2_hue"])
        s.bg_hue = cls._hue(out["bg_hue"])
        s.fun_enabled = bool(out["fun_enabled"])
        s.fun_rotate = bool(out["fun_rotate"])
        s.fun_target_name = str(out["fun_target_name"])[:24] or "一件 T 恤"
        s.fun_target_amount = cls._num(out["fun_target_amount"], 50.0, 0.01, 1e7)
        s.refresh_ms = int(cls._num(out["refresh_ms"], 100, REFRESH_MIN_MS, REFRESH_MAX_MS))

        # 刷新间隔「数值 + 单位」：旧配置只有 refresh_ms 时自动推导，
        # 新配置以 value+unit 为真值重新换算，保证保存 / 重开 / 再读取一致。
        has_parts = "refresh_value" in raw and "refresh_unit" in raw
        if has_parts:
            s.refresh_value = cls._num(out["refresh_value"], 100.0, 0.0, 1e9)
            raw_unit = out["refresh_unit"]
            s.refresh_unit = raw_unit if raw_unit in REFRESH_UNITS else "ms"
        else:
            s.refresh_value, s.refresh_unit = _derive_refresh_parts(s.refresh_ms)
        s.normalize_refresh()

        # 自动日历：把「最近一次成功数据」随配置一起读回，离线也能继续用
        s.calendar_auto_sync = bool(out["calendar_auto_sync"])
        for key in ("calendar_holidays", "calendar_makeup_workdays"):
            val = out[key]
            s.__setattr__(key, sorted({x for x in val if isinstance(x, str) and len(x) == 10})
                          if isinstance(val, list) else [])
        s.calendar_updated_at = str(out["calendar_updated_at"])[:40]
        s.calendar_source = str(out["calendar_source"])[:120]
        years = out["calendar_years"]
        s.calendar_years = sorted({int(y) for y in years if isinstance(y, int) and 1990 <= y <= 2100}) \
            if isinstance(years, list) else []

        s.always_on_top = bool(out["always_on_top"])
        s.minimize_to_tray = bool(out["minimize_to_tray"])
        s.auto_start = bool(out["auto_start"])
        s.widget_visible = bool(out["widget_visible"])
        s.widget_dock_desktop = bool(out["widget_dock_desktop"])
        s.widget_opacity = cls._num(out["widget_opacity"], 0.94, WIDGET_OPACITY_MIN, 1.0)
        # 无级缩放：不再只有档位，保留两位小数，范围 0.5x ~ 3.0x
        s.widget_scale = round(cls._num(out["widget_scale"], 1.0, WIDGET_SCALE_MIN, WIDGET_SCALE_MAX), 3)
        s.widget_follow_main = bool(out["widget_follow_main"])
        s.widget_accent_hue = cls._hue(out["widget_accent_hue"])
        s.widget_accent2_hue = cls._hue(out["widget_accent2_hue"])
        s.widget_bg_hue = cls._hue(out["widget_bg_hue"])
        for key in ("widget_pos", "main_pos", "main_size", "settings_size"):
            val = out[key]
            s.__setattr__(key, [int(val[0]), int(val[1])] if isinstance(val, list) and len(val) == 2
                          and isinstance(val[0], int) and isinstance(val[1], int) else None)
        s.auto_check_update = bool(out["auto_check_update"])
        s.last_update_check = str(out["last_update_check"])[:40]
        s.skipped_version = str(out["skipped_version"])[:20]
        # 关键：加载时也重新推导日薪，旧配置文件里的旧日薪不会残留
        return s.sync_salary()

    @classmethod
    def load(cls, directory: Path | None = None) -> "Settings":
        return cls.from_dict(_read_json((directory or app_data_dir()) / CONFIG_FILE))

    def save(self, directory: Path | None = None) -> None:
        # 写盘前再同步一次，保证任何保存路径落下的都是当前模式下的一致值
        self.sync_salary()
        self.normalize_refresh()
        _atomic_write((directory or app_data_dir()) / CONFIG_FILE,
                      json.dumps(asdict(self), ensure_ascii=False, indent=2))


# --------------------------------------------------------------------------- #
# 运行状态（暂停区间等）
# --------------------------------------------------------------------------- #
@dataclass
class AppState:
    day: str = ""                                   # 归属日期，跨天自动重置
    paused: bool = False
    pause_start: str | None = None                 # ISO 本地时间
    pause_spans: list[list[str]] = field(default_factory=list)  # [[start_iso, end_iso], ...]

    @classmethod
    def load(cls, directory: Path | None = None) -> "AppState":
        raw = _read_json((directory or app_data_dir()) / STATE_FILE)
        st = cls()
        st.day = raw.get("day") if isinstance(raw.get("day"), str) else ""
        st.paused = bool(raw.get("paused", False))
        ps = raw.get("pause_start")
        st.pause_start = ps if isinstance(ps, str) else None
        spans = raw.get("pause_spans", [])
        st.pause_spans = [list(x) for x in spans
                          if isinstance(x, (list, tuple)) and len(x) == 2
                          and all(isinstance(v, str) for v in x)] if isinstance(spans, list) else []
        if st.paused and not st.pause_start:
            st.paused = False
        return st

    def save(self, directory: Path | None = None) -> None:
        _atomic_write((directory or app_data_dir()) / STATE_FILE,
                      json.dumps(asdict(self), ensure_ascii=False, indent=2))

    def rollover(self, today: date) -> None:
        """新的一天：清掉昨天的暂停记录，自动开始摸鱼。"""
        key = today.isoformat()
        if self.day != key:
            self.day = key
            self.paused = False
            self.pause_start = None
            self.pause_spans = []

    def set_paused(self, flag: bool, now: datetime | None = None) -> None:
        now = now or datetime.now()
        if flag == self.paused:
            return
        if flag:
            self.paused = True
            self.pause_start = now.isoformat(timespec="seconds")
        else:
            if self.pause_start:
                self.pause_spans.append([self.pause_start, now.isoformat(timespec="seconds")])
            self.paused = False
            self.pause_start = None

    def reset_today(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        self.day = now.date().isoformat()
        self.paused = False
        self.pause_start = None
        self.pause_spans = []


# --------------------------------------------------------------------------- #
# 时段计算
# --------------------------------------------------------------------------- #
def _hms(value: str) -> float:
    """'09:00' -> 32400.0（相对当日 00:00 的秒数）"""
    h, m = value.split(":")
    return int(h) * 3600 + int(m) * 60


def _pair_maps(cfg: Settings) -> tuple[set[str], set[str]]:
    """拆出调休配对中的「休息日」与「补班日」两个集合。"""
    rests: set[str] = set()
    works: set[str] = set()
    for pair in getattr(cfg, "makeup_pairs", []) or []:
        if isinstance(pair, (list, tuple)) and len(pair) == 2:
            rests.add(pair[0])
            works.add(pair[1])
    return rests, works


def _calendar_maps(cfg: Settings) -> tuple[set[str], set[str]]:
    """自动日历中的「放假休息日」与「调休上班日」（最近一次成功数据）。"""
    rests = set(getattr(cfg, "calendar_holidays", []) or [])
    works = set(getattr(cfg, "calendar_makeup_workdays", []) or [])
    return rests, works


def is_workday(cfg: Settings, d: date) -> bool:
    """优先级：手动补班 > 手动休息 > 法定调休上班 > 法定放假 > 每周工作日。"""
    key = d.isoformat()
    rests, works = _pair_maps(cfg)
    auto_rests, auto_works = _calendar_maps(cfg)
    if key in cfg.makeup_workdays or key in works:
        return True
    if key in cfg.holidays or key in rests:
        return False
    if key in auto_works:
        return True
    if key in auto_rests:
        return False
    return d.weekday() in cfg.workdays


def day_kind(cfg: Settings, d: date) -> str:
    """当天性质：work / weekend / holiday / makeup_work / makeup_rest。

    holiday 同时涵盖手动额外休息日与自动日历里的法定放假日；
    makeup_work 同时涵盖手动与自动日历里的调休上班日。
    """
    key = d.isoformat()
    rests, works = _pair_maps(cfg)
    auto_rests, auto_works = _calendar_maps(cfg)
    # 手动配置优先于自动日历；补班 > 休息 > 每周工作日
    if key in cfg.makeup_workdays or key in works:
        return "makeup_work"
    if key in rests:
        return "makeup_rest"
    if key in cfg.holidays:
        return "holiday"
    if key in auto_works:
        return "makeup_work"
    if key in auto_rests:
        return "holiday"
    return "work" if d.weekday() in cfg.workdays else "weekend"


def work_segments(cfg: Settings, d: date | None = None) -> list[tuple[float, float]]:
    """返回当日有效工作区间（相对 00:00 的秒），已扣除午休。

    支持跨零点班次（如 22:00–06:00），也支持午休落在零点之后的情况。
    """
    s = _hms(cfg.work_start)
    e = _hms(cfg.work_end)
    if e <= s:
        e += 86400.0

    cuts: list[tuple[float, float]] = []
    if cfg.lunch_enabled:
        ls, le = _hms(cfg.lunch_start), _hms(cfg.lunch_end)
        # 把午休平移到工作时段所在的同一条时间轴上
        if ls < s:
            ls += 86400.0
        if le <= ls:
            le += 86400.0
            if le < ls:
                le += 86400.0
        cuts.append((ls, le))

    segments = [(s, e)]
    for c0, c1 in cuts:
        nxt: list[tuple[float, float]] = []
        for a, b in segments:
            x0, x1 = max(a, c0), min(b, c1)
            if x1 > x0:
                if x0 > a:
                    nxt.append((a, x0))
                if x1 < b:
                    nxt.append((x1, b))
            else:
                nxt.append((a, b))
        segments = nxt
    return [(a, b) for a, b in segments if b > a]


def full_work_seconds(cfg: Settings, d: date | None = None) -> float:
    return sum(b - a for a, b in work_segments(cfg, d))


def _day_origin(d: date) -> datetime:
    return datetime.combine(d, time.min)


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def worked_seconds(cfg: Settings, now: datetime, d: date | None = None) -> float:
    """截至 now，日期 d 已经产生的有效上班（摸鱼）秒数。"""
    d = d or now.date()
    t = (now - _day_origin(d)).total_seconds()
    return sum(_overlap(a, b, -1e12, t) for a, b in work_segments(cfg, d))


def remaining_seconds(cfg: Settings, now: datetime, d: date | None = None) -> float:
    """从 now 到下班还剩多少有效工作秒。"""
    d = d or now.date()
    t = (now - _day_origin(d)).total_seconds()
    return sum(_overlap(a, b, t, 1e12) for a, b in work_segments(cfg, d))


def hourly_rate(cfg: Settings) -> float:
    if cfg.salary_mode == "hourly":
        return max(0.0, cfg.hourly_rate)
    if cfg.salary_mode == "daily":
        full_h = full_work_seconds(cfg) / 3600.0
        return max(0.0, cfg.daily_salary / full_h) if full_h > 0 else 0.0
    denom = cfg.pay_days_per_month * cfg.hourly_divisor_hours
    return max(0.0, cfg.monthly_salary / denom) if denom > 0 else 0.0


def effective_day(cfg: Settings, now: datetime) -> date:
    """跨零点班次：次日凌晨仍归属「班次开始的那一天」。"""
    d = now.date()
    segs = work_segments(cfg, d)
    if segs and segs[-1][1] > 86400:
        t = (now - _day_origin(d)).total_seconds()
        cross_end = segs[-1][1] - 86400
        if t < cross_end and t < segs[0][0]:
            return d - timedelta(days=1)
    return d


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def paused_seconds(cfg: Settings, state: AppState, now: datetime, d: date) -> float:
    """累计「认真工作（暂停摸鱼）」的有效秒数：只统计落在工作时段内的部分。"""
    spans: list[tuple[datetime, datetime]] = []
    for pair in state.pause_spans:
        a, b = _parse_iso(pair[0]), _parse_iso(pair[1])
        if a and b and b > a:
            spans.append((a, b))
    if state.paused and state.pause_start:
        a = _parse_iso(state.pause_start)
        if a and now > a:
            spans.append((a, now))

    total = 0.0
    origin = _day_origin(d)
    # 只需要统计落在「今日」工作时段里的暂停，其余日期天然无交集
    for a, b in spans:
        x0 = (a - origin).total_seconds()
        x1 = (b - origin).total_seconds()
        for s0, s1 in work_segments(cfg, d):
            total += _overlap(s0, s1, x0, x1)
    return min(total, worked_seconds(cfg, now, d))


# --------------------------------------------------------------------------- #
# 快照
# --------------------------------------------------------------------------- #
@dataclass
class Snapshot:
    now: datetime
    day: date
    status: str                       # before | working | lunch | off | rest | paused
    status_text: str
    earned_today: float               # 今日混底薪【工资】
    fished_seconds: float             # 已摸鱼时长（秒）
    worked_seconds: float             # 未扣暂停的上班秒数
    paused_seconds: float
    remain_seconds: float                 # 剩余有效工作秒（扣掉午休）
    wall_remain_seconds: float            # 距离下班的墙上时钟秒
    progress: float                   # 0..1
    full_seconds: float
    full_pay: float
    rate: float                       # 时薪
    per_second: float                 # 每秒进账
    month_total: float
    month_fished_seconds: float
    is_workday: bool
    day_kind: str                     # work / weekend / holiday / makeup_work / makeup_rest
    date_text: str
    countdown_text: str
    fun_text: str

    @property
    def fished_hours(self) -> float:
        return self.fished_seconds / 3600.0

    @property
    def full_hours(self) -> float:
        return self.full_seconds / 3600.0

    @property
    def day_kind_label(self) -> str:
        return day_kind_label(self.day_kind)


def format_money(value: float, decimals: int = 4) -> str:
    return f"{value:,.{decimals}f}"


def format_hms(seconds: float) -> str:
    """秒 -> HH:MM:SS（可超过 24 小时）"""
    s = max(0, int(seconds + 0.5))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"


def format_chinese_duration(seconds: float) -> str:
    s = max(0, int(seconds + 0.5))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}小时{m}分{sec}秒"
    if m:
        return f"{m}分{sec}秒"
    return f"{sec}秒"


def _fun_text(cfg: Settings, snap_data: dict[str, Any]) -> str:
    if not cfg.fun_enabled:
        return "摸鱼不误砍柴工，稳住，我们能赢。"
    rate = snap_data["rate"]
    if rate <= 0:
        return "先把薪资设好，快乐才有价格。"

    name, amount = cfg.fun_target_name, cfg.fun_target_amount
    if cfg.fun_rotate:
        idx = int(snap_data["now"].timestamp() // 20) % len(FUN_TARGETS)
        name, amount = FUN_TARGETS[idx]

    if snap_data["status"] == "rest":
        return f"今天不用上班，{name}算白送的。"
    if snap_data["status"] == "off":
        return f"今天摸完啦，{name}已经到账。"

    # 关键：以「今日已赚」为基准，而不是从零起算——
    # 否则已经赚够目标了还在说"再过 X 就摸回来了"（v1.2.0 实测 bug）。
    left = amount - max(0.0, snap_data.get("earned_today", 0.0))
    if left <= 0:
        return f"今天{name}已经摸回来了，接下来都是净赚。"

    per_hour = rate / 3600.0
    need_seconds = left / per_hour if per_hour > 0 else 0
    h = int(need_seconds // 3600)
    m = int((need_seconds % 3600) // 60)
    duration = f"{h} 小时 {m} 分" if h else f"{m} 分"

    if need_seconds > snap_data["remain_seconds"] + 1:
        return f"今天剩下的时间摸不回{name}了，明天接着摸。"
    return f"再摸 {duration}，{name}就到账了。"


def compute(cfg: Settings, state: AppState, now: datetime | None = None) -> Snapshot:
    """计算一份完整的实时快照。UI 每次刷新都调用它。"""
    now = now or datetime.now()
    d = effective_day(cfg, now)
    # 跨天数据由 UI 显式 rollover + 落盘；这里只做只读隔离，
    # 保证即使调用方忘了重置，也绝不会把昨天的暂停算进今天。
    if state.day and state.day != d.isoformat():
        state = AppState(day=d.isoformat())

    rate = hourly_rate(cfg)
    per_second = rate / 3600.0
    full_secs = full_work_seconds(cfg, d)
    full_pay = full_secs / 3600.0 * rate
    raw = worked_seconds(cfg, now, d) if is_workday(cfg, d) else 0.0
    paused = paused_seconds(cfg, state, now, d)
    fished = max(0.0, raw - paused)
    earned = max(0.0, min(full_pay, fished / 3600.0 * rate)) if full_pay > 0 else 0.0
    remain = remaining_seconds(cfg, now, d) if is_workday(cfg, d) else 0.0
    progress = min(1.0, fished / full_secs) if full_secs > 0 else 0.0

    # 本月累计：已过去的工作日按满勤补算；调休休息日同样带薪（不因调休扣薪）
    first = date(d.year, d.month, 1)
    prior_days = max(0, (d - first).days)
    prior_workdays = 0
    prior_makeup_rest = 0
    for i in range(prior_days):
        x = first + timedelta(days=i)
        if is_workday(cfg, x):
            prior_workdays += 1
        elif day_kind(cfg, x) == "makeup_rest":
            prior_makeup_rest += 1
    kind = day_kind(cfg, d)
    today_paid_rest = (not is_workday(cfg, d) and kind == "makeup_rest")
    paid_days = prior_workdays + prior_makeup_rest + (1 if today_paid_rest else 0)
    month_total = paid_days * full_pay + (earned if is_workday(cfg, d) else 0.0)
    month_fished = prior_workdays * full_secs + fished

    # 状态判定
    segs = work_segments(cfg, d)
    t = (now - _day_origin(d)).total_seconds()
    in_lunch_gap = any(segs[i][1] <= t < segs[i + 1][0] for i in range(len(segs) - 1))
    end_abs = segs[-1][1]
    wall_remain = max(0.0, end_abs - t)
    if not is_workday(cfg, d):
        status = "rest"
        status_text = ("调休休息中" if kind == "makeup_rest"
                       else "节假日休息" if kind == "holiday" else "今天不摸鱼")
    elif t < segs[0][0]:
        status, status_text = "before", "还没上班"
    elif t >= end_abs:
        status, status_text = "off", "今天摸完啦"
    elif state.paused:
        status, status_text = "paused", "暂停摸鱼中"
    elif in_lunch_gap:
        status, status_text = "lunch", "午休躺平中"
    else:
        status, status_text = "working", "调休补班中" if kind == "makeup_work" else "摸鱼中"

    if status == "before":
        countdown_text = f"距离上班还有 {format_chinese_duration(max(0.0, segs[0][0] - t))}"
    elif status == "rest":
        countdown_text = ("调休休息 · 带薪按满勤补算" if kind == "makeup_rest"
                          else "休息日 · 快乐不打烊")
    elif status == "off":
        countdown_text = "已下班 · 快乐是自己的"
    elif status == "lunch":
        # 明确告知「数据冻结是午休计费暂停」，避免被当成卡死（v1.2.0 用户反馈）
        countdown_text = (f"午休中 · 计费已暂停，{cfg.lunch_end} 自动恢复"
                          f" · 距下班 {format_chinese_duration(wall_remain)}")
    else:
        countdown_text = f"距离下班还有 {format_chinese_duration(wall_remain)}"

    # 日期行显示真实墙上时钟；金额归属日 d 可能因跨零点班次是前一天
    date_text = f"{now.date().isoformat()} {DAY_NAMES[now.weekday()]} {now.strftime('%H:%M:%S')}"

    base = dict(now=now, status=status, rate=rate, remain_seconds=remain,
                earned_today=earned)
    fun_text = _fun_text(cfg, base)

    return Snapshot(
        now=now, day=d, status=status, status_text=status_text,
        earned_today=earned, fished_seconds=fished, worked_seconds=raw,
        paused_seconds=paused, remain_seconds=remain,
        wall_remain_seconds=wall_remain, progress=progress,
        full_seconds=full_secs, full_pay=full_pay, rate=rate,
        per_second=per_second, month_total=month_total,
        month_fished_seconds=month_fished, is_workday=is_workday(cfg, d),
        day_kind=kind, date_text=date_text, countdown_text=countdown_text, fun_text=fun_text,
    )


# --------------------------------------------------------------------------- #
# 小组件数据导出（供 Rainmeter / 其它桌面组件读取）
# --------------------------------------------------------------------------- #
def export_widget_data(cfg: Settings, snap: Snapshot, directory: Path | None = None) -> None:
    root = directory or app_data_dir()
    money = format_money(snap.earned_today, cfg.decimals)
    duration = format_hms(snap.fished_seconds)
    text = f"{money}\n{duration}\n{snap.status_text}\n{snap.countdown_text}\n"
    payload = json.dumps({
        "app": APP_NAME, "money": money, "money_raw": round(snap.earned_today, 6),
        "duration": duration, "duration_seconds": round(snap.fished_seconds, 2),
        "status": snap.status_text, "countdown": snap.countdown_text,
        "day_kind": snap.day_kind, "daily_salary": round(cfg.daily_salary, 4),
        "progress": round(snap.progress, 4), "per_second": round(snap.per_second, 6),
        "full_pay": round(snap.full_pay, 2), "month_total": round(snap.month_total, 2),
        "updated_at": snap.now.isoformat(timespec="seconds"),
    }, ensure_ascii=False, indent=2)

    _atomic_write(root / WIDGET_TEXT_FILE, text)
    _atomic_write(root / WIDGET_JSON_FILE, payload)

    # 可选：同步到 Rainmeter 皮肤目录，实现零配置的第三方桌面小组件
    extra = os.environ.get("MOYU_WIDGET_EXPORT_DIR")
    skins = Path.home() / "Documents" / "Rainmeter" / "Skins"
    candidates = [Path(extra)] if extra else [
        skins / "TodayMoYu",   # 推荐：ASCII 目录，避免 Rainmeter 读取中文路径
        skins / APP_NAME,
    ]
    for target in candidates:
        try:
            if target.is_dir():
                _atomic_write(target / WIDGET_TEXT_FILE, text)
                _atomic_write(target / WIDGET_JSON_FILE, payload)
        except OSError:
            pass


if __name__ == "__main__":
    cfg = Settings.load()
    st = AppState.load()
    s = compute(cfg, st)
    print(f"{APP_NAME} {APP_VERSION}  {s.date_text}")
    print(f"状态            {s.status_text}")
    print(f"今日混底薪      ¥{format_money(s.earned_today, cfg.decimals)}")
    print(f"已摸鱼时长      {format_hms(s.fished_seconds)}  ({s.fished_hours:.2f} / {s.full_hours:.2f} 小时)")
    print(f"时薪 / 每秒     ¥{s.rate:.2f} / ¥{s.per_second:.4f}")
    print(f"日薪 / 满勤     ¥{cfg.daily_salary:,.2f} / ¥{s.full_pay:,.2f}")
    print(f"当天性质        {s.day_kind}")
    print(f"进度            {s.progress * 100:.1f}%")
    print(f"本月累计        ¥{format_money(s.month_total, cfg.decimals)}")
    print(f"{s.countdown_text}")
    print(s.fun_text)
