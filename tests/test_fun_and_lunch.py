# -*- coding: utf-8 -*-
"""今天摸了吗 · v1.2.1 修复回归：小目标文案 / 午休提示 / 状态倒计时。

核心是锁死 v1.2.0 的实测 bug：
* 今日已赚 ¥51.72 > 目标 ¥50，趣味文案却还在说「再过 2 小时 53 分摸回来」。
* 午休期间金额 / 时长冻结（设计行为），但界面没有任何「计费已暂停」的提示。
"""
from __future__ import annotations

from datetime import datetime

import pytest

from core import Settings, compute, work_segments, full_work_seconds


def make_cfg(**kw) -> Settings:
    base = dict(work_start="09:00", work_end="18:00", lunch_enabled=True,
                lunch_start="12:00", lunch_end="13:30", salary_mode="daily",
                daily_salary=129.3103, decimals=4)
    base.update(kw)
    return Settings.from_dict(base)


class State:
    """compute 只需要 day / paused / pause_spans / pause_start。"""

    def __init__(self, day="2026-11-05", paused=False):
        self.day = day
        self.paused = paused
        self.pause_spans = []
        self.pause_start = None


def lunch_snap(**kw):
    cfg = make_cfg(**kw)
    # 13:28:20 —— 正好在午休内
    return cfg, compute(cfg, State(), datetime(2026, 11, 5, 13, 28, 20))


# --------------------------------------------------------------------------- #
# 一、小目标文案：必须以「今日已赚」为基准
# --------------------------------------------------------------------------- #
def test_fun_text_acks_target_already_earned():
    cfg, snap = lunch_snap(fun_target_name="一件 T 恤", fun_target_amount=50.0)
    # 9:00-12:00 已摸 3h × 17.24 = 51.72 > 50
    assert "已经摸回来" in snap.fun_text, snap.fun_text
    assert "再过" not in snap.fun_text and "再摸" not in snap.fun_text


def test_fun_text_counts_down_when_not_yet_earned():
    cfg, snap = lunch_snap(fun_target_name="一杯奶茶", fun_target_amount=100.0)
    # 还差 100 - 51.72 ≈ 48.28 元 ≈ 2 小时 48 分
    assert "再摸" in snap.fun_text, snap.fun_text
    assert "2 小时" in snap.fun_text
    assert "到账" in snap.fun_text


def test_fun_text_no_longer_counts_from_zero():
    """回归：v1.2.0 的文案是从 0 起算（50 元全须 2h53m），与已赚无关。"""
    cfg, snap = lunch_snap(fun_target_amount=50.0)
    assert "2 小时 53 分" not in snap.fun_text


def test_fun_text_off_status_still_announces():
    cfg = make_cfg(fun_target_amount=50.0)
    snap = compute(cfg, State(), datetime(2026, 11, 5, 19, 0, 0))
    assert "已经到账" in snap.fun_text


def test_fun_text_rest_day():
    cfg = make_cfg(fun_target_amount=50.0, workdays=[0, 1, 2, 3, 4])
    snap = compute(cfg, State(), datetime(2026, 11, 7, 10, 0, 0))   # 周六
    assert snap.status == "rest"
    assert "白送" in snap.fun_text


# --------------------------------------------------------------------------- #
# 二、午休提示：冻结必须被明确解释
# --------------------------------------------------------------------------- #
def test_lunch_countdown_explains_pause():
    _, snap = lunch_snap()
    assert snap.status == "lunch"
    assert "计费已暂停" in snap.countdown_text
    assert "13:30" in snap.countdown_text          # 恢复时间
    assert "距下班" in snap.countdown_text


def test_lunch_freezes_money_and_time_by_design():
    _, s1 = lunch_snap()
    cfg, s2 = lunch_snap()
    # 午休内再过 1 分钟：金额与时长完全不变（这是设计，不是 bug）
    from core import compute as c
    s2 = c(cfg, State(), datetime(2026, 11, 5, 13, 29, 20))
    assert s2.fished_seconds == pytest.approx(s1.fished_seconds)
    assert s2.earned_today == pytest.approx(s1.earned_today)


def test_working_status_speed_line_unchanged():
    cfg = make_cfg()
    snap = compute(cfg, State(), datetime(2026, 11, 5, 10, 0, 0))
    assert snap.status == "working"
    assert "计费已暂停" not in snap.countdown_text


# --------------------------------------------------------------------------- #
# 三、倒计时数值：以真实系统时钟为基准（13:28:20 → 4小时31分40秒）
# --------------------------------------------------------------------------- #
def test_wall_remain_matches_wall_clock():
    _, snap = lunch_snap()
    # 13:28:20 → 18:00:00 = 4h31m40s
    assert snap.wall_remain_seconds == pytest.approx(4 * 3600 + 31 * 60 + 40)
    assert "4小时31分40秒" in snap.countdown_text


def test_work_segments_exclude_lunch():
    cfg = make_cfg()
    segs = work_segments(cfg)
    assert segs == [(9 * 3600, 12 * 3600), (13.5 * 3600, 18 * 3600)]
    assert full_work_seconds(cfg) == pytest.approx(7.5 * 3600)
