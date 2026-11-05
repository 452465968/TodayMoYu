# 更新记录（CHANGELOG）

本文件记录「今天摸了吗」**每一个发布版本**的完整变更，与 git 标签 `vX.Y.Z`、提交说明 `[vX.Y.Z]` 前缀一一对应。
格式与递增规则见 [docs/VERSIONING.md](docs/VERSIONING.md)；版本真值在 `core.py` 的 `APP_VERSION`。
每次更新必须写全：变更目的 / 新增内容 / 修复内容 / 调整内容 / 影响范围 / 已知问题。

**当前版本：`v1.4.0`**

---

## [1.4.0] - 2026-11-05

**对应版本**：v1.4.0　**对应提交**：`[v1.4.0] feat(ui): 主界面整窗拖动与滚轮缩放，修复小组件裁切与设置按钮悬浮框残留`
**对应标签**：`v1.4.0`

### 变更目的
用户反馈四项问题：设置按钮点击后残留悬浮框、小组件缩小后数字被遮挡、
主界面缺少便捷的拖动 / 缩放能力、小窗口下内容被裁切。本轮集中修复，
并把「窗口缩小不再裁切」做成结构性保障（滚动区兜底 + 内容自适应），
同时回归验证自动更新链路（v1.3.0 引入，本轮补齐端到端测试）。

### 新增内容
- 主界面支持**按住任意空白区域整窗拖动**（按钮、滚动条仍保持原点击行为），位置自动记忆（ui_main.py）。
- 主界面支持 **Ctrl（macOS 为 ⌘）+ 滚轮整体缩放**：等比改变窗口尺寸，字号 / 间距 / 卡片按同一比例自适应，70%–160% 连续可调，松手 0.6 秒后自动落盘（ui_main.py）。
- 主界面内容放进**透明滚动区**：窗口缩到比内容最小尺寸还小时出现细滚动条，任何元素不再被裁切或遮挡（ui_main.py / theme.py）。
- 新增回归脚本 `scripts/fixes_v140_check.py`（25 项离屏检查）与 `tests/test_v140_fixes.py`（9 项单测）。

### 修复内容
- 设置按钮上的悬浮框不消失 → 根因：模态对话框（设置 / 更新弹窗）盖住按钮时吞掉 Leave 事件，关闭后按钮停在 :hover 高亮 → 处理：打开与关闭对话框后调用 `clear_transient_button_state()` 手动复位悬停 / 按下 / 焦点态并隐藏 tooltip；设置页取色器同理（main.py / ui_main.py / ui_settings.py）。
- 小组件缩小后金额 / 时长数字被遮挡 → 根因：窗口尺寸固定为「基准尺寸 × 缩放」，而 100% 时布局最小高度（220px）已大于窗口高度（190px），缩小后标签被压扁裁切 → 处理：窗口尺寸改为 `max(基准 × 缩放, 布局最小需求)` 自适应，金额位数 / 状态文案变化时同步撑大（ui_widget.py）。
- 清理 `_offer_update` 中「跳过此版本」按钮的重复分支（无行为变化）（main.py）。

### 调整内容
- 主窗口最小尺寸从 340×500 放宽到 300×380（滚动区兜底后小尺寸仍可用）。
- 小组件在 100% 缩放下高度从 190px 自适应到约 220px（修复裁切的自然结果，宽度也会随金额位数 / 状态文案略微变宽）。
- 主界面滚轮行为：不带修饰键 = 滚动内容（仅内容放不下时）；Ctrl/⌘+滚轮 = 缩放。
- 兼容性：config.json 无新增必填字段，旧配置直接可用；`main_size` / `main_pos` / `widget_scale` 等沿用原字段。

### 影响范围
- 模块：ui_main.py（滚动区 / 拖动 / 缩放 / 悬浮框复位）、ui_widget.py（尺寸自适应）、ui_settings.py（取色器复位）、theme.py（滚动区透明样式）、main.py（设置弹窗前后复位、更新弹窗清理）、core.py（版本号）。
- 配置：无新增字段，完全向后兼容。
- 平台与交付物：Windows 免安装 zip 与 macOS .app zip 双端同步；测试 149 项全过（140 → 149）。
- 用户需做的事：无。

