# 爱之屋 0.7.0 自适应记忆同步交接

本次承接 0.6.0 的聊天导入、记忆包和版本检测，并落实用户最新定位：个人记忆不因固定条数或统一天数消失，AI 整理服从程序底层规则。

分支：`codex/adaptive-memory-retention`。先读 [自适应记忆与整理规则](自适应记忆与整理规则.md)。这是 macOS 先行更新，Windows 与移动端需要在各自最新分支上合并共享改动，并完成原生验证。不要覆盖已发布 Windows 修复或 Android 工程。

新增核心：`companion/retention.py`、`service/usage.py`、`organizer/rules.py`。`config.py` 和 `core/brain.py` 支持个人策略的 `max_nodes=None`，导入、整理、生命周期的旧数值比较均须兼容。普通 CLI 仍保留显式数值容量测试。

新增入口：

- `GET /api/retention`：本库实际策略、数量、状态、存储大小和待巩固元信息。
- `POST /api/retention/settings`：仅 `mode:adaptive`、`forgetting_pace:gentle/balanced/fast`、`usage_reinforcement:boolean`；不接受条数或存放期限。
- `GET /api/organizer/rules`：实际版本化引导和程序边界，只读、不联网、不调用模型。

UI 的“记忆规律”与“整理准则”分别对应以上入口。自适应节点不能继续展示旧“半衰期 N 天 / 恢复窗口 200 天”文案。原生自检应验证两个入口和实际系统引导可查看。

真实连接取回资料会排队使用元信息，完整用户发言仅以保守字面匹配记录明确重提。只读资料接口不改图谱文件；下次对话入库或维护事务再应用使用事件。必须先成功提交图谱，后确认 usage；确认失败不能把已保存正文报告为丢失。更新关闭开关、明确忘记、库隔离和幂等均需回归。

`memory-usage.sqlite3` 只含库 ID、节点 ID、类型和时间，不含查询或聊天正文。SQLite 图谱迁移未接入，本轮继续 JSON。导出和恢复的单次大小限制仍存在，不能宣传任意尺寸单文件无限导出。

0.7.0 配置会保存 `max_nodes:null`。升级前保留应用和私有数据备份；旧版程序不理解该配置，回退需要配套恢复升级前数据，不能直接共用活动目录。备份只能留在本机，不可上传 GitHub。

验证至少覆盖：11000 同日完整对话全部保存并重开、无容量驱逐；年久记录淡化仍可强线索召回；多次使用与间隔强化；后台浏览不强化；异常保存与 usage 确认失败；固定库与默认单窗口；模型越权输出被拒绝、空整理结果仍保留原文。具体单测位于 `test_temporal_retention`、`test_unlimited_archive_ingest`、`test_usage_journal`、`test_retention_service`、`test_retention_ui`、`test_organizer_rules`。

产品版本为 0.7.0，服务协议仍为 0.4.0；macOS 构建号 10。不得将本机/模拟测试称为 Windows 消费者环境验收。许可证与 myflww 署名保持原样。

本机升级前的数据备份使用各库既有受管备份，不另存绕过遗忘清理的原文 ZIP；用户明确忘记时，该库旧备份仍会按既有规则清理。回退前先确认配套备份仍在，并另行处理升级后新增的资料。
