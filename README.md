<div align="center">

<img src="assets/branding/love-house-icon.png" width="144" alt="爱之屋软件图标" />

# 爱之屋 · Love House

给个人 Agent 的长期记忆之家。

保存原话、整理来源与前后变化，在新窗口继续使用同一份存档。

[下载安装](#下载) · [各系统最新版](#各系统最新版) · [使用说明](#开始使用)

</div>

## 下载

[推荐下载 · 0.10.7rc1](https://github.com/myflww/love-house/releases/latest)

| 系统 | 最新版本 | 下载 | 系统要求 |
|---|---|---|---|
| Windows x64 | **0.10.7rc1 · 当前推荐版** | [安装版 EXE](https://github.com/myflww/love-house/releases/download/v0.10.7rc1/LoveHouse-Setup-0.10.7rc1-Windows-x64.exe) · [便携版 ZIP](https://github.com/myflww/love-house/releases/download/v0.10.7rc1/LoveHouse-0.10.7rc1-Windows-x64.zip) | Intel / AMD 64 位；目标为 Windows 10 2004（19041）及以上或 Windows 11 |
| macOS | **0.10.7rc1 · 当前推荐版** | [下载 ZIP](https://github.com/myflww/love-house/releases/download/v0.10.7rc1/LoveHouse-0.10.7rc1-macOS-arm64.zip) | Apple Silicon（M 系列）；macOS 13.0+ |
| Android | **0.10.6rc1 · 原签名预览版** | [下载 APK](https://github.com/myflww/love-house/releases/download/v0.10.6rc1/LoveHouse-0.10.6rc1-Android.apk) · [校验文件](https://github.com/myflww/love-house/releases/download/v0.10.6rc1/Android-SHA256SUMS.txt) | 64 位 ARM / x86；Android 8.0+，完整界面需 WebView 109+，建议最新 |

0.10.7rc1 为当前推荐下载版本，本轮整合 DSH 新接口兼容、已有适配器副本升级与更新通道持续检查，安装／升级及原生运行验收状态与范围见[发布页](https://github.com/myflww/love-house/releases/tag/v0.10.7rc1)及[本版说明](docs/release-0.10.7rc1.md)。支持目标不代表全部系统已实测。

目前没有 macOS Intel、Windows ARM64／32 位或 Linux 桌面安装包。项目已停止提供 iPhone 版；旧主屏幕版用户请先[导出原有记忆](docs/手机版安装与使用.md#旧-iphone-版的记忆迁移)，再迁移到 Android 或桌面版。

## 各系统最新版

### Windows 0.10.7rc1（当前推荐版）

- **DSH 更新兼容**：按实际接口能力连接新版，升级时刷新已归属的适配器副本；保留窗口绑定、暂停和待发送记录。已运行的 DSH 需重新加载插件一次。

- **围绕实际话题召回**：澄清与问句套话本身不作为相关依据；无对象时允许空召回，显式查原话仍可找，不用旧窗口猜当前所指。
- **自由形成、忠于原话**：猜想、误解、矛盾和故事设定可整理成有角色与来源的材料，不必逐条裁决真假；重要设定、人格和关系变化继续受保护。
- **看清前后变化**：当前、历史、前后比较三种读取；更正保留旧原话，界面可以查看“原话与后续变化”，明确停用与真正忘记始终生效。
- **实用的空闲整理**：本地维护原文目录和同会话前后文，调用模型 0 次；不再生成反思、策略或模拟提案，旧记录可以查看、拒绝或撤回。
- **更轻的原文读取**：单条读取避免全图复制和重新编码；目录与长文分页，保留完整来源和错误回执。
- **持续整理与清楚的边界**：个人记忆无固定库存上限，普通失败续排，保留逐渐淡忘；多窗口仍按用户连接的库和区域工作。断开连接停止该连接读写，已存记忆需要停用或忘记才退出相应使用。

保留模型/强度选择、默认最高上下文和输出、星云拖动旋转与 Shift 平移、选中节点才停止自旋，以及启动更新提醒。科学借鉴、合成性能条件与验证范围分别说明，不宣称外部记忆整理等于训练模型或人脑记忆。

[发布页](https://github.com/myflww/love-house/releases/tag/v0.10.7rc1) · [本版说明与验证范围](docs/release-0.10.7rc1.md) · [记忆设计与论文依据](docs/memory-0105-design.md)

### macOS 0.10.7rc1（当前推荐版）

同步本轮 DSH 兼容、已有适配器刷新和共享记忆服务，继续使用 AppKit / WKWebView 和内置 Python，保留原数据目录及 Keychain helper。本轮 arm64 包的构建、原生运行与升级验证单独记录，不以 Windows 结果代替 Mac 验收。

[发布说明与验证范围](docs/release-0.10.7rc1.md#验证与下载) · [上一版 Mac 升级与恢复参考](docs/MACOS-0104-UPDATE.md)

### Android

0.10.7rc1 已同步源码与构建，原签名在另一台设备，由该设备按[签名发布交接书](docs/ANDROID-0107-HANDOFF.md)完成签名、覆盖升级验收后再追加 APK。当前可安装版仍为下列 0.10.6rc1。

**Android 0.10.6rc1 原签名 APK 已发布，可从 0.8.0rc2 直接覆盖升级。** 升级前逐库导出 JSON，不要先卸载或清除应用数据。原发行签名已核对；公开旧版 0.8.0rc2 → 本版的双库覆盖升级及进程重启通过。Android 16 / API36 的完整引擎 11 项测试及额外迁移、幂等、实际文件导出恢复、库隔离与凭据重启验收通过；Android 9 / API28 的旧内核仅通过旧入口、内核更新提示 7 项及旧库升级保留，不代表完整引擎可在该旧内核运行。完整界面需要 WebView 109+。以上为独立模拟器与合成数据，未调用付费模型，实体手机尚待验证。

新版在手机内置与桌面相同版本的记忆引擎和完整界面，接入记忆整理、人格、召回、原文与更正历史、独立库及神经星图。原来的离线库保留，通过“打开完整记忆”和“迁移当前旧库”明确选择使用；迁移不会删除旧库。模型整理需要为目标库配置 API，按实际用量计费。

手机本机服务仅监听 `127.0.0.1`，云服务器或电脑上的 Agent 应连接其所在设备的爱之屋服务，再用手机管理该 HTTPS 服务。关闭界面后不保证持续接收，系统省电或结束应用进程可能停止接收；不承诺全天后台采集，也不会读取其他 App。

已发布的 0.8.0rc2 继续支持手动记录、检索、多库、标签星图和 JSON 导入导出；这些旧版下载不包含新的本机完整引擎。设备间的本地存档各自保存，没有自动云同步。

[Android 下载与升级说明](docs/ANDROID-0106-UPDATE.md) · [手机版安装与使用](docs/手机版安装与使用.md) · [公开验收报告](https://github.com/myflww/love-house/releases/download/v0.10.6rc1/Android-0106-verification.json)

## 开始使用

1. **安装或解压**：Windows 便携版完整解压后打开 `LoveHouse.exe`；macOS 解压后将“爱之屋.app”放入应用程序目录。桌面安装包无需另装 Python 或 Node。
2. **选择记忆库并连接 Agent**：桌面版使用 Harness 向导或通用 MCP 配置；桌面最新版也可用 AstrBot 来源配置。完成一轮真实对话，确认记录已入库；自动存档需要宿主提供轮次结束回调。
3. **按需配置整理模型**：在“记忆整理”中填写模型与 Key、选择模型强度，再开启自动整理。桌面版不设每日调用或字符硬上限，API 按实际用量计费。保存原文、检索、完整导出与本地原文目录无需整理 API；可选的空闲目录维护默认关闭。

升级前备份完整数据目录。完整安装要求、文件校验、签名状态和验证范围见 [下载与系统支持](docs/下载与系统支持.md)。

[Agent 连接说明](nkb/service/AGENT_CONNECTOR.md) · [WorkBuddy 接入](docs/WORKBUDDY-CONNECTION.md) · [源码与 API](docs/API.md)

作者：[myflww](https://github.com/myflww)。非商业使用，修改与再分发须保留署名、[许可](LICENSE)及 [NOTICE](NOTICE)；第三方组件见 [第三方声明](THIRD_PARTY_NOTICES.md)。
