# -*- coding: utf-8 -*-
"""今天摸了吗 · 自动更新模块单元测试（全部离线，用注入的 fetcher）。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import updater


# --------------------------------------------------------------------------- #
# 一、版本解析与比较
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,expect", [
    ("v1.2.0", (1, 2, 0)),
    ("1.2.0", (1, 2, 0)),
    ("v1.10.3", (1, 10, 3)),
    ("1.2", (1, 2)),
    ("v2.0.0-beta.1", (2, 0, 0, 1)),
    ("", ()),
    ("nightly", ()),
    (None, ()),
])
def test_parse_version(text, expect):
    assert updater.parse_version(text) == expect


@pytest.mark.parametrize("cur,new,expect", [
    ("1.2.0", "1.2.1", True),
    ("1.2.0", "1.3.0", True),
    ("1.2.0", "2.0.0", True),
    ("1.2.0", "1.2.0", False),
    ("1.2.1", "1.2.0", False),
    ("1.2.0", "v1.2.0", False),
    ("1.9.9", "1.10.0", True),      # 不能被字符串比较骗到
    ("1.2", "1.2.0", False),        # 补齐后相等
    ("0.0.0", "0.0.1", True),
])
def test_is_newer(cur, new, expect):
    assert updater.is_newer(cur, new) is expect


# --------------------------------------------------------------------------- #
# 二、Release 解析与资产挑选
# --------------------------------------------------------------------------- #
def release_payload(tag="v1.2.1", assets=None, draft=False, prerelease=False):
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/452465968/TodayMoYu/releases/tag/{tag}",
        "body": "## 修复\n- 若干",
        "draft": draft,
        "prerelease": prerelease,
        "published_at": "2026-11-05T05:00:00Z",
        "assets": assets if assets is not None else [
            {"name": "TodayMoYu-Windows-Portable-v1.2.1.zip", "size": 86_000_000,
             "browser_download_url": "https://example.com/win.zip"},
            {"name": "TodayMoYu-macOS-v1.2.1.zip", "size": 30_000_000,
             "browser_download_url": "https://example.com/mac.zip"},
        ],
    }


def test_parse_release_picks_platform_asset():
    win = updater.parse_release(release_payload(), "win32")
    mac = updater.parse_release(release_payload(), "darwin")
    assert win.asset_name == "TodayMoYu-Windows-Portable-v1.2.1.zip"
    assert mac.asset_name == "TodayMoYu-macOS-v1.2.1.zip"
    assert win.version == "1.2.1"
    assert win.asset_mb == pytest.approx(86_000_000 / 1024 / 1024)


@pytest.mark.parametrize("flag", ["draft", "prerelease"])
def test_parse_release_ignores_unpublished(flag):
    assert updater.parse_release(release_payload(**{flag: True})) is None


def test_parse_release_single_zip_fallback():
    payload = release_payload(assets=[
        {"name": "random-name.zip", "size": 10, "browser_download_url": "https://e/x.zip"}])
    info = updater.parse_release(payload, "win32")
    assert info.asset_name == "random-name.zip"


def test_parse_release_without_asset_still_reports_version():
    info = updater.parse_release(release_payload(assets=[]), "darwin")
    assert info.version == "1.2.1"
    assert info.asset_url == ""


# --------------------------------------------------------------------------- #
# 三、check_latest：有新版 / 已最新 / 网络异常 / 无 Release
# --------------------------------------------------------------------------- #
def test_check_latest_returns_update():
    info = updater.check_latest("1.2.0", platform="darwin",
                                fetcher=lambda url, t: release_payload())
    assert info is not None and info.version == "1.2.1"


def test_check_latest_same_version_returns_none():
    info = updater.check_latest("1.2.1", fetcher=lambda url, t: release_payload())
    assert info is None


def test_check_latest_network_error_raises_update_error():
    def boom(url, timeout):
        raise OSError("network down")

    with pytest.raises(updater.UpdateError):
        updater.check_latest("1.2.0", fetcher=boom)


def test_check_latest_404_means_no_release():
    import urllib.error

    def not_found(url, timeout):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]

    assert updater.check_latest("1.2.0", fetcher=not_found) is None


# --------------------------------------------------------------------------- #
# 四、下载：落地 / 半包清理（用本地 file:// 模拟，不联网）
# --------------------------------------------------------------------------- #
def test_download_writes_file_and_reports_progress(tmp_path: Path):
    src = tmp_path / "pkg.zip"
    src.write_bytes(b"x" * 500_000)
    seen: list[tuple[int, int]] = []

    out = updater.download(src.as_uri(), tmp_path / "dl",
                           progress=lambda d, t: seen.append((d, t)),
                           filename="TodayMoYu-macOS-v9.zip")
    assert out.name == "TodayMoYu-macOS-v9.zip"
    assert out.stat().st_size == 500_000
    assert seen and seen[-1][0] == 500_000
    assert not list((tmp_path / "dl").glob("*.part")), "残留了半包"


def test_download_failure_cleans_partial(tmp_path: Path):
    with pytest.raises(updater.UpdateError):
        updater.download((tmp_path / "missing.zip").as_uri(), tmp_path / "dl")
    assert not list((tmp_path / "dl").glob("*")), "失败时不应留下文件"


def test_sha256_matches_hashlib(tmp_path: Path):
    import hashlib

    p = tmp_path / "a.bin"
    p.write_bytes(b"moyu" * 1000)
    assert updater.sha256_of(p) == hashlib.sha256(b"moyu" * 1000).hexdigest()


# --------------------------------------------------------------------------- #
# 五、安装指引与配置字段
# --------------------------------------------------------------------------- #
def test_install_hint_per_platform():
    assert "覆盖" in updater.install_hint("win32")
    assert ".app" in updater.install_hint("darwin")
    assert "解压" in updater.install_hint("linux")


def test_update_settings_fields_roundtrip(tmp_path: Path):
    from core import Settings

    s = Settings.from_dict({"auto_check_update": False,
                            "last_update_check": "2026-11-05T13:00:00",
                            "skipped_version": "9.9.9"})
    assert s.auto_check_update is False
    assert s.last_update_check == "2026-11-05T13:00:00"
    assert s.skipped_version == "9.9.9"
    s.save(tmp_path)
    back = Settings.load(tmp_path)
    assert back.auto_check_update is False
    assert back.skipped_version == "9.9.9"


def test_update_fields_default_on_for_old_config(tmp_path: Path):
    """老配置没有这些字段时：默认开启自动检查、版本号为旧配置原样。"""
    (tmp_path / "config.json").write_text(json.dumps({"theme": "mint"}), encoding="utf-8")
    from core import Settings

    s = Settings.load(tmp_path)
    assert s.auto_check_update is True
    assert s.last_update_check == ""
    assert s.skipped_version == ""


# --------------------------------------------------------------------------- #
# 六、24 小时节流
# --------------------------------------------------------------------------- #
def test_needs_check_when_never_checked():
    assert updater.needs_check("") is True


def test_needs_check_respects_interval():
    from datetime import datetime, timedelta

    now = datetime(2026, 11, 5, 13, 0, 0)
    recent = (now - timedelta(hours=2)).isoformat(timespec="seconds")
    old = (now - timedelta(hours=30)).isoformat(timespec="seconds")
    assert updater.needs_check(recent, now) is False
    assert updater.needs_check(old, now) is True


def test_needs_check_tolerates_garbage_and_clock_skew():
    from datetime import datetime, timedelta

    now = datetime(2026, 11, 5, 13, 0, 0)
    assert updater.needs_check("not-a-date", now) is True
    future = (now + timedelta(hours=5)).isoformat(timespec="seconds")
    assert updater.needs_check(future, now) is True   # 时钟回拨也重查一次
