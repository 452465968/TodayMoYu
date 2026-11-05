# -*- coding: utf-8 -*-
"""今天摸了吗 · 刷新间隔 / 自动节假日日历 的单元测试（不联网）"""
from __future__ import annotations

import json
import urllib.request
from datetime import date, datetime

import pytest

import holiday_calendar as hc
from core import (
    AppState, Settings, calendar_sync_interval_ms, compute, day_kind,
    day_kind_label, is_workday, validate_refresh_interval,
)


def payload(year: int = 2026) -> dict:
    return {
        "year": year,
        "papers": ["https://www.gov.cn/zhengce/zhengceku/xxx.htm"],
        "days": [
            {"name": "元旦", "date": f"{year}-01-01", "isOffDay": True},
            {"name": "元旦", "date": f"{year}-01-02", "isOffDay": True},
            {"name": "元旦", "date": f"{year}-01-04", "isOffDay": False},
        ],
    }


# --------------------------------------------------------------------------- #
# 一、刷新间隔：数值 + 单位 / 范围校验 / 旧配置兼容 / 持久化
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("value,unit,expect_ms", [
    (100, "ms", 100), (1, "s", 1000), (5, "min", 300_000),
    (0.5, "h", 1_800_000),
])
def test_refresh_units(value, unit, expect_ms):
    ok, msg, ms = validate_refresh_interval(value, unit)
    assert ok and msg == "" and ms == expect_ms


@pytest.mark.parametrize("value,unit", [
    (0, "s"), (-1, "ms"), (float("nan"), "s"), (1, "week"),
    (99_999_999, "ms"), (0.0001, "min"), ("abc", "s"),
])
def test_refresh_rejects_invalid_values(value, unit):
    ok, msg, ms = validate_refresh_interval(value, unit)
    assert not ok and msg
    assert 50 <= ms <= 3_600_000


def test_old_config_only_has_refresh_ms():
    """旧 config.json 只有 refresh_ms 时，自动回填一组等价的数值 + 单位。"""
    s = Settings.from_dict({"refresh_ms": 500})
    assert s.refresh_ms == 500
    assert s.refresh_unit == "s" and s.refresh_value == 0.5


def test_new_parts_win_over_stale_refresh_ms():
    s = Settings.from_dict({"refresh_ms": 100, "refresh_value": 2, "refresh_unit": "s"})
    assert s.refresh_ms == 2000
    assert s.refresh_value == 2 and s.refresh_unit == "s"


def test_refresh_save_and_reload_are_consistent(tmp_path):
    s = Settings()
    s.refresh_value, s.refresh_unit = 2, "s"
    s.normalize_refresh()
    s.save(tmp_path)
    raw = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert raw["refresh_ms"] == 2000
    assert raw["refresh_value"] == 2 and raw["refresh_unit"] == "s"
    loaded = Settings.load(tmp_path)
    assert loaded.refresh_ms == 2000
    assert loaded.refresh_value == 2 and loaded.refresh_unit == "s"
    loaded.save(tmp_path)
    assert Settings.load(tmp_path).refresh_ms == 2000          # 再次保存幂等


def test_calendar_sync_period_follows_refresh_interval():
    assert calendar_sync_interval_ms(100) == 15 * 60 * 1000   # 下限 15 分钟
    assert calendar_sync_interval_ms(5000) == 50 * 60 * 1000  # 5 秒 → 50 分钟
    assert calendar_sync_interval_ms(3_600_000) == 24 * 60 * 60 * 1000  # 上限 24 小时


# --------------------------------------------------------------------------- #
# 二、日历解析、镜像重试、部分失败、离线沿用
# --------------------------------------------------------------------------- #
def test_parse_holiday_cn_distinguishes_rest_and_makeup():
    d = hc.parse_holiday_cn(payload())
    assert d.published and d.years == [2026]
    assert d.holidays == ["2026-01-01", "2026-01-02"]
    assert d.makeup_workdays == ["2026-01-04"]
    assert d.days["2026-01-04"]["name"] == "元旦"


