# 更新记录（CHANGELOG）

本文件记录「今天摸了吗」**每一个发布版本**的完整变更，与 git 标签 `vX.Y.Z`、提交说明 `[vX.Y.Z]` 前缀一一对应。
格式与递增规则见 [docs/VERSIONING.md](docs/VERSIONING.md)；版本真值在 `core.py` 的 `APP_VERSION`。
每次更新必须写全：变更目的 / 新增内容 / 修复内容 / 调整内容 / 影响范围 / 已知问题。

**当前版本：`v1.0.0`**

---

## [1.0.0] - 2026-11-05

**对应版本**：v1.0.0　**对应提交**：`[v1.0.0] release(repo): 首次纳入版本管理，建立 GitHub 基线`
**对应标签**：`v1.0.0`

### 变更目的

1. 依据用户提供的 7 秒演示视频，复刻「上班鼓励器」的实时薪资折算能力，并统一更名为「今天摸了吗」，主数据改为**今日混底薪【工资】**与**已摸鱼时长**。
2. 交付可直接运行的 Windows 桌面软件（含桌面小组件、托盘、开机自启），并提供 macOS 上可交互的网页预览用于调试。
3. 解决多轮使用反馈中的功能缺陷（月薪联动、调休、设置窗口尺寸、小组件缩放与透明度）。
4. **建立版本规则与更新记录基线**，使后续每次更新都能按规则递增版本号、逐字段留痕、可追溯。

> 本版本是首次纳入 Git 版本管理的初始基线，因此把建立规则之前的所有迭代一次性汇总在此条目下；
> 从下一版本开始，每个版本单独一条记录。

### 新增内容

**核心与桌面程序**
- `core.py`：基于真实系统时钟的实时折算（定时器只重画、不累加，休眠/卡顿不漂移）；工作区间运算、午休扣除、周末/节假日/调休、`day_kind()`；暂停按区间只扣工作时段；跨零点夜班日期归属；本月累计（含调休休息日满勤补算）；配置/状态原子写入与容错；`widget.txt` / `widget.json` 导出。
- `Settings.sync_salary()`：日薪定义为派生值（`日薪 = 时薪 × 每日有效工时`），`from_dict()` 与 `save()` 均调用，保证月薪变更不残留旧值。
- `Settings.makeup_pairs`：调休配对（休息日 ↔ 补班日）；休息日不计摸鱼时长但按满勤补算，补班日正常实时计薪，状态显示「调休休息中 / 调休补班中」。
- `ui_main.py`：柔光渐变主窗口、两项主数据、倒计时、进账速度、进度条、趣味文案、暂停/继续、重置今日、置顶、收进托盘、日薪展示。
- `ui_settings.py`：三模式薪资、工时与午休、调休配对管理（日期选择 + 列表 + 快捷）、主题、刷新间隔、开机自启；**小组件大小 60–200% 与不透明度 30–100% 双滑块（实时预览 / 取消还原）**；`QScrollArea` + 尺寸把手 + `settings_size` 记忆。
- `ui_widget.py`：无边框半透明桌面贴片，可拖动、缩放、调透明度、置顶、右键菜单（±10% 连续步进 + 档位）、双击打开主窗、位置记忆与屏幕边界 clamp。
- `win32_extra.py`：`HKCU Run` 开机自启、`WS_EX_TOOLWINDOW`、`WorkerW` 贴桌面（`SetParent`）、Win32 全局坐标拖动；非 Windows 自动降级为 no-op。
- `theme.py` / `make_assets.py`：三套柔光渐变主题与样式表、代码绘制的多尺寸 ICO/PNG 图标、绘制层 `set_alpha()`。
- `main.py`：Qt 生命周期、托盘菜单、单实例（`QLocalServer`）、实时刷新、异常兜底、Windows AppUserModelID。

**网页预览（macOS 调试）**
- `web/preview.html`：单文件零依赖预览，时间模拟（任意时刻 / 1×–600× / 快捷跳上班前·视频时刻·午休·下班后·周末）、设置抽屉、调休配对、拖动小组件、调试面板（中间量 / Snapshot JSON / 配置 JSON）、375/768/1440 响应式断点。
- `web/server.py` + `start.command`：真实 `core.py` 对照接口 `POST /api/snapshot`，网页一键逐字段比对 JS 与 Python 结果；`GET /api/ping`、`SelfCheck` 支持。
- `resources/preview_*.png|jpg`：主窗口、设置页、小组件、网页预览、小组件三档缩放对比图。

