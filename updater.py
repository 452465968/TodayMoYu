# -*- coding: utf-8 -*-
"""今天摸了吗 · 自动更新（基于 GitHub Releases）

设计原则：
* **只读网络、失败静默**：检查更新出错绝不打扰用户，也绝不影响主功能。
* **不自动执行外来代码**：只下载官方 Release 里的 zip，下载后引导用户替换，
  不做静默自替换（免安装版 / .app 都无法安全替换正在运行的自身）。
* **可测试**：所有网络访问都可通过 `fetcher` 注入，单测无需联网。
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

REPO = "452465968/TodayMoYu"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
# 纯 ASCII：HTTP 头只能是 latin-1，带中文会抛 UnicodeEncodeError
USER_AGENT = "TodayMoYu-Updater/1.0 (+github)"
CHECK_INTERVAL_HOURS = 24


class UpdateError(Exception):
    """检查 / 下载更新失败（调用方通常只记录日志，不弹窗）。"""


@dataclass
class UpdateInfo:
    version: str                     # 例如 "1.2.1"
    tag: str                         # 例如 "v1.2.1"
    notes: str = ""
    page_url: str = RELEASES_PAGE
    asset_name: str = ""
    asset_url: str = ""
    asset_size: int = 0
    published_at: str = ""

    @property
    def asset_mb(self) -> float:
        return self.asset_size / 1024 / 1024


# --------------------------------------------------------------------------- #
# 版本比较
# --------------------------------------------------------------------------- #
def parse_version(text: str) -> tuple[int, ...]:
    """把 "v1.2.3" / "1.2.3-beta" / "1.2" 解析成可比较的整数元组。

    非数字段忽略；完全无法解析时返回空元组（视为 0）。
    """
    if not text:
        return ()
    m = re.findall(r"\d+", str(text))
    return tuple(int(x) for x in m[:4]) if m else ()


def _norm(v: tuple[int, ...], n: int = 4) -> tuple[int, ...]:
    return tuple(list(v) + [0] * (n - len(v)))[:n]


def is_newer(current: str, latest: str) -> bool:
    """latest 是否比 current 新。"""
    return _norm(parse_version(latest)) > _norm(parse_version(current))


# --------------------------------------------------------------------------- #
# Release 解析
# --------------------------------------------------------------------------- #
def _pick_asset(assets: list[dict[str, Any]], platform: str) -> dict[str, Any] | None:
    """按平台挑选安装包；找不到任何一个 zip 时返回 None。

    约定命名：TodayMoYu-Windows-Portable-vX.Y.Z.zip / TodayMoYu-macOS-vX.Y.Z.zip
    """
    want = "windows" if platform.startswith("win") else "macos"
    zips = [a for a in assets
            if str(a.get("name", "")).lower().endswith(".zip")
            and str(a.get("browser_download_url", ""))]
    for a in zips:
        name = str(a["name"]).lower()
        if want in name or ("mac" in name and want == "macos"):
            return a
    # 兜底：只有一个 zip 时就直接用它（避免命名变化导致完全不可用）
    return zips[0] if len(zips) == 1 else None


def parse_release(payload: dict[str, Any], platform: str | None = None
                  ) -> UpdateInfo | None:
    """把 GitHub Release JSON 转成 UpdateInfo；不是正式版则返回 None。"""
    if not isinstance(payload, dict):
        return None
    tag = str(payload.get("tag_name") or "").strip()
    if not tag or payload.get("draft") or payload.get("prerelease"):
        return None
    version = ".".join(str(x) for x in parse_version(tag))
    if not version:
        return None
    asset = _pick_asset(payload.get("assets") or [], platform or sys.platform)
    return UpdateInfo(
        version=version,
        tag=tag,
        notes=str(payload.get("body") or "")[:4000],
        page_url=str(payload.get("html_url") or RELEASES_PAGE),
        asset_name=str(asset.get("name") or "") if asset else "",
        asset_url=str(asset.get("browser_download_url") or "") if asset else "",
        asset_size=int(asset.get("size") or 0) if asset else 0,
        published_at=str(payload.get("published_at") or ""),
    )


# --------------------------------------------------------------------------- #
# 网络
# --------------------------------------------------------------------------- #
def _default_fetch(url: str, timeout: float) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def check_latest(current: str, *, platform: str | None = None, timeout: float = 8.0,
                 fetcher: Callable[[str, float], dict[str, Any]] | None = None
                 ) -> UpdateInfo | None:
    """查询最新 Release。返回 None 表示已是最新或没有可用资产。

    网络异常抛 UpdateError，由调用方决定是否提示。
    """
    fetch = fetcher or _default_fetch
    try:
        payload = fetch(API_LATEST, timeout)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:            # 还没有发布任何 Release
            return None
        raise UpdateError(f"HTTP {exc.code}") from exc
    except Exception as exc:           # noqa: BLE001
        raise UpdateError(str(exc)) from exc

    info = parse_release(payload, platform)
    if info is None:
        return None
    return info if is_newer(current, info.version) else None


def download(url: str, dest_dir: Path, *, timeout: float = 30.0,
             progress: Callable[[int, int], None] | None = None,
             filename: str | None = None) -> Path:
    """下载安装包到 dest_dir，返回本地路径。附带 .part 临时文件，避免半包。"""
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = filename or url.rsplit("/", 1)[-1].split("?")[0] or "TodayMoYu-update.zip"
    target = dest_dir / name
    tmp = target.with_suffix(target.suffix + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            total = int(resp.headers.get("Content-Length") or 0)
            done = 0
            with tmp.open("wb") as fh:
                while True:
                    chunk = resp.read(262_144)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        tmp.replace(target)
    except Exception as exc:           # noqa: BLE001
        tmp.unlink(missing_ok=True)
        raise UpdateError(f"下载失败：{exc}") from exc
    return target


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# --------------------------------------------------------------------------- #
# 本地辅助：下载目录、打开文件夹
# --------------------------------------------------------------------------- #
def reveal(path: Path) -> None:
    """在文件管理器里选中该文件；失败则忽略（不是关键路径）。"""
    import subprocess

    path = Path(path)
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", str(path)], close_fds=True)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)], close_fds=True)
        else:
            subprocess.Popen(["xdg-open", str(path.parent)], close_fds=True)
    except Exception:                  # noqa: BLE001
        pass


def install_hint(platform: str | None = None) -> str:
    """下载完成后的安装指引（各平台动作不同）。"""
    p = platform or sys.platform
    if p.startswith("win"):
        return ("已下载新版本压缩包。请退出「今天摸了吗」，解压后覆盖原文件夹里的文件"
                "（config.json 在 AppData 里，不会被覆盖）。")
    if p == "darwin":
        return ("已下载新版本。解压后把「今天摸了吗.app」拖到「应用程序」文件夹覆盖旧版；"
                "配置与数据保存在 ~/Library/Application Support 里，不会丢。")
    return "已下载新版本压缩包，请解压后替换现有程序。"


def cleanup_dir(path: Path) -> None:
    shutil.rmtree(path, ignore_errors=True)


def needs_check(last_iso: str, now=None, interval_hours: float = CHECK_INTERVAL_HOURS) -> bool:
    """距上次检查是否已超过 interval_hours（空/非法时间视为需要检查）。"""
    from datetime import datetime as _dt

    if not last_iso:
        return True
    try:
        last = _dt.fromisoformat(str(last_iso))
    except (ValueError, TypeError):
        return True
    now = now or _dt.now()
    try:
        delta = (now - last).total_seconds()
    except TypeError:                  # 一个是 naive 一个是 aware
        return True
    if delta < 0:                      # 时钟回拨：当作需要检查
        return True
    return delta >= interval_hours * 3600
