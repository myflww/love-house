# 爱之屋 0.10.4rc1 · macOS Apple Silicon 完整预发布

本版为 Apple Silicon（M 系列）、macOS 13.0+ 提供完整“爱之屋.app”，沿用 AppKit / WKWebView、内置 Python 和原生 Keychain helper。本轮由真实 Apple Silicon CI 独立编译和运行；本版为预发布，仅有 arm64 包，验证范围见文末。

## 本轮更新

- 同步 [Windows 说明中的七项共享改进](ReleaseNotes-0.10.4rc1-Windows.md#七项记忆与使用体验改进)：自然问法/时间召回、纠正闭环、连接阶段、经历与约定、分层反馈、大库检索及更简明的界面。
- 统一记忆窗口查看经历、约定、连接状态和待核对事项；常用与高级操作分层，普通记事默认经历，保留来源与错误回执。
- 整合不限个人记忆库存、不限每日整理调用/字符及候选累计总量、普通旧失败续排与分片进度。多窗口只覆盖用户明确连接的库和区域，淡忘与真正遗忘规则继续生效。
- 保留模型和强度选择；上下文与输出默认模型公布的最高能力，未知能力由服务决定。
- 在原整理面板增加默认关闭的空闲回顾，使用已有整理模型；只生成有证据提案，反思需明确采纳，策略和模拟不自动生效。当前效果未验证，不训练模型参数，详见 [研究与边界](research/idle-review-design.md)。
- 保留星云普通拖动旋转、Shift 平移、选中节点才保持停止自旋和启动更新提醒。

## 下载与升级

下载 [LoveHouse-0.10.4rc1-macOS-arm64.zip](https://github.com/myflww/love-house/releases/download/v0.10.4rc1/LoveHouse-0.10.4rc1-macOS-arm64.zip)，上传与下载状态以发布页为准。完整解压后将“爱之屋.app”放入应用程序目录；升级前备份 `~/Library/Application Support/NeuralKnowledge`。步骤见 [Mac 更新与恢复说明](MACOS-0104-UPDATE.md)。

仅提供 arm64 包，不承诺 Intel Mac 兼容。应用完成 ad-hoc 签名及完整性校验，未提供 Developer ID 签名或 Apple 公证。

## 验证记录与系统范围

共享源码与空闲回顾已使用合成资料、临时库和模拟模型测试；没有真实付费模型调用。当前自检不证明真实厂商服务效果，也不证明用户现有 Keychain、系统首次打开提示或全部系统版本已验证。

[本轮 Apple Silicon CI](https://github.com/myflww/love-house/actions/runs/41767666536) 已成功，运行代码受测提交为 [`e4a62aa17a2a7041d0f088fcef3ebe820336726a`](https://github.com/myflww/love-house/commit/e4a62aa17a2a7041d0f088fcef3ebe820336726a)。AppKit / WKWebView 与 Keychain helper 已编译，随包后端及原生窗口完成检查，签名验证通过，ZIP 解压后再次通过原生运行。`build.json`、`native.json` 和 `zip-native.json` 均为完成且通过，包含统一工作区导航、空闲回顾默认关闭及只读预览 probe。

测试使用临时合成资料，无真实用户数据或付费模型调用，临时数据已清理。runner 的真实减少动态效果偏好为 true；自检隔离覆盖 no-preference/reduce 两种媒体查询，不改变系统偏好。空闲回顾 probe 不代表真实模型整理效果或全部提案操作都已在原生窗口执行。

| 文件 | 字节数 | SHA256 |
| --- | --- | --- |
| `LoveHouse-0.10.4rc1-macOS-arm64.zip` | `73292676` | `896df5c6c39def5ffd7e00ef0b647cc2f47e124e37101547ff9004247a7768f8` |

本版提供 [macOS-0104-verification.json](https://github.com/myflww/love-house/releases/download/v0.10.4rc1/macOS-0104-verification.json) 与 [macOS-SHA256SUMS.txt](https://github.com/myflww/love-house/releases/download/v0.10.4rc1/macOS-SHA256SUMS.txt)，公开下载字节在上传后单独复核。没有安装覆盖用户现有应用，也未执行真实用户旧版 Mac 数据的覆盖升级；最低系统目标不等于所有 Mac 系统版本均已实测。
