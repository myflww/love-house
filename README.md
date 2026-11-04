<div align="center">

<img src="assets/branding/love-house-icon.png" width="144" alt="爱之屋软件图标" />

# 爱之屋 · Love House

给个人 Agent 的长期记忆之家。

保存对话、整理记忆与人格，在新窗口继续使用同一份存档。

[下载安装](#下载) · [各系统最新版](#各系统最新版) · [使用说明](#开始使用)

</div>

## 下载

| 系统 | 最新版本 | 下载 | 系统要求 |
|---|---|---|---|
| Windows x64 | **0.10.4rc1 · 完整预发布** | [安装版 EXE](https://github.com/myflww/love-house/releases/download/v0.10.4rc1/LoveHouse-Setup-0.10.4rc1-Windows-x64.exe) · [便携版 ZIP](https://github.com/myflww/love-house/releases/download/v0.10.4rc1/LoveHouse-0.10.4rc1-Windows-x64.zip) | Intel / AMD 64 位；目标为 Windows 10 2004（19041）及以上或 Windows 11 |
| macOS | **0.10.4rc1 · 完整预发布** | [下载 ZIP](https://github.com/myflww/love-house/releases/download/v0.10.4rc1/LoveHouse-0.10.4rc1-macOS-arm64.zip) | Apple Silicon（M 系列）；macOS 13.0+ |
| Android | **0.8.0rc2 · 预览版** | [下载 APK](https://github.com/myflww/love-house/releases/download/v0.8.0rc2/LoveHouse-0.8.0rc2-Android.apk) | Android 8.0+；保持系统 WebView 更新 |
| iPhone | **0.8.0rc2 · 主屏幕版** | [打开网页版](https://love-house-mobile-myflww.haixiac34.chatgpt.site) | iOS 15.4+；Safari 打开 → 分享 → 添加到主屏幕 |

0.10.4rc1 为完整预发布，两端分别完成本轮 CI 构建与原生运行检查，具体范围见下方说明。发布资产上传与下载状态以发布页为准；Windows 10 是支持目标，不代表全部系统已实测。

iPhone 使用 PWA 网页应用，无需下载 IPA。目前没有 macOS Intel、Windows ARM64／32 位或 Linux 桌面安装包。

## 各系统最新版

### Windows 0.10.4rc1（完整预发布）

- **记忆与纠正**：改进自然问法、时间线索及原文召回；更正由用户确认，保存后可按原主题重验。
- **一个记忆窗口**：集中查看经历、约定、连接状态与待核对事项；约定完成或取消后保留历史，提供资料与模型采纳分开说明。
- **更简单的操作**：合并显示和添加入口，高级字段按需展开，普通记事默认经历；补齐分页、错误回执及键盘焦点。
- **持续整理**：个人记忆无固定库存上限，普通旧失败任务续排，保留原文、进度和淡忘规则；多个已授权窗口仍严格按库和区域导入、召回。
- **空闲回顾**：默认关闭，在原整理面板中按需启用，使用已有模型与强度生成有证据的提案；反思需明确采纳，策略和模拟不自动生效，效果未验证，不训练模型参数。

保留模型/强度选择、默认最高上下文和输出、星云拖动旋转与 Shift 平移、选中节点才停止自旋，以及启动更新提醒。补充大库基准、分层反馈与长期回归，具体范围见发布说明。

[发布页](https://github.com/myflww/love-house/releases/tag/v0.10.4rc1) · [本版说明与验证范围](docs/ReleaseNotes-0.10.4rc1-Windows.md) · [升级与恢复步骤](docs/WINDOWS-0104-UPDATE.md)

### macOS 0.10.4rc1（完整预发布）

同步本轮共享记忆服务、统一记忆窗口及空闲回顾，继续使用 AppKit / WKWebView 和内置 Python。本轮 arm64 包已在 Apple Silicon CI 编译并运行原生窗口，ZIP 解压后再次通过检查；保留原数据目录及 Keychain helper。未覆盖所有 Mac 系统或真实用户旧版应用升级。

[发布说明与验证范围](docs/ReleaseNotes-0.10.4rc1-macOS.md) · [Mac 升级步骤](docs/MACOS-0104-UPDATE.md)

### Android / iPhone 0.8.0rc2

支持手动记录、检索、多记忆库、标签星图和 JSON 导入导出。也可连接自己的 HTTPS 服务管理 Agent 记忆；各设备的本地存档独立保存，没有自动云同步。手机版尚未同步桌面版的人格学习与新版神经星图。

[手机版安装与使用](docs/手机版安装与使用.md) · [Android 发布说明](https://github.com/myflww/love-house/releases/tag/v0.8.0rc2)

## 开始使用

1. **安装或解压**：Windows 便携版完整解压后打开 `LoveHouse.exe`；macOS 解压后将“爱之屋.app”放入应用程序目录。桌面安装包无需另装 Python 或 Node。
2. **选择记忆库并连接 Agent**：桌面版使用 Harness 向导或通用 MCP 配置；桌面最新版也可用 AstrBot 来源配置。完成一轮真实对话，确认记录已入库；自动存档需要宿主提供轮次结束回调。
3. **按需配置整理模型**：在“记忆整理”中填写模型与 Key、选择模型强度，再开启自动整理。桌面版不设每日调用或字符硬上限，API 按实际用量计费。保存原文、检索和完整导出无需整理 API；可选的空闲回顾默认关闭。

升级前备份完整数据目录。完整安装要求、文件校验、签名状态和验证范围见 [下载与系统支持](docs/下载与系统支持.md)。

[Agent 连接说明](nkb/service/AGENT_CONNECTOR.md) · [WorkBuddy 接入](docs/WORKBUDDY-CONNECTION.md) · [源码与 API](docs/API.md)

作者：[myflww](https://github.com/myflww)。非商业使用，修改与再分发须保留署名、[许可](LICENSE)及 [NOTICE](NOTICE)；第三方组件见 [第三方声明](THIRD_PARTY_NOTICES.md)。
