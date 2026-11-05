# -*- coding: utf-8 -*-
"""今天摸了吗 · 核心算法单元测试（纯逻辑，不需要 GUI / 不联网）"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from core import (
    AppState, Settings, compute, day_kind, export_widget_data, format_chinese_duration,
    format_hms, format_money, full_work_seconds, hourly_rate, is_workday,
    remaining_seconds, work_segments, worked_seconds,
)


def at(day: str, h: int, m: int, s: int = 0) -> datetime:
    return datetime.fromisoformat(f"{day}T{h:02d}:{m:02d}:{s:02d}")


@pytest.fixture
def cfg() -> Settings:
    return Settings()


@pytest.fixture
def state() -> AppState:
    return AppState()


# --------------------------------------------------------------------------- #
# 视频参数还原
# --------------------------------------------------------------------------- #
def test_video_reference_values(cfg, state):
    """2026-11-02 周一 15:05:36 应还原视频中的关键数字。"""
    now = at("2026-11-02", 15, 5, 36)
    assert now.weekday() == 0
    snap = compute(cfg, state, now)

    assert full_work_seconds(cfg, now.date()) == 7.5 * 3600
    assert hourly_rate(cfg) == pytest.approx(17.24, abs=1e-9)
    assert snap.full_pay == pytest.approx(129.30, abs=1e-6)
    assert snap.per_second == pytest.approx(0.0047889, abs=1e-6)
    assert snap.earned_today == pytest.approx(79.184, abs=0.02)   # 视频 ¥79.1865
    assert snap.fished_hours == pytest.approx(4.59, abs=0.01)     # 视频 4.59 / 7.50
    assert snap.progress == pytest.approx(0.612, abs=0.002)       # 视频 61.2%
    assert snap.countdown_text == "距离下班还有 2小时54分24秒"
    assert "一件 T 恤" in snap.fun_text


def test_money_grows_in_realtime(cfg, state):
    """同一天内金额按每秒 ¥0.0048 线性增长。"""
    a = compute(cfg, state, at("2026-11-02", 15, 5, 35))
    b = compute(cfg, state, at("2026-11-02", 15, 5, 42))  # 视频末尾 15:05:42
    assert b.earned_today - a.earned_today == pytest.approx(7 * hourly_rate(cfg) / 3600, abs=1e-9)
    assert b.fished_seconds - a.fished_seconds == 7
    assert b.earned_today == pytest.approx(79.2175, abs=0.02)  # 视频 ¥79.2209


# --------------------------------------------------------------------------- #
# 时段边界
# --------------------------------------------------------------------------- #
def test_work_segments(cfg):
    segs = work_segments(cfg, date(2026, 11, 2))
    assert segs == [(9 * 3600, 12 * 3600), (13 * 3600 + 1800, 18 * 3600)]
    assert sum(b - a for a, b in segs) == 27000


def test_before_work_and_after_work(cfg, state):
    before = compute(cfg, state, at("2026-11-02", 8, 59, 59))
    assert before.status == "before"
    assert before.earned_today == 0.0
    assert before.fished_seconds == 0.0
    assert before.progress == 0.0

    after = compute(cfg, state, at("2026-11-02", 19, 30, 0))
    assert after.status == "off"
    assert after.earned_today == pytest.approx(129.30, abs=1e-6)
    assert after.progress == 1.0
    assert after.remain_seconds == 0


def test_lunch_break_does_not_pay(cfg, state):
    """午休 12:00–13:30 不计薪，金额与时长原地不动。"""
    a = compute(cfg, state, at("2026-11-02", 12, 0, 0))
    b = compute(cfg, state, at("2026-11-02", 13, 29, 59))
    c = compute(cfg, state, at("2026-11-02", 13, 30, 0))
    assert b.status == "lunch"
    assert b.earned_today == pytest.approx(a.earned_today, abs=1e-9)
    assert b.fished_seconds == a.fished_seconds
    assert c.fished_seconds == b.fished_seconds  # 13:30:00 刚开始下午段
    assert "距离下班还有" in c.countdown_text


def test_no_lunch_mode():
    cfg = Settings(lunch_enabled=False)
    assert full_work_seconds(cfg) == 9 * 3600
    state = AppState()
    snap = compute(cfg, state, at("2026-11-02", 12, 30, 0))
    assert snap.status == "working"
    assert snap.fished_seconds == 3.5 * 3600


# --------------------------------------------------------------------------- #
# 工作日 / 节假日 / 调休
# --------------------------------------------------------------------------- #
def test_weekend_and_holiday_and_makeup(cfg, state):
    sunday = compute(cfg, state, at("2026-11-08", 15, 0, 0))
    assert sunday.status == "rest"
    assert sunday.earned_today == 0.0
    assert sunday.month_total > 0  # 之前的日子按满勤补算

    cfg.holidays = ["2026-11-02"]
    assert not is_workday(cfg, date(2026, 11, 2))
    holiday = compute(cfg, AppState(), at("2026-11-02", 15, 0, 0))
    assert holiday.status == "rest" and holiday.earned_today == 0

    cfg.holidays = ["2026-11-08"]
    cfg.makeup_workdays = ["2026-11-08"]
    assert is_workday(cfg, date(2026, 11, 8))  # 调休优先级高于周末
    makeup = compute(cfg, AppState(), at("2026-11-08", 15, 0, 0))
    assert makeup.status == "working" and makeup.earned_today > 0


def test_month_accumulation(cfg, state):
    """11/2 是当月第一个工作日 -> 本月累计 == 今日已赚（与视频一致）。"""
    snap = compute(cfg, state, at("2026-11-02", 15, 5, 36))
    assert snap.month_total == pytest.approx(snap.earned_today, abs=1e-9)

    later = compute(cfg, state, at("2026-11-04", 15, 0, 0))
    assert later.month_total == pytest.approx(2 * 129.30 + later.earned_today, abs=0.01)


# --------------------------------------------------------------------------- #
# 暂停摸鱼
# --------------------------------------------------------------------------- #
def test_pause_freezes_money(cfg, state):
    now = at("2026-11-02", 15, 0, 0)
    state.set_paused(True, now)
    a = compute(cfg, state, now)
    b = compute(cfg, state, now + timedelta(minutes=30))
    assert a.status == "paused"
    assert b.earned_today == pytest.approx(a.earned_today, abs=1e-9)
    assert b.fished_seconds == pytest.approx(a.fished_seconds, abs=1e-9)

    state.set_paused(False, now + timedelta(minutes=30))
    c = compute(cfg, state, now + timedelta(minutes=31))
    assert c.earned_today - a.earned_today == pytest.approx(hourly_rate(cfg) / 3600 * 60, abs=1e-6)


def test_pause_during_lunch_does_not_deduct(cfg, state):
    """午休本来就不计薪，此时暂停不应额外扣钱。"""
    now = at("2026-11-02", 10, 0, 0)
    base = compute(cfg, state, at("2026-11-02", 15, 0, 0))
    state.set_paused(True, at("2026-11-02", 12, 0, 0))
    state.set_paused(False, at("2026-11-02", 13, 30, 0))
    after = compute(cfg, state, at("2026-11-02", 15, 0, 0))
    assert after.earned_today == pytest.approx(base.earned_today, abs=1e-9)


def test_rollover_resets_daily_state(state):
    state.day = "2026-11-02"
    state.paused = True
    state.pause_start = "2026-11-02T15:00:00"
    state.pause_spans = [["2026-11-02T10:00:00", "2026-11-02T10:30:00"]]
    state.rollover(date(2026, 11, 3))
    assert state.day == "2026-11-03"
    assert state.paused is False
    assert state.pause_spans == []


def test_reset_today(state):
    state.day = "2026-11-02"
    state.paused = True
    state.pause_start = "2026-11-02T15:00:00"
    state.reset_today(at("2026-11-02", 16, 0, 0))
    assert not state.paused and state.pause_spans == []


# --------------------------------------------------------------------------- #
# 跨零点班次 / 异常配置容错
# --------------------------------------------------------------------------- #
def test_overnight_shift():
    cfg = Settings(work_start="22:00", work_end="06:00",
                   lunch_start="00:00", lunch_end="00:30")
    assert full_work_seconds(cfg) == pytest.approx(7.5 * 3600)
    snap = compute(cfg, AppState(), at("2026-11-03", 1, 0, 0))
    # 11/3 凌晨属于 11/2 的班次：本日维度不倒扣，结果非负
    assert snap.earned_today >= 0
    assert snap.fished_seconds >= 0


def test_settings_tolerant_to_bad_values():
    s = Settings.from_dict({
        "salary_mode": "???", "monthly_salary": "abc", "decimals": 999,
        "work_start": "99:99", "workdays": ["x", 9, 2], "holidays": "not-a-list",
        "widget_pos": [1.5, "a"], "unknown_field": 123,
    })
    assert s.salary_mode == "daily"
    assert s.monthly_salary == 3000.0
    assert 0 <= s.decimals <= 6
    assert s.work_start == "09:00"
    assert s.workdays == [2]
    assert s.holidays == []
    assert s.widget_pos is None


def test_config_roundtrip(tmp_path: Path):
    cfg = Settings(monthly_salary=8888, workdays=[0, 1, 2, 3, 4, 5], decimals=2)
    cfg.save(tmp_path)
    loaded = Settings.load(tmp_path)
    assert loaded.monthly_salary == 8888
    assert loaded.workdays == [0, 1, 2, 3, 4, 5]
    assert loaded.decimals == 2


def test_state_roundtrip(tmp_path: Path):
    st = AppState(day="2026-11-02", paused=True, pause_start="2026-11-02T15:00:00")
    st.save(tmp_path)
    loaded = AppState.load(tmp_path)
    assert loaded.day == "2026-11-02" and loaded.paused


def test_export_widget_data(tmp_path: Path, cfg, state):
    snap = compute(cfg, state, at("2026-11-02", 15, 5, 36))
    export_widget_data(cfg, snap, tmp_path)
    lines = (tmp_path / "widget.txt").read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("79.")
    assert lines[1] == "04:35:36"
    assert (tmp_path / "widget.json").exists()


# --------------------------------------------------------------------------- #
# 格式化
# --------------------------------------------------------------------------- #
def test_formatters():
    assert format_hms(4 * 3600 + 35 * 60 + 12) == "04:35:12"
    assert format_hms(-5) == "00:00:00"
    assert format_hms(25 * 3600) == "25:00:00"
    assert format_chinese_duration(2 * 3600 + 54 * 60 + 24) == "2小时54分24秒"
    assert format_money(79.1865, 4) == "79.1865"
    assert format_money(12345.6, 2) == "12,345.60"


def test_zero_salary_is_safe(state):
    cfg = Settings(salary_mode="hourly", hourly_rate=0)
    snap = compute(cfg, state, at("2026-11-02", 15, 0, 0))
    assert snap.earned_today == 0
    assert snap.full_pay == 0
    assert "薪资" in snap.fun_text


# --------------------------------------------------------------------------- #
# 月薪 → 日薪联动（用户反馈的缺陷）
# --------------------------------------------------------------------------- #
def monthly_expected(monthly: float, pay_days: float = 21.75,
                     divisor: float = 8.0, full_h: float = 7.5) -> float:
    return monthly / (pay_days * divisor) * full_h


def test_monthly_change_recomputes_daily_salary():
    """月薪从默认 3000 改到 6000，日薪必须立刻按项目规则重算，不能留 129.30。"""
    cfg = Settings.from_dict({
        "salary_mode": "monthly", "monthly_salary": 6000.0,
        "daily_salary": 129.30,          # 故意塞入旧日薪
    })
    assert cfg.daily_salary == pytest.approx(monthly_expected(6000), abs=0.001)
    assert cfg.daily_salary == pytest.approx(258.6207, abs=0.001)
    assert cfg.daily_salary != 129.30
    assert hourly_rate(cfg) == pytest.approx(6000 / (21.75 * 8), abs=1e-6)


def test_monthly_change_save_reload_is_consistent(tmp_path: Path):
    """保存 → 重新打开 → 再次读取，日薪始终是同一个新值。"""
    cfg = Settings.from_dict({"salary_mode": "monthly", "monthly_salary": 6000.0,
                              "daily_salary": 129.30})
    cfg.save(tmp_path)
    on_disk = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert on_disk["daily_salary"] == pytest.approx(cfg.daily_salary, abs=1e-9)
    assert on_disk["daily_salary"] != 129.30

    loaded = Settings.load(tmp_path)
    assert loaded.daily_salary == pytest.approx(cfg.daily_salary, abs=1e-9)
    assert loaded.monthly_salary == 6000.0
    # 再存一次 / 再读一次，幂等
    loaded.save(tmp_path)
    again = Settings.load(tmp_path)
    assert again.daily_salary == pytest.approx(cfg.daily_salary, abs=1e-9)
    assert again.hourly_rate == pytest.approx(loaded.hourly_rate, abs=1e-9)


def test_old_daily_salary_never_survives_config_reload(tmp_path: Path):
    """模拟旧配置文件里残留旧日薪；加载后必须被重新推导覆盖。"""
    raw = {"salary_mode": "monthly", "monthly_salary": 9000.0,
           "daily_salary": 129.30, "hourly_rate": 17.24}
    (tmp_path / "config.json").write_text(json.dumps(raw), encoding="utf-8")
    cfg = Settings.load(tmp_path)
    assert cfg.daily_salary == pytest.approx(monthly_expected(9000), abs=0.001)
    assert cfg.daily_salary > 380
    snap = compute(cfg, AppState(), at("2026-11-02", 15, 0, 0))
    assert snap.full_pay == pytest.approx(monthly_expected(9000), abs=0.01)


def test_multiple_monthly_changes_are_linear():
    cfg = Settings.from_dict({"salary_mode": "monthly", "monthly_salary": 3000.0})
    d1 = cfg.daily_salary
    for value in (4500.0, 9000.0, 1200.0):
        cfg.monthly_salary = value
        cfg.sync_salary()
        assert cfg.daily_salary == pytest.approx(monthly_expected(value), abs=0.001)
    assert d1 == pytest.approx(monthly_expected(3000), abs=0.001)


def test_pay_days_divisor_and_work_hours_also_update_daily():
    cfg = Settings.from_dict({"salary_mode": "monthly", "monthly_salary": 6000.0})
    base = cfg.daily_salary
    cfg.pay_days_per_month = 30.0
    cfg.sync_salary()
    assert cfg.daily_salary < base

    cfg.hourly_divisor_hours = 10.0
    cfg.sync_salary()
    assert cfg.daily_salary < base * 0.7

    cfg2 = Settings.from_dict({"salary_mode": "monthly", "monthly_salary": 6000.0,
                               "work_end": "17:00"})   # 每日 6.5 小时
    assert cfg2.daily_salary == pytest.approx(monthly_expected(6000, full_h=6.5), abs=0.001)


def test_daily_and_hourly_modes_keep_their_own_source_value():
    daily = Settings.from_dict({"salary_mode": "daily", "daily_salary": 200.0,
                                "monthly_salary": 3000.0})
    assert daily.daily_salary == 200.0
    assert hourly_rate(daily) == pytest.approx(200 / 7.5, abs=1e-6)

    hourly = Settings.from_dict({"salary_mode": "hourly", "hourly_rate": 30.0,
                                 "daily_salary": 129.30})
    assert hourly.hourly_rate == 30.0
    assert hourly.daily_salary == pytest.approx(30 * 7.5, abs=0.001)
    assert hourly.daily_salary != 129.30


# --------------------------------------------------------------------------- #
# 调休功能
# --------------------------------------------------------------------------- #
def test_makeup_pair_switches_rest_and_work_day():
    """2026-11-02 周一休息，2026-11-08 周日补班。"""
    cfg = Settings(makeup_pairs=[["2026-11-02", "2026-11-08"]])
    assert not is_workday(cfg, date(2026, 11, 2))
    assert day_kind(cfg, date(2026, 11, 2)) == "makeup_rest"
    assert is_workday(cfg, date(2026, 11, 8))
    assert day_kind(cfg, date(2026, 11, 8)) == "makeup_work"

    rest = compute(cfg, AppState(), at("2026-11-02", 15, 0, 0))
    assert rest.status_text == "调休休息中"
    assert rest.earned_today == 0
    assert "满勤补算" in rest.countdown_text
    assert rest.day_kind == "makeup_rest"

    work = compute(cfg, AppState(), at("2026-11-08", 15, 0, 0))
    assert work.status_text == "调休补班中"
    assert work.earned_today > 0
    assert work.day_kind == "makeup_work"


def test_makeup_rest_day_is_paid_in_month_total():
    """调休休息日不计今日金额，但本月累计按满勤补算，不因调休扣薪。"""
    cfg = Settings(makeup_pairs=[["2026-11-02", "2026-11-08"]])
    snap = compute(cfg, AppState(), at("2026-11-03", 15, 0, 0))
    # 11/2 是已过去的调休休息日 → 补算 1 个满勤日
    assert snap.month_total == pytest.approx(snap.full_pay + snap.earned_today, abs=0.01)

    plain = compute(Settings(), AppState(), at("2026-11-03", 15, 0, 0))
    assert snap.month_total > plain.month_total - 0.01   # 不比正常情况少


def test_makeup_work_day_overrides_holiday():
    cfg = Settings(makeup_pairs=[["2026-11-02", "2026-11-08"]],
                   holidays=["2026-11-08"])
    assert is_workday(cfg, date(2026, 11, 8))
    assert day_kind(cfg, date(2026, 11, 8)) == "makeup_work"


def test_makeup_pairs_roundtrip_and_validation(tmp_path: Path):
    cfg = Settings.from_dict({"makeup_pairs": [["2026-11-02", "2026-11-08"], ["bad"], []]})
    assert cfg.makeup_pairs == [["2026-11-02", "2026-11-08"]]
    cfg.save(tmp_path)
    assert Settings.load(tmp_path).makeup_pairs == [["2026-11-02", "2026-11-08"]]

    bad = Settings.from_dict({"makeup_pairs": "not-a-list"})
    assert bad.makeup_pairs == []


def test_makeup_works_with_existing_lists():
    """新的调休配对与原有的 holidays / makeup_workdays 可以叠加使用。"""
    cfg = Settings(holidays=["2026-11-03"], makeup_workdays=["2026-11-07"],
                   makeup_pairs=[["2026-11-02", "2026-11-08"]])
    assert not is_workday(cfg, date(2026, 11, 3))
    assert is_workday(cfg, date(2026, 11, 7))
    assert is_workday(cfg, date(2026, 11, 8))
    assert not is_workday(cfg, date(2026, 11, 2))
