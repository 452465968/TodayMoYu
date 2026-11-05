# -*- coding: utf-8 -*-
"""生成 Windows 图标资源：resources/app.png + resources/app.ico

图标由代码绘制（珊瑚色渐变 + 「摸」字），不依赖图片素材。
如需换图标，改 main.make_icon() 后重新运行：
    python make_assets.py
"""
from __future__ import annotations

import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice
from PySide6.QtWidgets import QApplication

from main import make_icon

HERE = Path(__file__).resolve().parent
RES = HERE / "resources"
SIZES = [16, 24, 32, 48, 64, 128, 256]


def ico_bytes(images: list[tuple[int, bytes]]) -> bytes:
    """PNG-in-ICO（Windows Vista 及以上支持），多尺寸打包。"""
    count = len(images)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    entries = bytearray()
    body = bytearray()
    for size, png in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32,
                               len(png), offset)
        body += png
        offset += len(png)
    return header + bytes(entries) + bytes(body)


def main() -> None:
    app = QApplication([])
    RES.mkdir(parents=True, exist_ok=True)
    images: list[tuple[int, bytes]] = []
    for size in SIZES:
        pixmap = make_icon(size).pixmap(size, size)
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        pixmap.save(buf, "PNG")
        data = bytes(QByteArray(buf.data()))
        buf.close()
        images.append((size, data))
    (RES / "app.png").write_bytes(images[-1][1])
    (RES / "app.ico").write_bytes(ico_bytes(images))
    print(f"已生成 {RES / 'app.ico'}（{len(images)} 种尺寸）与 {RES / 'app.png'}")


if __name__ == "__main__":
    main()