def test_parse_rejects_broken_payload():
    with pytest.raises(ValueError):
        hc.parse_holiday_cn({"year": 2026})
    with pytest.raises(ValueError):
        hc.parse_holiday_cn({"year": "2026", "days": []})
    assert not hc.parse_holiday_cn({"year": 2027, "days": []}).published  # 尚未公布


def test_fetch_year_falls_back_to_mirror():
    calls = []

    def fetcher(url, timeout):
        calls.append(url)
        if "cdn.jsdelivr.net" in url:
            raise OSError("主源超时")
        return payload()

    d = hc.fetch_year(2026, fetcher=fetcher)
    assert len(calls) == 2 and "fastly.jsdelivr.net" in calls[1]
    assert len(d.days) == 3


def test_fetch_year_all_sources_down():
    def fetcher(url, timeout):
        raise OSError("offline")

    with pytest.raises(hc.CalendarFetchError):
        hc.fetch_year(2026, fetcher=fetcher)


def test_partial_year_failure_keeps_success():
    def fetcher(url, timeout):
        if "/2027.json" in url:
            raise OSError("offline")
        return payload(2026)

    fresh, failed = hc.fetch_years([2026, 2027], fetcher=fetcher)
    assert fresh.published and fresh.years == [2026]
    assert failed == [2027]


def test_merge_replaces_successful_year_only():
    old = hc.CalendarData(
        years=[2025, 2026], updated_at="2026-01-01T00:00:00", source="旧",
        days={"2025-01-01": {"name": "元旦", "off": True},
              "2026-01-01": {"name": "旧数据", "off": True}})
    fresh = hc.CalendarData(
        years=[2026], updated_at="2026-11-05T10:00:00", source="新",
        days={"2026-01-01": {"name": "新数据", "off": True},
              "2026-01-04": {"name": "元旦", "off": False}})
    merged = hc.merge_calendar(old, fresh)
    assert merged.years == [2025, 2026]
    assert merged.days["2025-01-01"]["name"] == "元旦"        # 失败年份保留旧数据
    assert merged.days["2026-01-01"]["name"] == "新数据"      # 成功年份整体替换
    assert merged.makeup_workdays == ["2026-01-04"]
    assert merged.updated_at == "2026-11-05T10:00:00"


def test_offline_uses_last_successful_cache(tmp_path):
    good = hc.CalendarData(years=[2026], updated_at="2026-11-05T10:00:00",
                           source="上次成功",
                           days={"2026-01-01": {"name": "元旦", "off": True},
                                 "2026-01-04": {"name": "元旦", "off": False}})
    hc.save_cache(good, tmp_path)

    def offline(url, timeout):
        raise OSError("offline")

    fresh, failed = hc.fetch_years([2026, 2027], fetcher=offline)
    assert not fresh.published and failed == [2026, 2027]
    cached = hc.load_cache(tmp_path)
    merged = hc.merge_calendar(cached, fresh)                 # 空结果不覆盖缓存
    hc.save_cache(merged, tmp_path)
    cfg = Settings()
    hc.apply_to_settings(cfg, merged)
    assert cfg.calendar_holidays == ["2026-01-01"]
    assert cfg.calendar_makeup_workdays == ["2026-01-04"]
    assert hc.load_cache(tmp_path).days == good.days


def test_factory_baseline_is_available_without_cache(tmp_path):
    base = hc.load_cache(tmp_path)                           # 无缓存 → 出厂基线
    assert base.published and 2026 in base.years
    assert base.holidays and base.makeup_workdays
    assert "2026-01-04" in base.makeup_workdays


