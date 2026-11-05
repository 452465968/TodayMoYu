#!/bin/bash
# 今天摸了吗 · 网页预览（macOS 双击本文件即可启动）
# 会启动本地预览服务并自动打开浏览器；关闭终端窗口即停止服务。
cd "$(dirname "$0")" || exit 1
exec python3 server.py --open
