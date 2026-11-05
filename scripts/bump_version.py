# -*- coding: utf-8 -*-
"""今天摸了吗 · 版本号同步与一致性校验工具

用法：
    python3 scripts/bump_version.py --check                 # 校验四处版本号与 CHANGELOG 完整性
    python3 scripts/bump_version.py patch --date 2026-11-06 --dry-run
    python3 scripts/bump_version.py patch --date 2026-11-06
    python3 scripts/bump_version.py minor
    python3 scripts/bump_version.py major

规则见 docs/VERSIONING.md。脚本只做版本号同步与 CHANGELOG 草稿插入，
草稿里的 <请填写> 必须由人补全后才能 --check 通过。
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORE = ROOT / "core.py"
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"

REQUIRED_SECTIONS = [
    "变更目的", "新增内容", "修复内容", "调整内容", "影响范围", "已知问题",
]
VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")

DRAFT = """## [{ver}] - {date}

**对应版本**：v{ver}　**对应提交**：`[v{ver}] <type>(<scope>): <请填写一句话摘要>`
**对应标签**：`v{ver}`

### 变更目的
<请填写：为什么做这次改动>

### 新增内容
- <请填写；没有则写「无」>

### 修复内容
- <请填写：现象 → 根因 → 处理；没有则写「无」>

### 调整内容
- <请填写；注明是否向后兼容；没有则写「无」>

### 影响范围
- 模块：<请填写>
- 配置：<请填写新增/变更字段，是否兼容旧 config.json>
- 平台与交付物：<请填写>
- 用户需做的事：<请填写「无」或具体步骤>

### 已知问题
- <请填写「无」或逐条列出>

