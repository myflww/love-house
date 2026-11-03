# Windows 0.10.1rc1 更新与验收

已公开发布 Windows 0.10.1rc1 同步预览，并完成公开下载安装复核。

这是从已公开的 Windows 0.9.1rc1 工程继续开发的同步预览。共享增量来自已发布 macOS `v0.10.1` 的真实源码 `b2279da12c3b14d4708595343433849f3f8f2911`，以 macOS 0.9 基线进行三方差量合并，没有用 Main 的旧生产代码或 Mac 桌面工程替换 Windows。

## 本次同步

1. 人格形成、逐字助手证据、手动核心优先、来源版本与失效检查、移除阻止加回、明确关闭保留、跨库隔离。普通整理可在同一请求补充人格；快速 `purpose=persona` 独立任务不改变普通队列，不自动重试或重置预算。只读预览和查看不调用模型，模型 Key 不进入分享文件。
2. 直接复用批准的 painter／renderer／data、布局、纤维及编译 bundle。原像素界面保留，已有星星按钮是视图切换入口，图画布共用黑白状态与显示坐标。没有把演示样本当作用户记忆，展示不制造实际边或召回次数。
3. 普通新增、确认记忆、HTTP／MCP、历史文本与 CLI 默认不猜测关联。高级 `auto_link` 仅显式启用；共同召回只强化已有有效边。整理 `related_ids`、`relate` 与旧缓存再次经过应用边界，不为修复加模型请求或清账本；明确用户引用、手动关系和真实事件来源边保留，不批量删旧边。
4. WorkBuddy 只读预览、独立确认合并、其他爱之屋连接器冲突阻止、重绑 review／取消／换发、迟到响应与版本保护。来源管理 GET／POST 都要求 UI 管理会话，来源 Bearer 不能管理。保留 Windows Harness 安装、实际路径发现、固定窗口和独立输出不抢绑定的边界。
5. 保留分享范围与整理模型解耦、30 秒完整预览超时重试、原生保存／取消／写失败／异源隔离与 AstrBot ZIP 导出。可选 AI 状态缩短为 4 秒，凭据和模型必须都明确就绪且另行同意，不影响 JSON／Markdown。
6. Windows 捕获时钟可能令相邻记录时间戳完全相同。人格旧依据在相同时间时按实际入库顺序判定，后写入原文不能提前成为“更早”依据；不同时间仍保留时间边界。

## 安装、升级与回退

适用 Windows 10 2004／19041 及以上或 Windows 11 x64，Intel／AMD 64 位。下载 EXE 以当前用户安装，或完整解压 ZIP 运行 `LoveHouse.exe`；不能只拖出一个 EXE。WebView2／.NET 探测与离线微软组件修复沿用既有实现。

升级前关闭爱之屋和向它写入的宿主，备份停止写入后的完整 `%LOCALAPPDATA%\LoveHouse` 及旧程序。数据目录与程序目录分离，安装或卸载程序不应删除原库。`organizer.sqlite3.jobs` 增加 `purpose` 列，旧行默认普通 memory；旧事实缓存沿用原规则版本，不因人格增量重新付费。若回退到旧版，必须同时恢复升级前的完整配套数据快照。

## Windows 验收方式

发布门禁要求同一冻结源码完成完整回归、真实 Windows EXE／ZIP 构建、安装与便携各自的后端／WebView2 原生／污染环境检查。新增人格、原版图、独立节点检查随真实包运行；旧版本升级检查必须先匿名下载固定 SHA256 的公开 0.9.1rc1 安装器，在 GitHub Windows 的独立合成目录启动旧版、写入资料、退出，再用本次安装器覆盖并重新启动，比较旧库、原文、回收站、固定连接、私有配置摘要、整理设置与假凭据元数据。

所有报告须退出码 0、`ok:true`、`process_complete:true`，并完成临时资料清理。发布器逐字节核对新 UI／图 bundle 与冻结源码，拒绝旧 bundle 或缺失资产；先建草稿再上传，不移动旧标签或替换旧附件。公开后再匿名下载 EXE／ZIP，核对固定 SHA256 后重新安装、解压和运行。最终完成范围见发行附件 `Windows-0101-verification.json` 与对应 CI 链接；未完成的验证不能写成已通过。

只使用临时合成记忆与假 API／假凭据，没有读取或备份用户真实资料，没有新增真实 DeepSeek 付费调用。新 Windows 预览不代表 Win10 真机、运行时损坏、企业安装策略、任意 GPU／高 DPI／字体、全部模型账户或长期运行均已通过。旧记录被真正遗忘、停用或更正后，派生人格不能继续作为有效依据。

本次不重发 macOS 或手机包，保留其公开入口与历史发布资产。自有代码继续采用 PolyForm Noncommercial 1.0.0，保留 myflww 署名及第三方许可；主程序未附商业发行商签名。

