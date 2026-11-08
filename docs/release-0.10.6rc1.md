# 爱之屋 0.10.6rc1：围绕话题取回记忆

本版修复对话中出现“我指的是”等澄清用语时，多个无关旧句子仅因措辞相同被送给大肥鱼的问题。

## 修复办法

- **当前发言与检索焦点分开**：识别澄清、转述、礼貌和问句框架，检索其中的对象和话题。大肥鱼仍收到完整当前发言；否定、频率和限定不会从原发言或排序输入中删除。
- **匹配需要话题证据**：人称、指代、提问套话本身不能证明相关。先限定有内容依据的候选，再排序；图邻居和同文克隆不能挤掉真正的主题或别名来源。
- **不为数量补材料**：只有指代、缺少可定位对象时允许空召回；无关长期偏好或其他会话最近对话不能被用来猜当前所指。大肥鱼可以依据当前可见对话自然回应，检索失败不强制打断聊天追问。
- **明确找原话仍可找**：例如 `查找包含“我指的是”的原话` 会查实际正文和历史助手原文；生成标题、别名或图连接不能冒充这段话确实出现过。

以下为合成回归场景，不是读取真实用户记录：

| 当前输入 | 提供给大肥鱼的材料 |
| --- | --- |
| 我指的是为什么总背清单 | 围绕“背清单”检索；不夹带文档记忆库、情绪体检或“现在选什么” |
| 我指的是你的情绪体检 | 仍可找到情绪体检，不封禁整个澄清句式 |
| 我指的是／我指的是这个 | 不猜旧话题、不补无关偏好、不强制追问 |
| 查找包含“我指的是”的原话 | 返回实际包含短语的可用原文 |

同一份 9 节点、3 连接合成数据，分别用 0.10.5rc1 源码和本轮运行源码调用真实公开函数，结果如下。没有使用模型或模拟返回值；这些是定向诊断，不是整体准确率。

| 场景 | 旧版相关／无关记录 | 新版相关／无关记录 |
| --- | ---: | ---: |
| 背清单 | 1／8 | 1／0 |
| 情绪体检 | 1／8 | 1／0 |
| “这个”无对象 | 0／9 | 0／0 |
| 中文单引号原话搜索 | 3／6 | 3／0 |
| 饮料偏好 | 3／5 | 3／0 |

原话搜索的 3 条是两段原话和一份逐字索引，不是三次独立经历。饮料结果保留温水、肯定咖啡和否定咖啡，颜色偏好被排除。见[实际返回记录与方法](retrieval-0106-evidence/same-data-report.json)及[合成数据](retrieval-0106-evidence/synthetic-fixture.json)。报告还保留了未发布中间提交漏识别中文单引号的诊断，最后源码已经补齐并复测，未替换旧的失败记录。

## 使用与边界

升级服务端即可改善现有工具、代理和 SourceClient 的自动记忆上下文，无需因此重装客户端或重整整个记忆库。原文、角色、来源和版本保留，停用、忘记及连接的窗口／库边界继续生效。人工图谱探索仍保留关联浏览能力。

本轮没有新增收费 API，也没有换成嵌入模型或宣称完整理解所有自然语言。默认检索仍以本地文本和有依据的别名为基础，新增可审计的焦点提取及更克制的候选筛选。当前宿主上一轮没有传给服务时，服务不会从旧窗口或持久化会话猜指代；当前对话理解仍由大肥鱼依据它可见的上下文完成。

## 验证与下载

本轮本机 Python 全套 1347 项通过（10 项条件跳过），JavaScript 332 项通过，桌面源码检查 24 项通过（12 项平台跳过）；最后的中文单引号补齐通过相关 44 项回归。全部使用合成数据，没有读取真实用户记忆或调用付费模型。

运行源码 `226bb7507c783258336b0d0e0136f7608d38fc46` 的 [Python 3.11／3.12／3.13 与 JavaScript CI](https://github.com/myflww/love-house/actions/runs/42144741697)、[macOS／Linux 真实 Harness CLI](https://github.com/myflww/love-house/actions/runs/42144741709)、[Android 28／36 实际 WebView 接口](https://github.com/myflww/love-house/actions/runs/42144741599)和[iOS 模拟器接口](https://github.com/myflww/love-house/actions/runs/42144741607)均通过。发布前逐文件核对构建提交与最终说明提交的运行文件 Git 内容和模式一致。

- [Windows 完整包验收](https://github.com/myflww/love-house/actions/runs/42144735567)：打包、应用原生、临时目录实际安装、0.10.5rc1→0.10.6rc1 实际升级、安装件与便携件在精简／受污染环境运行，以及发行环境全量回归均通过。具体结果见发布资产 `Windows-0106-verification.json`；CI 主机预装 WebView2，未验证所有 Windows 系统、损坏运行时或真实用户旧库。
- [macOS 完整包验收](https://github.com/myflww/love-house/actions/runs/42144735573)：AppKit／WKWebView、模拟 Keychain、后端重启、来源与窗口隔离，以及应用本体和 ZIP 解压件的两次原生运行检查均通过，首次运行完成。具体结果见 `macOS-0106-verification.json`；没有在用户 Applications 目录执行实际旧 App 覆盖升级。

Windows 目标为 x64、Windows 10 2004+／Windows 11；macOS 包适用于 Apple Silicon、macOS 13.0+，采用 ad-hoc 签名，尚未公证。实际平台验收范围以发布验证文件为准。Android 已追加 [0.10.6rc1 原签名 APK](https://github.com/myflww/love-house/releases/download/v0.10.6rc1/LoveHouse-0.10.6rc1-Android.apk)，可从公开 0.8.0rc2 覆盖升级；64 位 ARM / x86、Android 8.0+，完整界面需 WebView 109+。API36 完整引擎与 API28 旧内核的不同验证范围见 [Android 说明](ANDROID-0106-UPDATE.md)及[独立验收报告](https://github.com/myflww/love-house/releases/download/v0.10.6rc1/Android-0106-verification.json)。本次追加未更换原有 Windows、macOS、源码或校验资产；实验性 AstrBot 附件保持 0.3.0。

升级前备份完整数据目录。[本版发布页](https://github.com/myflww/love-house/releases/tag/v0.10.6rc1)提供完整包、源码和校验值，匿名下载核验见附带的 `Public-download-verification.json`。