# --------------------------------------------------------------------------- #
# 三、工作日 / 休息日 / 调休上班日 严格区分
# --------------------------------------------------------------------------- #
def test_three_day_kinds_from_auto_calendar():
    cfg = Settings()
    cfg.calendar_holidays = ["2026-01-01", "2026-01-02"]     # 法定放假
    cfg.calendar_makeup_workdays = ["2026-01-04"]            # 周日补班
    assert day_kind(cfg, date(2026, 1, 1)) == "holiday"
    assert not is_workday(cfg, date(2026, 1, 1))
    assert day_kind(cfg, date(2026, 1, 3)) == "weekend"      # 周六
    assert day_kind(cfg, date(2026, 1, 4)) == "makeup_work"
    assert is_workday(cfg, date(2026, 1, 4))
    assert day_kind(cfg, date(2026, 1, 5)) == "work"         # 周一
    assert day_kind_label("makeup_work") == "调休上班日"


def test_manual_dates_override_auto_calendar():
    cfg = Settings()
    cfg.calendar_makeup_workdays = ["2026-01-01"]
    cfg.holidays = ["2026-01-01"]                            # 手动休息优先
    assert day_kind(cfg, date(2026, 1, 1)) == "holiday"
    assert not is_workday(cfg, date(2026, 1, 1))
    cfg.makeup_workdays = ["2026-01-01"]                     # 手动补班最优先
    assert day_kind(cfg, date(2026, 1, 1)) == "makeup_work"
    assert is_workday(cfg, date(2026, 1, 1))


def test_compute_on_auto_makeup_workday_and_holiday():
    cfg = Settings()
    cfg.calendar_makeup_workdays = ["2026-01-04"]
    cfg.calendar_holidays = ["2026-01-01"]
    w = compute(cfg, AppState(), datetime.fromisoformat("2026-01-04T15:00:00"))
    assert w.day_kind == "makeup_work" and w.status_text == "调休补班中"
    assert w.earned_today > 0 and w.is_workday
    h = compute(cfg, AppState(), datetime.fromisoformat("2026-01-01T15:00:00"))
    assert h.day_kind == "holiday" and h.status_text == "节假日休息"
    assert h.earned_today == 0 and not h.is_workday
    assert h.month_total == 0                                # 法定放假不按满勤补发


def test_settings_from_dict_reads_calendar_fields():
    cfg = Settings.from_dict({
        "calendar_auto_sync": True,
        "calendar_holidays": ["2026-01-01"],
        "calendar_makeup_workdays": ["2026-01-04"],
        "calendar_updated_at": "2026-11-05T10:00:00",
        "calendar_years": [2026],
    })
    assert cfg.calendar_holidays == ["2026-01-01"]
    assert cfg.calendar_makeup_workdays == ["2026-01-04"]
    assert cfg.calendar_years == [2026]
    assert day_kind(cfg, date(2026, 1, 4)) == "makeup_work"


# --------------------------------------------------------------------------- #
# 五、请求头必须是 ASCII（中文 User-Agent 会让 urllib 抛 UnicodeEncodeError，
#     曾导致自动获取节假日 100% 失败，这里锁死回归）
# --------------------------------------------------------------------------- #
def test_user_agent_is_ascii_and_buildable():
    ua = hc.USER_AGENT
    assert ua.isascii(), f"User-Agent 必须为 ASCII：{ua!r}"
    # latin-1 可编码即代表能安全放进 HTTP 头
    ua.encode("latin-1")
    # 真正构造一次请求对象，确保不会在发送前抛 UnicodeEncodeError
    req = urllib.request.Request(
        "https://example.invalid/2026.json",
        headers={"User-Agent": ua, "Accept": "application/json"})
    assert req.get_header("User-agent") == ua


def test_fetch_year_error_message_lists_each_source():
    def boom(url, timeout):
        raise OSError("network down")

    with pytest.raises(hc.CalendarFetchError) as exc:
        hc.fetch_year(2026, fetcher=boom)
    msg = str(exc.value)
    for host in ("cdn.jsdelivr.net", "fastly.jsdelivr.net", "raw.githubusercontent.com"):
        assert host in msg
