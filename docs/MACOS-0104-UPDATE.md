# macOS 0.10.4rc1 更新与恢复说明

本版为 Apple Silicon（M 系列）、macOS 13.0+ 提供完整预发布，内置 Python 与本地页面资源。本轮由真实 Apple Silicon CI 独立完成原生构建、签名校验与运行；资产上传和下载状态以发布页为准。

## 升级与数据保留

1. 退出旧版并停止写入，备份完整 `~/Library/Application Support/NeuralKnowledge`。
2. 从 [本版发布页](https://github.com/myflww/love-house/releases/tag/v0.10.4rc1) 下载 `LoveHouse-0.10.4rc1-macOS-arm64.zip`，按 `macOS-SHA256SUMS.txt` 核对相同文件名的 SHA256。
3. 完整解压，将“爱之屋.app”放入应用程序目录，不要放进记忆数据目录。
4. 打开后确认原记忆库、窗口连接、人格/学习开关、整理模型及 Keychain 状态。原文保存无需整理 Key，普通旧失败只在来源有效、已启用且服务可用时继续处理。
5. 按 macOS 系统提示核对来源。应用使用 ad-hoc 签名，未提供 Developer ID 签名或 Apple 公证。

沿用 `local.neural-knowledge.atlas` bundle ID 和 `NeuralKnowledge` 数据目录，凭据继续由原生 Keychain helper 处理。回退时恢复配套旧程序和升级前完整数据快照，不清空数据目录排错。

## 使用本轮改进

统一记忆窗口集中查看经历、约定、连接状态和待核对事项。更正需用户选择旧条目并确认新事实，保存后可按原主题重验。完成或取消约定保留历史，不自动发消息。

个人记忆无固定库存上限，每日整理调用/字符及候选累计总量不再卡住队列；保留淡忘、真正遗忘和来源规则。多个窗口仍需分别明确连接；界面选库不改变原有连接授权。自然问法和时间线索只帮助查找已有证据，不补造事实。

“空闲回顾”位于原整理面板，默认关闭。预览只读，手动运行或启用后使用已有模型与强度生成带证据提案；API 按实际用量计费。反思需明确采纳且保持非事实状态，可撤回；策略和模拟不自动启用，效果未验证，不训练模型参数。

模型上下文及输出默认使用公布的最高能力，未知能力由服务决定。星云拖动旋转、Shift 平移、选中节点才保持停止自旋和启动版本提醒继续保留。

## 验证与发布状态

[本轮 Apple Silicon CI](https://github.com/myflww/love-house/actions/runs/41767666536) 已完成 AppKit / WKWebView、Keychain helper、内置后端、原生窗口、签名和 ZIP 解压后运行检查。运行代码受测提交为 `e4a62aa17a2a7041d0f088fcef3ebe820336726a`，`build.json`、`native.json`、`zip-native.json` 均完成且通过。自检使用隔离目录和合成资料，未使用真实用户数据或付费模型；包含空闲回顾默认关闭/只读预览，不代表真实整理效果验收。

本版 ZIP 大小为 `73292676` 字节，SHA256 为 `896df5c6c39def5ffd7e00ef0b647cc2f47e124e37101547ff9004247a7768f8`。随版提供 [macOS-0104-verification.json](https://github.com/myflww/love-house/releases/download/v0.10.4rc1/macOS-0104-verification.json) 与 [macOS-SHA256SUMS.txt](https://github.com/myflww/love-house/releases/download/v0.10.4rc1/macOS-SHA256SUMS.txt)，公开下载字节在上传后单独复核。[本版发布说明](ReleaseNotes-0.10.4rc1-macOS.md#验证记录与系统范围) 维护最终范围；没有覆盖安装用户现有应用或真实用户旧版数据，也未穷尽全部 Mac 系统。当前不提供 Intel Mac 包。