### 已知问题
- 极窄窗口下底部「时薪 / 日薪」一行文字会换行（不裁切，属正常换行）。
- 自动更新检查依赖 api.github.com 连通性，网络受限时静默失败，可在设置页手动「检查更新」查看原因。

---


## [1.3.0] - 2026-11-05

**对应版本**：v1.3.0　**对应提交**：`[v1.3.0] fix(macos,core): 修复 macOS 退出闪退与文案误导，新增自动更新`
**对应标签**：`v1.3.0`

### 变更目的
消除 macOS 端实测问题：退出 / 关窗口原生闪退（SIGSEGV）、小目标文案在已赚超过目标后仍误导、午休期间金额与时长冻结被误认为卡死；同时按用户需求新增自动更新（基于 GitHub Releases），并把「收进托盘」等 Windows 语义在 macOS 上本地化。

### 新增内容
- **自动更新**：启动后每天自动检查一次 GitHub Releases（可关），发现新版本弹窗展示版本、更新说明与安装包体积；支持「下载更新 / 跳过此版本 / 稍后」，下载带进度与取消，完成后自动在访达 / 资源管理器中定位文件并给出各平台替换指引；托盘菜单与 macOS 菜单栏均有「检查更新…」，设置页可开关与手动检查。设计上只读网络、失败静默，绝不自动执行外来代码。
- **macOS Dock 恢复**：主窗口隐藏后，点程序坞（Dock）图标或 ⌘Tab 切回会自动恢复窗口。
- 诊断脚本：`scripts/diagnose_live.py`（数据刷新探针）、`scripts/interaction_check.py`（真实 GUI 交互回归）、`scripts/update_gui_check.py`（更新弹窗端到端）。

### 修复内容
- **macOS 退出 / 关窗口闪退（SIGSEGV）** → 根因：在 closeEvent / 槽函数里同步调用 `QApplication.quit()`，macOS 走 `NSApplication terminate:` → `exit()`，PySide6 的 BindingManager 在 C++ 静态析构中销毁 QWidget 包装对象时踩到已失效的信号追踪器 → 处理：`quit_app()` 改为先落盘、拆界面，再通过 `QTimer.singleShot(0, quit)` 异步结束事件循环（实测崩溃消失）。
- **小目标文案误导** → 现象：今日已赚 ¥51.72 已超过目标 ¥50，仍显示「再过 2 小时 53 分，一件 T 恤就摸回来了」→ 根因：`_fun_text` 从 0 起算、完全不看今日已赚 → 处理：改为以「今日已赚」为基准，已达标显示「已经摸回来了，接下来都是净赚」，未达标显示「再摸 X 就到账」。
- **午休冻结被误认为卡死** → 现象：午休时段金额 / 时长完全不动，用户以为程序坏了 → 处理：倒计时改为「午休中 · 计费已暂停，13:30 自动恢复 · 距下班 X」，金额下方同步显示「计费已暂停」（下班前 / 休息日也有对应文案）。
- **更新弹窗丢失体积说明** → 根因：`A if notes else B + C` 运算符优先级把后缀并进了 else 分支 → 处理：拆分为显式拼接。
- **网页预览脚注版本号残留 v1.1.0** → 处理：已随版本递增修正。
- **日历同步疑似卡死风险** → 现象：单次同步 77 分钟未返回期间所有后续同步被吞 → 处理：加 45 秒 watchdog，超时解锁并提示「沿用最近一次成功数据」；过期响应按序号丢弃。
- **「重置今日」误触** → 增加确认对话框；小组件开关状态即时落盘。

### 调整内容
- **「收进托盘」平台化**：Windows 仍为最小化到任务栏（托盘图标可唤回）；macOS 按钮改为「隐藏窗口」，配合 Dock 点击恢复；关闭窗口的通知文案也按平台区分。向后兼容。
- 设置页新增「启动时自动检查更新」开关与版本号 / 「检查更新…」按钮；网页预览同步 `auto_check_update` 等字段（保持配置互通）。

