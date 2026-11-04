<div align="center">

<img src="assets/branding/love-house-icon.png" width="144" alt="爱之屋软件图标" />

# 爱之屋 · Love House

给个人 Agent 的长期记忆之家。

保存原话、整理来源与前后变化，在新窗口继续使用同一份存档。

[下载安装](#下载) · [各系统最新版](#各系统最新版) · [使用说明](#开始使用)

</div>

## 下载

| 系统 | 最新版本 | 下载 | 系统要求 |
|---|---|---|---|
| Windows x64 | **0.10.5rc1 · 完整预发布** | [安装版 EXE](https://github.com/myflww/love-house/releases/download/v0.10.5rc1/LoveHouse-Setup-0.10.5rc1-Windows-x64.exe) · [便携版 ZIP](https://github.com/myflww/love-house/releases/download/v0.10.5rc1/LoveHouse-0.10.5rc1-Windows-x64.zip) | Intel / AMD 64 位；目标为 Windows 10 2004（19041）及以上或 Windows 11 |
| macOS | **0.10.5rc1 · 完整预发布** | [下载 ZIP](https://github.com/myflww/love-house/releases/download/v0.10.5rc1/LoveHouse-0.10.5rc1-macOS-arm64.zip) | Apple Silicon（M 系列）；macOS 13.0+ |
| Android | **0.8.0rc2 · 预览版** | [下载 APK](https://github.com/myflww/love-house/releases/download/v0.8.0rc2/LoveHouse-0.8.0rc2-Android.apk) | Android 8.0+；保持系统 WebView 更新 |
| iPhone | **0.8.0rc2 · 主屏幕版** | [打开网页版](https://love-house-mobile-myflww.haixiac34.chatgpt.site) | iOS 15.4+；Safari 打开 → 分享 → 添加到主屏幕 |

0.10.5rc1 为本轮完整预发布，Windows 安装／升级与 macOS 原生运行检查已完成，验证范围见[发布页](https://github.com/myflww/love-house/releases/tag/v0.10.5rc1)及[本版说明](docs/release-0.10.5rc1.md)。支持目标不代表全部系统已实测。

iPhone 使用 PWA 网页应用，无需下载 IPA。目前没有 macOS Intel、Windows ARM64／32 位或 Linux 桌面安装包。

## 各系统最新版

### Windows 0.10.5rc1（完整预发布）

- **自由形成、忠于原话**：猜想、误解、矛盾和故事设定可整理成有角色与来源的材料，不必逐条裁决真假；重要设定、人格和关系变化继续受保护。
- **看清前后变化**：当前、历史、前后比较三种读取；更正保留旧原话，界面可以查看“原话与后续变化”，明确停用与真正忘记始终生效。
- **实用的空闲整理**：本地维护原文目录和同会话前后文，调用模型 0 次；不再生成反思、策略或模拟提案，旧记录可以查看、拒绝或撤回。
- **更轻的原文读取**：单条读取避免全图复制和重新编码；目录与长文分页，保留完整来源和错误回执。
- **持续整理与清楚的边界**：个人记忆无固定库存上限，普通失败续排，保留逐渐淡忘；多窗口仍按用户连接的库和区域工作。断开连接停止该连接读写，已存记忆需要停用或忘记才退出相应使用。

保留模型/强度选择、默认最高上下文和输出、星云拖动旋转与 Shift 平移、选中节点才停止自旋，以及启动更新提醒。科学借鉴、合成性能条件与验证范围分别说明，不宣称外部记忆整理等于训练模型或人脑记忆。

[发布页](https://github.com/myflww/love-house/releases/tag/v0.10.5rc1) · [本版说明与验证范围](docs/release-0.10.5rc1.md) · [记忆设计与论文依据](docs/memory-0105-design.md)

### macOS 0.10.5rc1（完整预发布）

同步本轮共享记忆服务、历史读取和本地空闲目录，继续使用 AppKit / WKWebView 和内置 Python，保留原数据目录及 Keychain helper。本轮 arm64 包的构建、原生运行与升级验证单独记录，不以 Windows 结果代替 Mac 验收。

[发布说明与验证范围](docs/release-0.10.5rc1.md#测试与平台验证状态) · [上一版 Mac 升级与恢复参考](docs/MACOS-0104-UPDATE.md)

### Android / iPhone 0.8.0rc2

支持手动记录、检索、多记忆库、标签星图和 JSON 导入导出。也可连接自己的 HTTPS 服务管理 Agent 记忆；各设备的本地存档独立保存，没有自动云同步。手机版尚未同步桌面版的人格学习与新版神经星图。

[手机版安装与使用](docs/手机版安装与使用.md) · [Android 发布说明](https://github.com/myflww/love-house/releases/tag/v0.8.0rc2)

## 开始使用

1. **安装或解压**：Windows 便携版完整解压后打开 `LoveHouse.exe`；macOS 解压后将“爱之屋.app”放入应用程序目录。桌面安装包无需另装 Python 或 Node。
2. **选择记忆库并连接 Agent**：桌面版使用 Harness 向导或通用 MCP 配置；桌面最新版也可用 AstrBot 来源配置。完成一轮真实对话，确认记录已入库；自动存档需要宿主提供轮次结束回调。
3. **按需配置整理模型**：在“记忆整理”中填写模型与 Key、选择模型强度，再开启自动整理。桌面版不设每日调用或字符硬上限，API 按实际用量计费。保存原文、检索、完整导出与本地原文目录无需整理 API；可选的空闲目录维护默认关闭。

升级前备份完整数据目录。完整安装要求、文件校验、签名状态和验证范围见 [下载与系统支持](docs/下载与系统支持.md)。

[Agent 连接说明](nkb/service/AGENT_CONNECTOR.md) · [WorkBuddy 接入](docs/WORKBUDDY-CONNECTION.md) · [源码与 API](docs/API.md)

作者：[myflww](https://github.com/myflww)。非商业使用，修改与再分发须保留署名、[许可](LICENSE)及 [NOTICE](NOTICE)；第三方组件见 [第三方声明](THIRD_PARTY_NOTICES.md)。