**交付与构建**
- `build_portable.py`：在 macOS/Linux 上组装 Windows 免安装包（Python 3.11 embeddable + PySide6 6.8.3 win_amd64 wheel + `qwindows.dll` + VC++ 运行库），写好 `python311._pth`、静态校验、打 zip 与 SHA-256；产物 82.3 MB，解压即用。
- `launcher/main.go` + `go.mod` + `rsrc_windows_amd64.syso`：Go 交叉编译的 Windows GUI 启动器（`PE32+ x86-64`、内嵌图标、无控制台闪屏），双击唤起 `runtime\pythonw.exe`。
- `app.spec` / `build.bat` / `run.bat`：Windows 单文件 exe 构建与源码运行入口；`Run.bat` / `Run-Debug.bat` / `SelfCheck.bat` 位于免安装包内。
- `rainmeter/TodayMoYu/TodayMoYu.ini`：可选 Rainmeter 皮肤，主程序自动同步 `widget.txt`。
- `requirements.txt` / `pytest.ini` / `tests/test_core.py`：30 个单元测试（视频参数还原、逐秒增长、午休/周末/节假日/调休、暂停、跨天、跨零点、异常配置、月薪联动、数据导出等）。
- `README.md`：项目概述、功能对照、运行/编译、小组件三种添加方式、薪资联动与调休规则、稳定性说明、常见问题、界面布局审核报告。
- `docs/VERSIONING.md`、`CHANGELOG.md`、`scripts/bump_version.py`：版本规则、发布流程、提交说明规范、版本号同步与一致性校验工具。

### 修复内容

| 现象 | 根因 | 处理 |
| --- | --- | --- |
| 改月薪后日薪不更新，保存/重新打开仍是旧值 | 月薪、日薪、时薪三个字段彼此独立，无派生关系 | `sync_salary()` 在 `from_dict()` / `save()` / 设置页草稿 / 主窗口统一调用；日薪框在月薪/时薪模式只读并实时回填 |
| 设置窗口无法调整大小，保存按钮被挤出屏幕 | 新增调休区后 `minimumSizeHint` 被撑到 500×1089，窗口最小高度锁死，且 `isSizeGripEnabled() = False` | 三个标签页各自 `QScrollArea`、`setMinimumSize(500,460)`、启用尺寸把手、初始 566×690、`settings_size` 记忆；实测 minHint 降至 414×266 |
| 小组件大小与透明度调不动 | `setWindowOpacity()` 与 `WA_TranslucentBackground` 在 Windows 争夺分层窗口机制被平台忽略；缩放时边距/间距/进度条高度为固定像素；设置页没有入口；右键菜单用 `globalPosition()` 且 `exec()` 阻塞 | 透明度改为 `SoftGradient.paintEvent` 绘制层 `p.setOpacity()`；布局四类尺寸按 scale 同步缩放；设置页双滑块实时预览；右键菜单 ±10% 步进 + 非阻塞 `popup()` + 事件兼容分支；背景也设鼠标穿透 |
| 调休只支持手填日期列表，功能不可见 | 仅 `holidays` / `makeup_workdays` 两个文本框 | 新增 `makeup_pairs` 配对管理与状态文案，休息日按满勤补算 |
| 网页打开后数据全是 0 | 顶层调用 `syncSalary()` 时 `fullWorkSeconds` 是尚未初始化的 `const`（TDZ） | 改到启动区调用 |
| 网页设置预览被刷成旧值 | 100ms 刷新循环重复写 `settingsPreview` | 抽屉打开时由 `onSettingsInput()` 独占 |
| 网页与 Python 对照出现伪差异 | JS 用带毫秒的模拟时间，POST 给 Python 的是秒级 ISO | 对照时统一对齐到整秒 |
| 浏览器控制台 favicon 404 | 自动请求 `/favicon.ico` | 内联 SVG data-URI 图标 |
| 工具条「设置」按钮变成整行深色大条 | 全局 `.primary { width:100% }` 污染同名 class | 限定 `.win-body .primary`，工具条改 `.tb-primary` |
| Snapshot JSON 时间显示 UTC | `Date` 先被 `toJSON` 转换，replacer 里 `v instanceof Date` 恒假 | 用普通 function + `this[k] instanceof Date` |
| `QLocalServer` 导入失败 | 误放在 `PySide6.QtCore` | 改从 `PySide6.QtNetwork` 导入 |
| Windows 批处理换行/编码问题 | `.bat` 为 LF、含中文 | 统一 CRLF + 全 ASCII；中文 exe 名放进 UTF-8 的 `app.spec` |
| 设置抽屉保存按钮滚出视口 | 内容变长后按钮在滚动区底部 | `.drawer-actions` 设 `position:sticky; bottom:0` |
| 计算中间量/暂停语义缺陷 | `compute()` 隐式 rollover 抹掉暂停状态 | 改为只读隔离，跨天重置由 UI 显式负责 |