### 影响范围
- 模块：updater.py（新增）、core.py（`_fun_text` / 午休倒计时 / 更新配置字段）、main.py（quit 流程 / Dock 恢复 / 更新流程 / 同步 watchdog）、ui_main.py（进账行分状态文案 / 按钮平台化）、ui_settings.py（更新开关）、win32_extra.py（无变更）、web/preview.html（配置字段与脚注）。
- 配置：新增 `auto_check_update`（默认 true）、`last_update_check`、`skipped_version`；完全兼容旧 config.json（缺失字段按默认值处理）。
- 平台与交付物：Windows 免安装 zip、macOS .app zip，均含自动更新；更新包由 GitHub Releases 分发。
- 用户需做的事：无。升级后首次启动 4 秒会静默检查一次更新（可关闭）。

### 已知问题
- 自动更新只负责「检查 + 下载 + 指引」，替换文件需用户手动完成（免安装版 / .app 无法安全替换正在运行的自身）。
- macOS「贴到桌面」仍为 Windows 专属；2027 年法定节假日安排尚未公布，公布后日历自动补齐。

---

## [1.2.0] - 2026-11-05

**对应版本**：v1.2.0　**对应提交**：`[v1.2.0] feat(ui,platform): 主界面自定义配色、小组件无级外观调节与 macOS 平台适配`
**对应标签**：`v1.2.0`

### 变更目的
让界面配色可以随个人喜好调整而不破坏可读性；把小组件的大小 / 透明度从「档位」升级为无级连续调节；补齐 macOS 平台的系统级支持（开机自启、菜单栏、.app 打包），实现 Windows / macOS 功能对齐。

### 新增内容
- **主界面自定义配色**：设置 → 外观与系统新增「自定义配色」，可分别调整主色 / 副色 / 背景的色相（0–359°，滑块或系统取色器），拖动即时预览；只替换色相、保留明度与饱和度，文字对比度始终达标；「恢复主题默认配色」一键还原。
- **小组件自定义配色**：可跟随主界面，也可单独设置小组件自己的主色 / 副色 / 背景色相。
- **小组件无级缩放**：50%–300% 连续调节（1% 步进），右下角拖拽、滚轮、右键菜单 ±1%/±5% 均可；透明度 15%–100% 连续调节（Shift+滚轮或滑块）；设置页滑块同步为连续取值。
- **macOS 平台适配**：LaunchAgent 开机自启（`~/Library/LaunchAgents/com.shu1nm.todaymoyu.plist`，无需管理员权限）；macOS 系统菜单栏（打开主窗口 ⌘1 / 设置 ⌘, / 暂停 ⌘P / 显示小组件 / 退出 ⌘Q）；`build_macos.py` 一键产出标准 `.app`（多尺寸 icns 图标、Info.plist、静态校验）并打 zip。
- 平台能力探测：`SUPPORTS_AUTOSTART` 统一 Windows / macOS 的开机自启开关行为；「贴到桌面」仍为 Windows 专属，macOS 上自动禁用并给出提示。

### 修复内容
- 自动获取节假日 100% 失败 → 根因：HTTP 请求头 User-Agent 含中文应用名，urllib 按 latin-1 编码请求头时抛 `UnicodeEncodeError` → 处理：改为 ASCII 标识 `TodayMoYu/1.2 (+holiday-cn)`，并新增回归测试锁死。
- macOS 菜单栏从未创建成功 → 根因：误用了不存在的 `QApplication.menuBar()`，异常被静默吞掉 → 处理：改为无父级 `QMenuBar`（macOS 全局菜单栏），并保留引用防止被回收。
- 启动即崩溃（ImportError）→ 根因：`QColorDialog` 误从 `PySide6.QtGui` 导入（实际在 QtWidgets）→ 处理：修正导入来源。
- 自动日历补班日压过用户手动休息日 → 处理：调整 `day_kind` 优先级为「手动配置 > 自动日历 > 周末」。

### 调整内容
- 小组件缩放范围从 60%–200%（5% 档位）放宽为 50%–300% 连续取值；透明度下限从 30% 放宽到 15%。**向后兼容**：旧 config.json 直接读取，取值会被钳制到新范围内。
- 设置对话框支持 `tab` 参数直达指定页（小组件右键「单独设置配色」入口）；取消设置时配色一并回滚。
- 托盘 / 右键菜单样式改为按当前配色实时生成；macOS 菜单动作同时挂到主窗口，保证快捷键在窗口内生效。

