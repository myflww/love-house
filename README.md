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
| Windows x64 | **0.10.3rc1 · 完整发行包** | [安装版 EXE](https://github.com/myflww/love-house/releases/download/v0.10.3rc1/LoveHouse-Setup-0.10.3rc1-Windows-x64.exe) · [便携版 ZIP](https://github.com/myflww/love-house/releases/download/v0.10.3rc1/LoveHouse-0.10.3rc1-Windows-x64.zip) | Intel / AMD 64 位；Windows 10 2004（19041）及以上或 Windows 11 |
| macOS | **0.10.1 · 稳定版** | [下载 ZIP](https://github.com/myflww/love-house/releases/download/v0.10.1/LoveHouse-0.10.1-macOS-arm64.zip) | Apple Silicon（M 系列）；macOS 13.0+ |
| Android | **0.8.0rc2 · 预览版** | [下载 APK](https://github.com/myflww/love-house/releases/download/v0.8.0rc2/LoveHouse-0.8.0rc2-Android.apk) | Android 8.0+；保持系统 WebView 更新 |
| iPhone | **0.8.0rc2 · 主屏幕版** | [打开网页版](https://love-house-mobile-myflww.haixiac34.chatgpt.site) | iOS 15.4+；Safari 打开 → 分享 → 添加到主屏幕 |

Windows 0.10.3rc1 提供完整安装版和便携版，本轮验证范围见发布说明。iPhone 使用 PWA 网页应用，无需下载 IPA。目前没有 macOS Intel、Windows ARM64／32 位或 Linux 桌面安装包。

## 各系统最新版

### Windows 0.10.3rc1

- **整理继续完成**：移除每日调用、字符及累计100条候选的硬上限；普通失败任务持续退避重试，旧失败任务重新排队，保留原文和进度。
- **多窗口与边界**：多个明确连接的窗口可同时导入与召回；每条连接固定所属记忆库和获准窗口，重复交付去重。
- **模型与强度**：读取可用模型并选择推理强度；上下文和输出默认模型最高，未知能力由服务决定，也可手动设置 token 数。
- **星云操作**：普通拖动旋转、Shift 平移；悬停和空白点击继续自旋，拖动松开恢复，选中具体节点或明确暂停时停止。
- **版本提醒**：自动检查开启时，每次打开检查当前平台的新版本，有更新时弹窗展示说明与可信下载入口。

保留 AstrBot 快速配置、整理 API 状态、人格学习、独立记忆和动态／平面两种星图。升级前备份完整数据目录。

[发布页](https://github.com/myflww/love-house/releases/tag/v0.10.3rc1) · [本版说明与验证范围](docs/ReleaseNotes-0.10.3rc1-Windows.md) · [升级与恢复步骤](docs/WINDOWS-0103-UPDATE.md)

### macOS 0.10.1

- **独立记忆**：普通入库不按相似文字、时间或标签强行连线；没有关联的记忆也能保存和召回。
- **人格与星图**：从有原话依据的记忆中整理人格，保留固定设定；支持动态星云、平面引力图和黑白画布。

[发布说明](https://github.com/myflww/love-house/releases/tag/v0.10.1)

### Android / iPhone 0.8.0rc2

支持手动记录、检索、多记忆库、标签星图和 JSON 导入导出。也可连接自己的 HTTPS 服务管理 Agent 记忆；各设备的本地存档独立保存，没有自动云同步。手机版尚未同步桌面版的人格学习与新版神经星图。

[手机版安装与使用](docs/手机版安装与使用.md) · [Android 发布说明](https://github.com/myflww/love-house/releases/tag/v0.8.0rc2)

## 开始使用

1. **安装或解压**：Windows 便携版完整解压后打开 `LoveHouse.exe`；macOS 解压后将“爱之屋.app”放入应用程序目录。桌面安装包无需另装 Python 或 Node。
2. **选择记忆库并连接 Agent**：桌面版使用 Harness 向导或通用 MCP 配置；Windows 最新版也可用 AstrBot 来源配置。完成一轮真实对话，确认记录已入库；自动存档需要宿主提供轮次结束回调。
3. **按需配置整理模型**：在“记忆整理”中填写模型与 Key、选择模型强度，再开启自动整理。Windows 0.10.3rc1 不设每日调用或字符硬上限，API 按实际用量计费。保存原文、检索和完整导出无需整理 API。

升级前备份完整数据目录。完整安装要求、文件校验、签名状态和验证范围见 [下载与系统支持](docs/下载与系统支持.md)。

[Agent 连接说明](nkb/service/AGENT_CONNECTOR.md) · [WorkBuddy 接入](docs/WORKBUDDY-CONNECTION.md) · [源码与 API](docs/API.md)

作者：[myflww](https://github.com/myflww)。非商业使用，修改与再分发须保留署名、[许可](LICENSE)及 [NOTICE](NOTICE)；第三方组件见 [第三方声明](THIRD_PARTY_NOTICES.md)。
