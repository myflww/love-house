# macOS 0.10.3rc1 升级与恢复

适用 Apple Silicon（M 系列）、macOS 13.0+。完整应用自带 Python 和本地页面资源，无需单独安装 Python、Node 或模型 SDK。

1. 退出旧版爱之屋并停止写入，备份完整的 `~/Library/Application Support/NeuralKnowledge`。
2. 从 [本版发布页](https://github.com/myflww/love-house/releases/tag/v0.10.3rc1)下载 `LoveHouse-0.10.3rc1-macOS-arm64.zip`，按同页校验文件核对 SHA256。
3. 完整解压，把“爱之屋.app”放入原应用程序目录；不要将程序文件放进记忆数据目录。
4. 打开后确认原记忆库、连接、人格开关和整理模型。只有整理已启用、来源有效且 API 可用时，旧失败任务才会继续处理。
5. 首次打开遵循 macOS 系统提示核对来源。本包为 ad-hoc 签名，未经过 Developer ID 签名或 Apple 公证。

本版继续使用 `local.neural-knowledge.atlas` bundle ID 和 `NeuralKnowledge` 数据目录；凭据由原生 Keychain helper 处理，Keychain 不可用时会明确显示临时保存状态。

多个窗口仍需各自明确连接到对应记忆库和授权范围。界面选库不改变既有连接归属；自动存档仍需宿主支持相应回调。

回退时先退出本版，再恢复升级前的完整数据备份与配套旧程序。不要通过清空数据目录处理启动问题。

原生 macOS 构建与验证范围见 [本版说明](ReleaseNotes-0.10.3rc1-macOS.md#验证记录)。
