# Harness 更新兼容检查

爱之屋通过 Harness 的 `session/event` 接收已提交的对话事件，通过 `agent/pre-step` 注入当前库的记忆。检测到安装路径和版本，只说明找到了宿主；插件在线、完整轮次存档和窗口隔离还需要分别验证。

当前兼容检查覆盖官方 Harness `0.2.1-rc.3`、`0.2.1-rc.5`（Cordis `4.0.5`），以及 `0.2.2-rc.1`（Cordis `4.1.0`）。安装路径、配置格式和能力判断由适配器维护；发生变化时应保留实际版本和具体诊断，不能把契约不兼容显示成没有安装程序。

## 自动检查

[Harness compatibility 工作流](../.github/workflows/harness-compatibility.yml) 在适配器、记忆服务、相关测试或工作流变更的推送与 PR 上运行。旧版在 Linux 检查，当前新版在 Linux 和 Windows 检查。

每天及手动运行时，工作流另取官方 `@deepseek-ai/dsh` 的 `latest` 标签作为候选。先解析 CLI 的精确版本，再安装同一精确版本的 `dsh-agent/session/llm/scope`；不会拿这些 SDK 各自的 `latest` 标签代替 CLI 版本。候选 Cordis 从该 CLI 声明的依赖范围解析，受测旧版和当前版使用表中的精确 Cordis 版本。

所有 npm 安装禁用生命周期脚本。检查使用 Node `24.22.1`、Python `3.12`，依次执行类型检查、构建、适配器测试、Python 连接测试及真实官方 CLI 验证。CLI 验证由 `scripts/verify_harness_connection.py` 创建临时 `DSH_HOME`、临时记忆服务和回环地址上的合成模型，检查两种连接方式的原话保存、完整轮次回执和第二窗口排除。

工作流不使用真实模型 Key、个人会话或用户记忆。它只写 GitHub 检查结果和构建附件，不自动发评论、创建 issue 或修改用户配置。每行矩阵保留解析版本、依赖锁、安装与测试日志；真实 CLI 运行时另保留合成验证 JSON 和失败报告，保存 14 天。

## 新版本失败时

1. 在 Actions 中打开失败矩阵，下载 `harness-compatibility-*` 附件。先看 `selection.json`，确认实际 CLI、SDK 和 Cordis 版本，再看失败步骤及 `real-cli/result.json`（若已运行）。
2. 对照官方发布说明、安装布局和公开类型，检查事件参数、消息身份与来源、完成／取消边界、pre-step 返回值、公开历史投影及窗口隔离。使用隔离资料重现，不加载用户现有 profile。
3. 修复能力判断或协议适配，补充行为回归；新契约通过后再更新支持记录和随包资源。单独增加版本白名单或跳过失败不能证明兼容。

能力配置和行为检查可以提前发现许多升级问题，但无法保证未来 API 破坏性变更永远兼容。未知或改变的契约应给出安全、具体的诊断；CI 失败应保持可见，不能用旧版成功结果代替新版本验收。需要真实运行回执后，界面才能宣称已经自动存档。

官方来源：[Harness 发布说明](https://github.com/deepseek-ai/deepseek-harness/releases) · [Desktop 安装与 profile 归属](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/desktop/README.md#installation-ownership) · [适配器说明](../extensions/deepseek-harness/README.md)。
