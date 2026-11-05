# -*- coding: utf-8 -*-
"""构建「今天摸了吗」macOS 应用包（.app + zip），在 macOS 上一键完成。

用法：
    .venv/bin/python build_macos.py                 # 构建并打包 zip
    .venv/bin/python build_macos.py --skip-zip      # 只产出 .app（调试用）
    .venv/bin/python build_macos.py --output /path/to/x.zip

产物：
    dist/今天摸了吗.app
    ../今天摸了吗_macOS版.zip      （默认，与项目目录同级）

说明：
* 用 PyInstaller 的 BUNDLE 生成标准 .app（有 Info.plist、图标、可双击启动）。
* .icns 由 resources/app.png 现生成（sips + iconutil），不额外维护图标文件。
* 打包后做静态校验：可执行文件存在、Info.plist 关键字段正确、资源齐全、PE/ELF/Mach-O 头正确。
"""
from __future__ import annotations

import argparse
import hashlib
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
APP_NAME = "今天摸了吗"
APP = DIST / f"{APP_NAME}.app"
DEFAULT_OUTPUT = ROOT.parent / "今天摸了吗_macOS版.zip"


def make_icns() -> Path:
    """由 app.png 生成多尺寸 .icns（sips + iconutil 均为 macOS 自带）。"""
    target = ROOT / "resources" / "app.icns"
    src = ROOT / "resources" / "app.png"
    if target.is_file() and target.stat().st_mtime >= src.stat().st_mtime:
        print(f"  使用已有图标 {target.name}")
        return target
    iconset = ROOT / "build" / "app.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)
    for size in (16, 32, 64, 128, 256, 512):
        for scale, suffix in ((1, ""), (2, "@2x")):
            px = size * scale
            out = iconset / f"icon_{size}x{size}{suffix}.png"
            subprocess.run(["sips", "-z", str(px), str(px), str(src), "--out", str(out)],
                           check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(target)], check=True)
    print(f"  生成图标 {target.name} ({target.stat().st_size/1024:.1f} KB)")
    return target


def build_app() -> Path:
    print("=== 1/4 生成 .icns 图标 ===")
    make_icns()

    print("=== 2/4 PyInstaller 构建 .app ===")
    if not (ROOT / ".venv" / "bin" / "python").exists():
        raise SystemExit("缺少 .venv：请先 python3 -m venv .venv && .venv/bin/pip install PySide6 pyinstaller")
    cmd = [str(ROOT / ".venv" / "bin" / "python"), "-m", "PyInstaller",
           "--noconfirm", "--clean", str(ROOT / "TodayMoYu-macos.spec")]
    subprocess.run(cmd, cwd=str(ROOT), check=True)

    print("=== 3/4 静态校验 .app ===")
    if not APP.is_dir():
        raise SystemExit(f"构建失败：未生成 {APP}")
    exe = APP / "Contents" / "MacOS" / APP_NAME
    plist = APP / "Contents" / "Info.plist"
    required = [
        exe,
        plist,
        APP / "Contents" / "Resources" / "app.icns",
    ]
    missing = [str(p.relative_to(APP)) for p in required if not p.exists()]
    if missing:
        raise SystemExit("缺少关键文件：" + ", ".join(missing))
    if exe.read_bytes()[:4] not in (b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe",
                                    b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xcf"):
        raise SystemExit("主可执行文件不是有效的 Mach-O")
    with plist.open("rb") as fh:
        info = plistlib.load(fh)
    for key in ("CFBundleIdentifier", "CFBundleExecutable", "CFBundleName"):
        if not info.get(key):
            raise SystemExit(f"Info.plist 缺少 {key}")
    # 内置资源（节假日基线）必须随包
    frozen_res = APP / "Contents" / "Resources" / "resources" / "holiday_cn_2026.json"
    if not frozen_res.exists():
        raise SystemExit("打包结果缺少 resources/holiday_cn_2026.json")
    total_mb = sum(p.stat().st_size for p in APP.rglob("*") if p.is_file()) / 1024 / 1024
    print(f"  校验通过：{info['CFBundleIdentifier']} · {info['CFBundleName']} · {total_mb:.1f} MB")
    return APP


def zip_app(output: Path) -> Path:
    print("=== 4/4 打包 zip（ditto，保留符号链接与权限） ===")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent",
                    str(APP), str(output)], check=True)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    (output.with_suffix(".zip.sha256")).write_text(f"{digest}  {output.name}\n", encoding="utf-8")
    print(f"  产物: {output}  ({output.stat().st_size/1024/1024:.1f} MB)")
    print(f"  SHA256: {digest}")
    return output


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--skip-zip", action="store_true")
    args = ap.parse_args()
    if sys.platform != "darwin":
        raise SystemExit("build_macos.py 只能在 macOS 上运行")
    build_app()
    if not args.skip_zip:
        zip_app(args.output.resolve())
    return 0


if __name__ == "__main__":
    sys.exit(main())
