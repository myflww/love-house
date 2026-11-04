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

Mac 应用来自[本轮 Apple Silicon 完整构建与验证](https://github.com/myflww/love-house/actions/runs/41745570866)，实际受测源码为 `8d097a6a146ecff584906a18047e97b03ea05e32`。原生 AppKit / WKWebView 窗口和 Keychain helper 均已在 arm64 runner 编译；应用完成 ad-hoc 签名及 `codesign --verify --deep --strict` 校验，ZIP 解压后的独立应用再次通过签名及原生运行检查。

`build.json`、`native.json` 和 `zip-native.json` 均为完成且通过。覆盖随包运行时、合成凭据的保存/读取/删除与连接隔离、后端及原生窗口重启、MCP、真实宿主 Hook 和单窗口绑定、历史角色导入、固定连接库边界、模型设置以及启动更新弹窗。测试仅使用新建合成资料和 FAKE 凭据，没有读取真实用户库或真实 API Key，没有调用付费模型；两次原生运行均停止后端并清理临时资料。

原生窗口先检查 runner 的真实“减少动态效果”偏好，再在隔离自检中只模拟该项媒体查询的两种状态，分别核对悬停继续旋转、实际节点按钮选择后停止、取消选择恢复，以及减少动态效果时保持停止。原生 `matchMedia` 在 `finally` 恢复，产品和系统偏好保持原状；报告明确记录 `actual_host_reduce_motion` 与 `tested_synthetic_motion_states`。

最终发行源码相对上述 Mac 构建源码仅追加验证测试、发布文档与源码清单，Mac 运行和打包输入保持一致。受测源码、最终发行源码、原始三份报告和文件摘要见随版 [macOS-0103-verification.json](https://github.com/myflww/love-house/releases/download/v0.10.3rc1/macOS-0103-verification.json) 及 [macOS-SHA256SUMS.txt](https://github.com/myflww/love-house/releases/download/v0.10.3rc1/macOS-SHA256SUMS.txt)；发布后的匿名公开下载与 SHA256 复核结果见 [Public-download-verification.json](https://github.com/myflww/love-house/releases/download/v0.10.3rc1/Public-download-verification.json)。

操作系统首次打开限制、真实客户端长期运行和用户已有 Keychain 权限仍以对应机器上的系统行为为准。