### 影响范围
- 模块：core.py（配色字段与 effective_hues）、theme.py（palette / recolor / palette_for）、ui_main.py、ui_widget.py、ui_settings.py、main.py、win32_extra.py、web/preview.html、holiday_calendar.py、build_macos.py（新增）、TodayMoYu-macos.spec（新增）、scripts/qt_offscreen_check.py（新增，26 项离屏 GUI 验证）。
- 配置：新增 `accent_hue` / `accent2_hue` / `bg_hue` / `widget_follow_main` / `widget_accent_hue` / `widget_accent2_hue` / `widget_bg_hue`（默认 -1 = 跟随主题）；`widget_scale` / `widget_opacity` 范围放宽。完全兼容旧 config.json。
- 平台与交付物：Windows 免安装 zip（`今天摸了吗_Windows免安装版.zip`）、macOS 应用包（`今天摸了吗_macOS版.zip`，解压得到 .app）。
- 用户需做的事：macOS 用户首次开启「开机自启」即可；其余为无。

### 已知问题
- macOS「贴到桌面」依赖 Windows WorkerW 图层，不可用（已自动禁用并以「主窗口置顶」替代）。
- 2027 年法定节假日安排尚未公布，日历同步会提示「未公布」，公布后自动补齐。

---

## [1.1.0] - 2026-11-05

**对应版本**：v1.1.0　**对应提交**：`[v1.1.0] feat(ui,calendar): 自定义刷新间隔、主窗口无级缩放与法定节假日自动同步`
**对应标签**：`v1.1.0`

### 变更目的

1. 刷新间隔此前只有固定档位，无法覆盖「想要 0.5 秒高频跳动」或「十分钟才看一眼」的使用习惯，改为**数值 + 时间单位**自由组合并立即生效。
2. 主窗口尺寸此前固定 432×706，小屏贴边、大屏浪费，改为**边缘 / 四角无级拖拽缩放**，任意尺寸下布局保持可用。
3. 调休安排此前只能手动逐个填写日期，维护成本高且容易漏，改为**自动获取国务院办公厅发布的法定节假日与调休安排**（holiday-cn 数据源），断网时自动回退最近一次成功数据。

### 新增内容

- `holiday_calendar.py`（新模块）：中国法定节假日与调休日历的获取 / 解析 / 缓存 / 回退，只用标准库、可脱离 GUI 测试；主源 jsDelivr CDN + 备源 Fastly 镜像 / GitHub Raw，逐个超时重试；允许部分成功（某一年未公布不算失败）；每次成功原子写入 `%APPDATA%/今天摸了吗/holiday_calendar.json`，网络异常沿用该缓存，从未成功过则回退随程序附带的出厂基线。
- `resources/holiday_cn_2026.json`：随程序附带的 2026 年国务院节假日安排出厂基线，首次运行即离线可用。
- `core.py`：`refresh_value` / `refresh_unit`（ms/s/min/h 四种单位，`REFRESH_UNITS` 换算表）、`REFRESH_MIN_MS=50` / `REFRESH_MAX_MS=3600000` 范围校验 `validate_refresh_interval()`、`_derive_refresh_parts()` 把旧 `refresh_ms` 自动换算回自然单位；`calendar_auto` 开关与 `calendar_state`；`day_kind()` 优先级改为 **手动补班/上班 > 手动休息 > 自动补班 > 节假日放假/自动休息 > 周末/工作日**（用户手动配置始终压过数据源）；`calendar_sync_interval_ms()` = max(30 分钟, 刷新间隔 ×100)，上限 24 小时。
- `ui_main.py`（重写）：去掉固定宽高，新增 `ResizeGrip` 八方向命中测试 + 连续拖拽缩放（`MIN_W=380 / MIN_H=560`），字号随宽度比例自适应，位置 clamp 到屏幕可用矩形；尺寸自动记忆。
- `ui_settings.py`：刷新间隔改为「数值（QDoubleSpinBox）+ 单位（下拉）」双控件；新增「自动同步节假日」开关、日历状态标签（最近同步时间 / 覆盖年份 / 放假与调休天数 / 来源 / 同步周期）与「立即同步」按钮。
- `main.py`：`CalendarSync(QThread)` 后台线程 + `synced` 信号驱动日历同步（不阻塞 UI）；托盘菜单新增「同步节假日」；刷新间隔变更后立即重启同步线程。
- `web/preview.html` / `web/server.py`：网页端同步实现三项能力；新增 `GET /api/calendar` 返回日历缓存状态；主窗口改自适应高度。
- `tests/test_calendar_and_refresh.py`（新增 14 项）：单位换算、旧 `refresh_ms` 兼容、范围钳制、日历解析、网络异常回退、三类日期判定、线程信号、User-Agent ASCII 回归等；全套 **59 项测试通过**。

