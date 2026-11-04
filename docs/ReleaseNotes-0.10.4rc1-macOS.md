# 爱之屋 0.10.4rc1 · macOS Apple Silicon 完整包候选

本版计划提供 Apple Silicon（M 系列）、macOS 13.0+ 的完整“爱之屋.app”，沿用 AppKit / WKWebView、内置 Python 和原生 Keychain helper。当前是待 CI 的候选，不表示已经发布或完成 Mac 原生验收；本机没有 Mac，不借用旧版或 Windows 的通过结果。

## 本轮更新

- 同步 [Windows 说明中的七项共享改进](ReleaseNotes-0.10.4rc1-Windows.md#七项记忆与使用体验改进)：自然问法/时间召回、纠正闭环、连接阶段、经历与约定、分层反馈、大库检索及更简明的界面。
- 统一记忆窗口查看经历、约定、连接状态和待核对事项；常用与高级操作分层，普通记事默认经历，保留来源与错误回执。
- 整合不限个人记忆库存、不限每日整理调用/字符及候选累计总量、普通旧失败续排与分片进度。多窗口只覆盖用户明确连接的库和区域，淡忘与真正遗忘规则继续生效。
- 保留模型和强度选择；上下文与输出默认模型公布的最高能力，未知能力由服务决定。
- 在原整理面板增加默认关闭的空闲回顾，使用已有整理模型；只生成有证据提案，反思需明确采纳，策略和模拟不自动生效。当前效果未验证，不训练模型参数，详见 [研究与边界](research/idle-review-design.md)。
- 保留星云普通拖动旋转、Shift 平移、选中节点才保持停止自旋和启动更新提醒。

## 下载与升级

预定文件为 [LoveHouse-0.10.4rc1-macOS-arm64.zip](https://github.com/myflww/love-house/releases/download/v0.10.4rc1/LoveHouse-0.10.4rc1-macOS-arm64.zip)，链接在发布完成前不可下载。完整解压后将“爱之屋.app”放入应用程序目录；升级前备份 `~/Library/Application Support/NeuralKnowledge`。步骤见 [Mac 更新与恢复说明](MACOS-0104-UPDATE.md)。

仅准备 arm64 包，不承诺 Intel Mac 兼容。计划沿用 ad-hoc 签名及完整性校验，未提供 Developer ID 签名或 Apple 公证；最终状态以本轮实际包与报告为准。

## 验证记录与系统范围

共享源码与空闲回顾已使用合成资料、临时库和模拟模型测试；没有真实付费模型调用。当前自检不证明真实厂商服务效果，也不证明用户现有 Keychain、系统首次打开提示或全部系统版本已验证。

本轮需在 Apple Silicon CI 上实际完成 AppKit / WKWebView 与 Keychain helper 编译、随包后端及原生窗口自检、签名校验，以及 ZIP 解压后的再次运行。以上均待本轮 CI 结果；尚无可填写的成功运行链接、最终 SHA256 或受测提交。不复用 0.10.3 的三份报告。

发布前应随包提供本版 `macOS-0104-verification.json` 与 `macOS-SHA256SUMS.txt`，并核对匿名公开下载的实际字节。当前不宣称完成真实用户旧版 Mac 数据的覆盖升级。
