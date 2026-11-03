# 爱之屋 0.10.3rc1 · macOS Apple Silicon 完整更新

本版为 Apple Silicon（M 系列）Mac 提供完整的“爱之屋.app”，支持 macOS 13.0+。与同版本 Windows 共用记忆服务及页面代码，保留原生 AppKit / WKWebView 窗口、文件对话框和 Keychain helper。

## 本轮更新

- 取消每日整理调用、字符及累计100条候选的硬上限。普通任务持续退避重试，旧失败与中断任务恢复；原文、进度、逐字证据和遗忘规则继续生效。
- 多个明确连接的窗口可并发导入、召回；每个连接的记忆库和窗口授权独立校验。
- 可读取模型列表并选择推理强度，上下文和输出默认使用模型公布的最高能力；未知服务由服务决定。超窗或输出截断后自动缩片，不丢弃未处理的原文。
- 修复手势释放丢失后的平移残留。普通拖动旋转、Shift平移；悬停及空白点击继续自旋，选中节点或明确暂停时停止。
- 启动检查当前平台的新版本，并在发现更新时弹窗。保留自动检查开关和发布通道选择。
- AstrBot 导出与随包插件统一为0.3.0；配置仍需要用户确认来源和获准窗口。

## 下载与升级

[LoveHouse-0.10.3rc1-macOS-arm64.zip](https://github.com/myflww/love-house/releases/download/v0.10.3rc1/LoveHouse-0.10.3rc1-macOS-arm64.zip)

完整解压后将“爱之屋.app”放入应用程序目录。升级前退出旧程序，并备份 `~/Library/Application Support/NeuralKnowledge`；本版沿用原 bundle ID 和数据目录。详细步骤见 [Mac 升级说明](MACOS-0103-UPDATE.md)。

此包沿用项目的 ad-hoc 签名和完整性验证，未使用 Developer ID 签名或 Apple 公证。首次打开可能需要按 macOS 的系统提示核对来源并允许打开；本轮不承诺 Intel Mac 兼容。

## 验证记录

macOS 构建使用独立的 Apple Silicon runner，编译原生窗口与 Keychain helper，验证签名、应用内置运行时、后端、MCP、窗口绑定及 WKWebView。测试仅使用隔离合成资料和模拟模型，不使用真实用户记忆或付费模型。

<!-- RELEASE-VERIFICATION: 发布前补入受测源码、macOS workflow、原生窗口结果和公开下载哈希复核；Windows检查不作为Mac证据。 -->

操作系统首次打开限制、真实客户端长期运行和用户已有 Keychain 权限仍以对应机器上的系统行为为准。
