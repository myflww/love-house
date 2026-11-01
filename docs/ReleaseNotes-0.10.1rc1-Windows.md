# 爱之屋 0.10.1rc1 · Windows 同步预览

Windows 10 2004（19041）及以上／Windows 11，Intel 或 AMD x64。提供完整 EXE 安装包与 ZIP 便携包；无需安装 Python 或 Node。本版承接 Windows 0.9.1rc1，按 macOS 0.9.2、0.10.0、0.10.1 三份 Windows 交接书选择性合入共享实现。

- 人格随记忆形成：新库默认开启人格和学习，固定设定为空；明确关闭的选择保留。特征需要当前库至少两条独立助手原话，手动核心优先。快速整理先只读预览，另行确认后最多一次模型请求；平常整理在同次请求补充，不额外开人格调用。
- 直接采用已批准的神经星图绘制与布局代码。原星星按钮切换动态星云／平面图，黑白主题仅作用图画布。浏览、缩放、暂停或切图不会增加实际召回次数。
- 独立记忆可以没有关系：默认入库不按前缀、同名、时间、通用标签猜测连线；共同召回只巩固已有有效边。整理器自由提出的关联及旧缓存不能绕过，合法事实和真实来源照常保存；不擅自删除历史边。
- WorkBuddy 预览后另行确认合并；其他爱之屋连接器冲突时停止自动合并。固定窗口范围、重绑定、旧凭据隔离、Windows Harness 检测、中文路径及原生导出修复继续保留。
- 修复 Windows 相同捕获时间戳时的人格依据排序，防止把后写入记录当作更早上下文。

升级前退出爱之屋并备份完整 `%LOCALAPPDATA%\LoveHouse` 数据目录；安装版覆盖安装，便携版完整解压后替换程序。整理数据库新增 `jobs.purpose` 列；回退旧版须恢复升级前配套数据快照，不能只换回旧 EXE。数据不在程序安装目录，勿删除记忆目录处理启动问题。

核对本页 `Windows-SHA256SUMS.txt`。主程序未附发行商代码签名；微软 WebView2 离线修复组件单独核验微软签名与散列。本版为预览，Windows 验证结果与边界以 `Windows-0101-verification.json` 及 [Windows 更新说明](https://github.com/myflww/love-house/blob/v0.10.1rc1/docs/WINDOWS-0101-UPDATE.md) 为准；Mac 验收不能代替 Windows 安装包验证。测试使用合成库与模拟 API，未读取用户密钥或新增真实 DeepSeek 调用，Win10 真机与缺失／损坏运行时仍需独立验收。

macOS 继续使用 [0.10.1 稳定版](https://github.com/myflww/love-house/releases/tag/v0.10.1)，手机继续使用现有 0.8.0rc2；本次不重发其他平台安装包。保留 myflww 署名、PolyForm Noncommercial 1.0.0 与全部第三方许可。

修复 Windows 并发记录记忆使用时偶发的保存失败；同次使用仍只计一次，尚未确认的记录继续保留待处理，避免重复巩固。

## Windows 已完成检查与公开下载复核

冻结生产源码为 [`1a69676cb9e98b343fc0a01bb47e07028cb39323`](https://github.com/myflww/love-house/tree/1a69676cb9e98b343fc0a01bb47e07028cb39323)。[Windows 构建与安装记录](https://github.com/myflww/love-house/actions/runs/41312425782) 已完成 EXE／ZIP 构建，便携与安装各自的 backend／native／consumer 六份检查，以及从匿名下载的固定 0.9.1rc1 安装器覆盖升级。检查包含合成原文、库与回收站、固定连接范围、整理设置、人格明确关闭选择、私有配置摘要和假凭据元数据的保留及重启核对；原生窗口检查人格、批准的星图、独立记忆及完整导出。

六份检查要求退出码 0、`ok:true`、`process_complete:true` 并清理临时目录。另见 [完整回归](https://github.com/myflww/love-house/actions/runs/41312425825) 和 [Harness 实际宿主轮次](https://github.com/myflww/love-house/actions/runs/41312425812)；这些记录使用同一冻结生产源码。

公开下载复核另在独立 CI 中记录：从真正公开地址匿名下载 EXE／ZIP，核对固定 SHA256 后重新安装、解压及启动。上述构建、六份包内检查与覆盖升级不代替这一步，也不据此宣称公开下载安装已通过。发布附件、固定受测文件和后续验证入口见 [Windows 发布页](https://github.com/myflww/love-house/releases/tag/v0.10.1rc1)、[Windows-0101-verification.json](https://github.com/myflww/love-house/releases/download/v0.10.1rc1/Windows-0101-verification.json) 与 [Windows-SHA256SUMS.txt](https://github.com/myflww/love-house/releases/download/v0.10.1rc1/Windows-SHA256SUMS.txt)。

只使用临时合成资料、模拟 API 和假凭据，未读取用户真实 Key，未新增真实 DeepSeek 调用。Win10 真机、缺失／损坏运行时、企业安装策略与长期运行仍待独立验收。