### 调整内容

- **可访问性**：三套主题加深 `muted` / `accent` / `accent2`，最差对比度由 3.24:1 提升到 ≥4.87:1（正文 ≥4.5）；11px → 12px；按钮/单选/复选加 `:focus` 2px outline；状态不单独依赖颜色。
- **响应式**：网页 `min-width:940px` 改为媒体查询纵向堆叠 + JS 等比缩放，375/768/1440 三档 `scrollWidth == innerWidth`。
- **窗口定位**：主窗口与桌面小组件的位置 clamp 到 `availableGeometry()`，换分辨率/放大后不跑出屏幕。
- **配置格式**：新增 `makeup_pairs`、`settings_size`；`daily_salary` 在月薪/时薪模式下变为派生值。**旧 `config.json` 加载时自动同步，无需手工迁移，向后兼容**。
- **交付形式**：新增免安装 zip 与 exe 入口；构建产物（zip / exe）**不纳入 Git**，通过 `build_portable.py` 重建或从 Releases 获取。
- **打包健壮性**：`upx=False`（避免 Qt 插件误报）、`_pth` 显式声明路径、包内源码与项目 SHA-256 逐一校验。

### 影响范围

- **模块**：`core.py`、`theme.py`、`main.py`、`ui_main.py`、`ui_settings.py`、`ui_widget.py`、`win32_extra.py`、`web/*`、`launcher/*`、`build_portable.py`、`app.spec`、`tests/*`、全部文档。
- **配置**：`config.json` 新增 `makeup_pairs`、`settings_size`；`daily_salary` 语义变为派生值（仅影响月薪/时薪模式显示与保存值，折算结果一致）；其余字段与读取逻辑不变。
- **平台与交付**：Windows 10/11 x64 为主交付；macOS/Linux 可运行源码与网页预览；Rainmeter 为可选扩展；Windows 11 小组件板不直接支持 Win32 程序。
- **用户需做的事**：解压免安装包后保持目录结构完整，双击 `今天摸了吗.exe`；或 `pip install -r requirements.txt` 后 `python main.py`。从旧配置升级无需任何操作。
- **不入库内容**：`.venv*`、缓存、`*.log`、`.workbuddy/`、`.codebuddy/`、`data/`、`uploads/`、`.env*`、`*.zip`、`*.exe`、`build/`、`dist/` 等本地/敏感/构建产物。

### 已知问题

- 开发环境为 macOS，**Windows 二进制未实机双击验证**；已做 PE 头、依赖、路径、图标资源、源码哈希一致等静态校验，包内 `SelfCheck.bat` / `Run-Debug.bat` 供 Windows 侧自检。
- exe 是启动器，必须与同目录 `runtime\` 一起解压；真正「单文件、可脱离目录」的 exe 需在 Windows 上执行 `build.bat`（PyInstaller 不支持跨平台产出 Windows 可执行文件）。
- 主窗口固定 `432×706`，低于 768px 屏幕高度会贴边；建议 1080p 及以上使用。
- 网页预览的调试工具条在 375px 下换行成多行；部分调试控件尚未补 `aria-label`。
- Windows 11 左侧小组件板只接受 MSIX 打包的 PWA，当前以桌面贴片 / 贴桌面图层 / Rainmeter 三种方式替代。
- 免安装包约 82 MB（解压约 200 MB），因需随包分发 Python 运行时与 Qt 库。

---

<!-- 后续版本请复制 docs/VERSIONING.md 第五节的模板，插在本分隔线之上；
     版本号、git tag、提交说明前缀三者必须一致。 -->
