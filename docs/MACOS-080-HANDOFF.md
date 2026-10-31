# 爱之屋 0.8.0 同步交接

功能分支：`codex/experience-agent-sources`，承接 `codex/adaptive-memory-retention` 的 0.7.0 与主分支的代码所有者保护。本次只打包 macOS；不要覆盖 Windows 修复分支、Android 工程或已发布安装包。

先读 [同鱼多平台接入](同鱼多平台接入.md) 和 [Agent 身份与经历](Agent身份与全活动记忆.md)。用户要记住的是鱼真实经历的事情，而不是每次工具调用的技术日志。模型整理必须引用原文，明确原因保持来源归属，未知不能编造。

## 需要同步的共享部分

- `organizer/experiences.py` 及 state/atoms/rules：结构化经历、来源版本核对、严格自主观察分支、安全投影和新身份导入重绑定。
- `service/agent_sources.py`、`source_client.py` 及 host：固定库来源登记、独立凭据、events/context 校验、平台/身份过滤、持久队列。
- `companion/memory.py`、ingestion/structured：真实事件时间与外部参与者归属、可回忆经历 JSON。
- sharing/backups：新库恢复重新核对依据，不继承连接与 Key。
- `viz/web/experience-ui.js`、`agent-sources-ui.js`、builder/index：经历时间线、来源管理、原始工具依据显示过滤。
- `extensions/astrbot-love-house`：独立实验插件，打包固定源码白名单。`source_client.py` 必须与共享 SDK 字节一致。
- `scripts/run_memory_service.py`、`configure_agent_source.py`、desktop.server 注入点：POSIX 无界面服务。Windows 应自行验证并适配自己的启动器，不能直接以 POSIX 脚本宣称通过。

新增管理接口均为本机同源管理权限；来源 Bearer 不能登记来源、读取其他库或下载管理插件。API 详见源码测试与上述教程。登记来源使用宿主断言，`full_activity_coverage_verified=false`，不声称有加密远程 Agent 身份证明。

## 桌面打包

产品版本 0.8.0，服务协议继续 0.4.0，macOS 构建号 11。Mac 原生 `exportAstrBotAdapter` 保存固定内置 ZIP，网页不能指定任意路径。Windows 若要同等体验，应新增自己的文件保存桥并核对当前源、取消、错误与成功状态，或保留明确的浏览器下载入口。

构建需携带 AstrBot 白名单源码和 `Resources/Adapters/LoveHouse-AstrBot-0.1.0-experimental.zip`。私有配置、原始存档、队列和数据库不得进包。公共源码扫描使用显式文件白名单，不允许将整个运行实例拷进仓库。

## 验证与边界

完整回归至少包含 `test_experience_memory`、`test_fish_life_workflow`、`test_experience_delivery`、`test_agent_sources`、`test_agent_source_service`、`test_astrbot_adapter` 和两份 UI JS 行为测试；继续跑旧的固定库、单窗口、备份、遗忘、重复、整理规则与容量回归。Mac 使用 `scripts/build_macos.py --native-smoke` 做隔离原生首启/重启。

真实 AstrBot 养鱼环境使用独立测试库和测试账号；测试结果另列，不能把 fake 模型或 WebChat 通路算成 QQ/阿里云验证。插件当前不覆盖未进入模型的指令、未提供文字的多媒体、绕过钩子的独立主动任务；外部副本/插件本地队列不因服务端遗忘自动被远程抹除。

## 升级和回退

原数据目录与 bundle ID 保持原样，旧 Harness 单窗口连接不静默扩展。升级前使用受管单库备份，应用包另存回滚副本；不要另存绕过遗忘清理的原文 ZIP。回退前停用新增的活动来源，核对升级前备份仍在，并单独处理升级后新记录；旧版本不理解新的来源管理和经历投影。

公开源码分支不包含用户 Key、真实对话、运行目录或私人测试报告。PolyForm Noncommercial 与 myflww 署名保留，第三方许可独立保留。其他系统需在各自最新分支合入后原生验收再发布。