"""


def read_version_core() -> str:
    text = CORE.read_text(encoding="utf-8")
    m = re.search(r'^APP_VERSION\s*=\s*"(\d+\.\d+\.\d+)"', text, re.M)
    if not m:
        raise RuntimeError("core.py 中找不到 APP_VERSION")
    return m.group(1)


def read_version_readme() -> str:
    text = README.read_text(encoding="utf-8")
    m = re.search(r"当前版本[^\d]*(\d+\.\d+\.\d+)", text)
    if not m:
        raise RuntimeError("README.md 中找不到「当前版本」行")
    return m.group(1)


def read_versions_changelog() -> list[str]:
    text = CHANGELOG.read_text(encoding="utf-8")
    return re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, re.M)


def git_tags() -> list[str]:
    try:
        out = subprocess.check_output(
            ["git", "tag", "--list", "v*", "--sort=-v:refname"],
            cwd=ROOT, stderr=subprocess.DEVNULL, text=True)
        return [line.strip() for line in out.splitlines() if line.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        return []


def latest_changelog_section(ver: str) -> str:
    text = CHANGELOG.read_text(encoding="utf-8")
    m = re.search(rf"^## \[{re.escape(ver)}\].*?(?=^## \[|^---\s*$|\Z)",
                   text, re.M | re.S)
    return m.group(0) if m else ""


def check() -> int:
    errors: list[str] = []
    core_v = read_version_core()
    readme_v = read_version_readme()
    cl_versions = read_versions_changelog()
    if not cl_versions:
        errors.append("CHANGELOG.md 没有任何版本条目")
    cl_v = cl_versions[0] if cl_versions else ""

    print(f"core.APP_VERSION      : {core_v}")
    print(f"README 当前版本        : {readme_v}")
    print(f"CHANGELOG 最新版本     : {cl_v or '(无)'}")
    print(f"CHANGELOG 版本数       : {len(cl_versions)}")
    tags = git_tags()
    print(f"git 标签               : {', '.join(tags[:5]) or '(无)'}")

    if core_v != readme_v:
        errors.append(f"README 版本 {readme_v} != core.py 版本 {core_v}")
    if cl_v != core_v:
        errors.append(f"CHANGELOG 最新版本 {cl_v} != core.py 版本 {core_v}")
    if len(cl_versions) != len(set(cl_versions)):
        errors.append("CHANGELOG 存在重复版本号")

    section = latest_changelog_section(core_v)
    if not section:
        errors.append(f"CHANGELOG 缺少 v{core_v} 条目")
    else:
        for name in REQUIRED_SECTIONS:
            if f"### {name}" not in section:
                errors.append(f"v{core_v} 条目缺少「{name}」")
        if "<请填写" in section:
            errors.append(f"v{core_v} 条目仍有 <请填写> 占位符")
        if f"**对应版本**：v{core_v}" not in section:
            errors.append(f"v{core_v} 条目缺少「对应版本」")
        if f"`v{core_v}`" not in section:
            errors.append(f"v{core_v} 条目缺少「对应标签」")

    # 每个版本标签都必须有 CHANGELOG 条目，反之亦然
    for tag in tags:
        v = tag.lstrip("v")
        if VERSION_RE.match(v) and v not in cl_versions:
            errors.append(f"标签 {tag} 没有对应的 CHANGELOG 条目")
    for v in cl_versions:
        if f"v{v}" not in tags:
            errors.append(f"CHANGELOG 的 v{v} 没有对应的 git 标签（发布后需补打）")

    if errors:
        print("\n校验未通过：")
        for e in errors:
            print("  -", e)
        return 1
    print("\n校验通过：版本号四处一致，CHANGELOG 字段齐全，标签与版本一一对应。")
    return 0


def bump(kind: str, date: str, dry_run: bool) -> int:
    current = read_version_core()
    major, minor, patch = map(int, current.split("."))
    if kind == "major":
        major, minor, patch = major + 1, 0, 0
    elif kind == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    new = f"{major}.{minor}.{patch}"

    if new in read_versions_changelog():
        print(f"错误：CHANGELOG 已存在 v{new} 条目，请先完成该版本发布。")
        return 1
    if not VERSION_RE.match(new):
        print("错误：生成的版本号不合法。")
        return 1

    print(f"版本递增：v{current} -> v{new}（{kind}）  日期：{date}")
    if dry_run:
        print("--dry-run：以下改动不会写入磁盘")
        print(f"  1. core.py          APP_VERSION = \"{new}\"")
        print(f"  2. README.md        当前版本 -> v{new}")
        print(f"  3. CHANGELOG.md     在顶部插入 [{new}] 草稿（含 6 个必填字段）")
        print(f"  4. 建议提交说明     [v{new}] <type>(<scope>): <摘要>")
        print(f"  5. 建议标签         git tag -a v{new} -m \"v{new}: <摘要>\"")
        return 0

    core_text = CORE.read_text(encoding="utf-8")
    core_text = re.sub(r'(^APP_VERSION\s*=\s*)"\d+\.\d+\.\d+"',
                       rf'\g<1>"{new}"', core_text, count=1, flags=re.M)
    CORE.write_text(core_text, encoding="utf-8")

    readme_text = README.read_text(encoding="utf-8")
    readme_text = re.sub(r"(当前版本[^\d]*)\d+\.\d+\.\d+",
                         rf"\g<1>{new}", readme_text, count=1)
    README.write_text(readme_text, encoding="utf-8")

    cl_text = CHANGELOG.read_text(encoding="utf-8")
    cl_text = re.sub(r"(当前版本[^\d]*)\d+\.\d+\.\d+",
                     rf"\g<1>{new}", cl_text, count=1)
    first = re.search(r"^## \[\d+\.\d+\.\d+\]", cl_text, re.M)
    if not first:
        raise RuntimeError("CHANGELOG.md 中没有可插入位置")
    block = DRAFT.format(ver=new, date=date) + "---\n\n"
    cl_text = cl_text[:first.start()] + block + cl_text[first.start():]
    CHANGELOG.write_text(cl_text, encoding="utf-8")

    print(f"已写入：core.py / README.md / CHANGELOG.md")
    print("下一步：补全 CHANGELOG 草稿里的 <请填写>，然后：")
    print(f"  python3 scripts/bump_version.py --check")
    print(f'  git commit -m "[v{new}] <type>(<scope>): <摘要>"')
    print(f'  git tag -a v{new} -m "v{new}: <摘要>"')
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="版本号同步与一致性校验")
    ap.add_argument("kind", nargs="?", choices=["patch", "minor", "major"])
    ap.add_argument("--check", action="store_true", help="只做一致性校验")
    ap.add_argument("--dry-run", action="store_true", help="只打印将做的改动")
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="发布日期 YYYY-MM-DD")
    args = ap.parse_args()

    if args.check:
        return check()
    if not args.kind:
        ap.error("请指定 patch|minor|major，或使用 --check")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", args.date):
        ap.error("--date 格式必须是 YYYY-MM-DD")
    return bump(args.kind, args.date, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