修复 Windows 并发记录记忆使用时偶发的保存失败；同次使用仍只计一次，尚未确认的记录继续保留待处理，避免重复巩固。

## Windows 已完成检查与公开下载复核

冻结生产源码为 [`1a69676cb9e98b343fc0a01bb47e07028cb39323`](https://github.com/myflww/love-house/tree/1a69676cb9e98b343fc0a01bb47e07028cb39323)。[Windows 构建与安装记录](https://github.com/myflww/love-house/actions/runs/41312425782) 已完成 EXE／ZIP 构建，便携与安装各自的 backend／native／consumer 六份检查，以及从匿名下载的固定 0.9.1rc1 安装器覆盖升级。检查包含合成原文、库与回收站、固定连接范围、整理设置、人格明确关闭选择、私有配置摘要和假凭据元数据的保留及重启核对；原生窗口检查人格、批准的星图、独立记忆及完整导出。

六份检查要求退出码 0、`ok:true`、`process_complete:true` 并清理临时目录。另见 [完整回归](https://github.com/myflww/love-house/actions/runs/41312425825) 和 [Harness 实际宿主轮次](https://github.com/myflww/love-house/actions/runs/41312425812)；这些记录使用同一冻结生产源码。

公开下载复核另在独立 CI 中记录：从真正公开地址匿名下载 EXE／ZIP，核对固定 SHA256 后重新安装、解压及启动。上述构建、六份包内检查与覆盖升级不代替这一步，也不据此宣称公开下载安装已通过。发布附件、固定受测文件和后续验证入口见 [Windows 发布页](https://github.com/myflww/love-house/releases/tag/v0.10.1rc1)、[Windows-0101-verification.json](https://github.com/myflww/love-house/releases/download/v0.10.1rc1/Windows-0101-verification.json) 与 [Windows-SHA256SUMS.txt](https://github.com/myflww/love-house/releases/download/v0.10.1rc1/Windows-SHA256SUMS.txt)。

只使用临时合成资料、模拟 API 和假凭据，未读取用户真实 Key，未新增真实 DeepSeek 调用。Win10 真机、缺失／损坏运行时、企业安装策略与长期运行仍待独立验收。

## 源码、下载与验证记录

生产构建使用 [冻结生产源码 `1a69676cb9e98b343fc0a01bb47e07028cb39323`](https://github.com/myflww/love-house/tree/1a69676cb9e98b343fc0a01bb47e07028cb39323)。`main` 的生产代码仍按仓库审阅流程合并；此处更新下载说明不表示所有生产分支已合并。

- [Windows 发布页](https://github.com/myflww/love-house/releases/tag/v0.10.1rc1)
- [EXE 安装包](https://github.com/myflww/love-house/releases/download/v0.10.1rc1/LoveHouse-Setup-0.10.1rc1-Windows-x64.exe) · [ZIP 便携包](https://github.com/myflww/love-house/releases/download/v0.10.1rc1/LoveHouse-0.10.1rc1-Windows-x64.zip)
- [Windows 校验文件](https://github.com/myflww/love-house/releases/download/v0.10.1rc1/Windows-SHA256SUMS.txt) · [受测文件与验证附件](https://github.com/myflww/love-house/releases/download/v0.10.1rc1/Windows-0101-verification.json)
- [Windows 构建、安装与原生检查](https://github.com/myflww/love-house/actions/runs/41312425782) · [Harness 实际宿主轮次](https://github.com/myflww/love-house/actions/runs/41312425812) · [完整回归](https://github.com/myflww/love-house/actions/runs/41312425825) · [发布及附件校验](https://github.com/myflww/love-house/actions/runs/41314554471) · [公开下载后安装与启动](https://github.com/myflww/love-house/actions/runs/41314722407)

Mac 的 [人格实现说明](https://github.com/myflww/love-house/blob/v0.10.0/docs/MACOS-010-PERSONA.md)、[批准星图代码说明](https://github.com/myflww/love-house/blob/v0.10.0/docs/NEURAL-ATLAS-010.md) 和 [独立记忆修复说明](https://github.com/myflww/love-house/blob/v0.10.1/docs/MACOS-0101-INDEPENDENT-MEMORIES.md) 固定到对应发布源码，不能替代本页 Windows 验证。

## 本机 Windows 11 实测

本机另以实际便携版 EXE 在 Windows 11 家庭中文版 x64（构建 26200）完成原生窗口检查：8 项原生导出、人格、原版星图、独立记忆及重启均通过。运行环境为 WebView2 156.0.4314.58、显示像素比 1.35；检查使用独立合成资料，模型调用为 0，未读取用户 Key，临时资料已清理。这项本机记录与 CI 验证分别记录；Win10 仍待真机验收。
