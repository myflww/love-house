# Windows 0.8.0rc1 共享功能同步交接

本次以当前 macOS 工作区实际 0.8.0 源码为共享功能来源，在现有 Windows 发布分支及本轮 Harness 修复上选择性合并。Windows 版本使用 0.8.0rc1，服务协议仍为 0.4.0。公开下载与发布状态由发布记录单独确认。

## 已同步的共享实现

- 0.6：事务回滚与单次落盘优化、历史聊天预览/导入、S/M/L 新窗口资料包、公开版本检查及系统/架构匹配。
- 0.7：个人库自适应策略、max_nodes:null、连续淡化与真实使用巩固、无原文使用日志、模型整理准则及越权输出校验。
- 0.8：同一 Agent 的多来源登记、来源 SDK、经历整理与显示、云端无界面服务入口、QQ/AstrBot 实验插件及其受审源代码包。
- 原窗口默认隔离、固定库身份、真实原话与结果来源、明确忘记和本库备份清理继续保留。

## Windows 实现的保留与适配

保留 Windows 现有 native WebView2 壳、单写者锁、UTF-8/LF stdio、系统凭据、CLR/运行时污染清理、启动分类诊断、签名/hash 验证的离线 Runtime 修复、按用户安装和消费环境验证。没有复制 macOS 原生壳、构建程序、私有数据或本机产物。

原生 ready 文件加入本次控制器实例标识。测试模式关闭自动公开版本联网。后端自检验证自适应策略、整理引导、资料包、来源/经历和版本接口；WebView2 自检验证各项真实入口已加载。

PyInstaller 只显式加入 AstrBot 的九个受审源文件和原始 SDK 校验输入，不遍历用户配置、消息或 outbox。下载插件包仍逐字验证 SDK 同源；普通桌面用户不需要自行安装 Python 或 Node。

POSIX 无界面服务脚本仍按其明确平台范围运行；Windows 使用自己的桌面程序，未把 POSIX 进程/锁语义套到 Windows。

## 迁移边界

个人库升级为 max_nodes:null。升级前保留应用及既有受管备份；旧版不能直接打开新版活动目录，回退须配套恢复升级前数据并另行处理升级后新增资料。明确忘记仍清理相关旧备份，不制作绕过清理的私有原文 ZIP。

图谱仍是 JSON，使用元信息单独 SQLite；操作、文件和上下文仍有各自预算。QQ/AstrBot 为实验适配，不把配置就绪当作全平台真实采集验收。

## 验证记录

共享功能合并后的本机全量第一轮 791 项测试通过，桌面 19 项通过。增加原生适配后 Windows 打包合同 37 项通过；源码模式后端自检结果为 ok:true、latest_feature_apis:passed、astrbot_source_package:passed。

这些是开发机上的共享代码与源码模式验证。Windows CI 的冻结安装包/原生自检、Windows 官方 Harness 实际完整对话及其他系统的连接验证须分别保留证据，不能互相替代。

## 本轮补充验证与跨系统连接

修正测试夹具在 Windows 未显式关闭 SQLite 连接的问题后，开发机最终全量为 814 项通过；这不是 Windows CI 或消费者环境的等价结果。使用日志和 AstrBot 生产连接管理原本已有 finally close，修正保留事务与错误回滚规则。

`verify_harness_connection.py` 已在 macOS 上用官方 rc.3 App，以及锁定的官方 rc.5 npm CLI，分别完成 Harness/原 MCP 两模式的真实宿主回合。每种模式实际走本机 SSE 合成模型并保存两方原话，另开真实会话验证窗口隔离；报告成功与进程退出码一致。所有 profile、模型凭据和记忆库都为隔离合成资料。

新增 `cross-platform-connect.yml` 在 Ubuntu/macOS 对应 runner 上运行同一真实 CLI 驱动。官方 npm CLI 与完整依赖通过提交的 package-lock integrity 固定，关闭安装脚本；CI 完成前不把本机 macOS 上的 npm CLI 结果说成已完成 Linux 运行验证。