### 修复内容

| 现象 | 根因 | 处理 |
| --- | --- | --- |
| 自动获取节假日 **100% 失败**（`UnicodeEncodeError`） | HTTP 请求头 User-Agent 携带中文应用名，urllib 按 latin-1 编码请求头时抛异常，三个数据源全部失败 | User-Agent 改为固定 ASCII 标识 `TodayMoYu/1.1 (+holiday-cn)`；新增回归测试锁死「请求头必须 ASCII」 |
| 自动日历的补班日压过用户手动设置的休息日 | 自动数据源优先级高于手动配置 | `day_kind()` 优先级重排：手动配置 > 自动日历 > 周末规则，用户意图永远最高 |
| 旧配置 `refresh_ms=500` 被推导成不自然的「0.5 秒」 | 整除优先的单位推导策略对非整数值不友好 | `_derive_refresh_parts()` 对不可整除值回退为毫秒原值（500ms），语义直观 |

### 调整内容

- **刷新调度**：主界面刷新与日历同步检查共用同一个用户周期（日历实际检查频率为刷新间隔 ×100，30 分钟 ~ 24 小时），修改后保存即生效，无需重启。**向后兼容**：旧 `config.json` 的 `refresh_ms` 自动换算成数值 + 单位，无需手工迁移。
- **主窗口**：`432×706` 固定尺寸 → `380×560` 起步的无级缩放；窗口宽高记忆进 `config.json`。**向后兼容**。
- **day_kind 判定**：由「手动配对 > 周末」两级改为「手动 > 自动日历 > 周末」三级；纯周末用户结果不变，**行为向后兼容**。
- **打包**：`build_portable.py` / `app.spec` 加入 `holiday_calendar.py` 与 `resources/holiday_cn_2026.json`；免安装包仍为 82.3 MB。

### 影响范围

- 模块：`core.py`、`main.py`、`ui_main.py`（重写）、`ui_settings.py`、`holiday_calendar.py`（新）、`web/preview.html`、`web/server.py`、`build_portable.py`、`app.spec`、`tests/`、README / CHANGELOG。
- 配置：新增 `refresh_value` / `refresh_unit` / `calendar_auto` / `calendar_state` 与日历字段（`calendar_holidays` / `calendar_makeup_workdays` / `calendar_updated_at` / `calendar_source` / `calendar_years`）、`window_size`；旧 `config.json` 全部字段自动兼容，升级无需任何操作。
- 平台与交付物：Windows 10/11 x64 免安装 zip（v1.1.0 功能已含）；macOS 源码运行与网页预览同步更新；自动同步需联网（断网不影响已有数据与本地判定）。
- 用户需做的事：从 v1.0.0 升级无需任何操作；如需自动节假日同步，在 设置 → 工时 → 打开「自动同步节假日」。

### 已知问题

- 2027 年国务院安排尚未公布，数据源返回空数据，程序按「未公布」处理而非失败，公布后自动补齐。
- Windows 二进制仍未实机双击验证（macOS 开发环境），已做 PE / CRLF / 关键文件静态校验，包内 `SelfCheck.bat` 可自检。
- 主窗口缩放到最小尺寸时趣味文案区会收窄，字号已按宽度比例缩放但超长自定义文案可能截尾。

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
