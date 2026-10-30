## 0.8.0rc1 · Windows 最新功能同步候选（未发布）

- 同步 macOS 当前 0.8.0 的共享记忆内核、界面和服务：无固定条数驱逐的自适应记忆、真实使用巩固、模型整理准则、聊天导入、分档记忆包及平台更新检测。
- 同一 Agent 可登记多个活动来源；QQ/AstrBot 实验适配及可追溯经历页面随共享实现提供，未宣称所有平台都已完成宿主验收。
- 保留 Windows 单写者、Unicode stdio、系统凭据、运行时检测与离线修复、消费者启动及安装验证流程；不以 macOS 的旧 Windows 草稿覆盖现有实现。
- 原生自检增加最新功能 API 与界面控件验证；成品显式包含受审 AstrBot 插件源与同源 SDK，自动版本网络检查在自检中关闭。
- Harness 识别与原 MCP 连接补装自动上报修复一并保留。所有真实连接结论以对应系统、官方宿主的实际完整回合保存结果为准。

## 0.5.1rc2 — Windows Harness connection repair (unreleased)

- Enable the DeepSeek Harness connection wizard on Windows and inspect the installed runtime version from official Electron package metadata. Support standard user/system install locations, registry locations, custom executable paths, and a custom Harness profile.
- Let existing generic MCP connections install the Harness automatic capture plugin while retaining the same connection, library, identity, and session scope.
- Keep detection read-only, back up host configuration before installation, persist installation paths per connection, and verify capture only after a real completed dialogue is saved.

# 变更记录

## 未发布 · Windows 启动与离线依赖修复

- 启动失败不再把“另一个窗口已打开”“缺少微软 WebView2 运行时”“其他错误”合并成一句提示；三类分开说明。
- 使用 x64 WebView2Loader 实际探测运行时，注册表仅作辅助；区分 .NET、打包 DLL、目录权限及异步初始化超时，清理外部 Python/CLR/WebView2 环境污染。
- 新增 `%LOCALAPPDATA%\LoveHouse\logs\startup.log` 与 `LoveHouse.exe --diagnose`：只写系统版本、WebView2/.NET 版本、失败类型与代码位置，不写异常原文、记忆、密钥或对话，可直接转发。
- 安装版与便携版携带固定 SHA256 和微软有效数字签名验证的 Evergreen x64 离线组件；明确确认后修复，结束后重新探测。按用户安装、卸载不清记忆。
- 修复第二实例清理首实例 ready 文件、服务线程未启动时 shutdown 卡死、测试缓存退出竞争和旧 MCP 入口代码页错误；日志目录不可写时回退 TEMP。
- 已在 Windows 11 x64 上完成实际打包、普通界面、中文路径、重复启动与消费者冒烟验证；干净系统 Runtime 缺失/损坏的实测仍待完成，不发布为已验收的 0.5.1。详见 [Windows 验证记录](docs/WINDOWS-VALIDATION.md)。

## 0.5.0 · 存档继承、分享与公开非商用发布

- 新窗口可连接已有记忆库，读取固定身份与人格；新增 bootstrap、完整目录和分块原文读取工具，明确上下文覆盖范围。
- 新的通用 Agent 默认单窗口：本机在 outbox 原文前过滤、离线与重启保留绑定，服务端复核；扩大为整连接需明确允许。API 单窗缺真实 header 则拒绝。
- 区分完整对话、工具观察、原始事件与索引等待，工具结果不再冒称完整聊天可召回。
- 强化服务端固定库校验，拒绝跨库节点、游标、参数、伪造确认与连接凭据复用；旧 MCP 状态不再列出其他库。
- 增加单库完整 JSON 分享包、Markdown 阅读文件、导入预览与全新库导入；可选整理模型阅读索引复用本库预算，原始记忆不被摘要替代。
- 新增桌面原生保存对话框；分享前检查范围、隐藏可识别凭据与本机路径，并保留停用及过时标记。
- 新增 Windows 桌面与按用户安装程序构建；通用 MCP 接入，系统凭据保管库，Windows CI 验证后提供下载。
- 自有部分改用 PolyForm Noncommercial 1.0.0，公开下载、非商用、保留作者 myflww 署名；第三方许可证独立保留。

## 0.4.2 · 清楚看见与轻松接入

- 新增本机 Agent 连接：直接复制标准 MCP 配置，无需模型厂商 Key；轮次结束回调独立安装，工具在线与自动记录状态分开显示。重启自动发现服务，离线记录持久排队并补交。
- Harness 专用插件保留，高级 API 转发入口折叠；整理模型凭据与记忆连接凭据分开。
- 自动视距结合节点数量、实际投影范围与面板占用；少量节点清晰可见，手动操作后保留视角。节点名称默认隐藏，提供显示开关。
- 同轮手动和自动采集副本保留来源、统一召回；支持检查、合并与拆开。整理可严格按累计 N 条触发，并归并有证据的跨轮重复事实。
- Agent 使用有界结构化 JSON 记忆，保留角色、时间、状态、来源与关系；可视化继续显示人类文字。
- 记忆库回收站支持删除和恢复，包括框架示例；删除撤销连接，默认空库和示例隔离不变。

## 0.4.1 · 像素之家与连接指引

- 新增悬停与键盘用途提示，动态按钮、禁用原因、对话框与屏幕边缘均可使用。
- 新建连接改为聊天方式、保存位置、完成连接的三步向导，可直接创建独立库。
- 当前库和其他库连接分组，提供打开目标库；Harness自动备份连接，API给出清楚的回填指引。
- 应用界面改为奶油/樱花像素风，按钮与20枚图标由imagegen生成；中文像素字体离线打包并保留OFL许可，神经星图区保持黑色。
- 原生工具栏采用同组像素图标；产品版本与服务协议版本分开，继续兼容原有连接和密钥。

## 0.4.0 · 爱之屋

- 统一品牌、像素爱心应用图标与黑白粒子神经星云，保留旧 bundle ID 和数据位置。
- 独立 Agent 记忆库、固定连接归属与默认空库；API 网关与可检测/应用的 Harness 自动存档插件。
- 用户配置兼容模型地址与系统钥匙串密钥，分离厂商密钥与本地连接凭证。
- 原文先保存，后台模型整理，逐字来源校验、语义别名、冲突/人格候选、用量预算和失败重试。
- 更正、停用、真正忘记与删除防回放；本库备份默认恢复成新库，保留原 Agent。
- 桌面长期记忆不按固定 200 天直接删除，底层实验接口维持兼容。

# 变更

## 0.3.1 · 2026-10-28

- 黑白全画布与动态粒子星云；常用面板默认收起，保留可恢复按钮、快捷键与焦点返回。
- DeepSeek API上下文装载、角色分离的对话存储、明确记住；缺密钥不会模拟成功。
- DeepSeek Harness专用MCP桥、个人/示例双服务隔离、带来源和成功/失败结果的网页事件。

- 补齐桌面笔记导入：原生文件选择、只读预览、批量写入、重复跳过和明确的Wiki关联。
- 节点支持编辑并保留标识/时间/强化次数，归档上下文摘录在详情可读。
- 修复异步召回覆盖预览、写入成功后刷新失败误报等日常流程缺陷。


## 0.3.0 · 2026-10-28

- 加入Three.js艺术视图与原生macOS应用，保留Canvas分析视图和离线HTML。
- 新增200天恢复窗口、四阶段记忆状态、有限情绪锚点上下文及真实摘录。
- 修复重复衰减、失效桥梁、历史未来信息泄漏、容量满时反思半提交、配置丢失。
- HTTP同源/Host校验、完整操作锁与失败回滚；MCP默认只读、显式学习。
- Python最低版本改为3.11；一键入口查找兼容解释器，应用内置Python。
- 新增教学图谱与测试，具体证据见docs/能力核对与验收.md。


遵循 [语义化版本](https://semver.org/lang/zh-CN/)。
`0.x` 阶段小版本可能有不兼容改动，会在下面写清楚。

---

## [0.2.0] — 2026-10-28

这一版回答的是"过了一段时间会怎样"。0.1 解决"记得住"，0.2 解决"会变"。

### 新增

- **双时态**（借鉴 Graphiti）：`supersede` / `invalidate` / `history`。
  事实有 `valid_from` / `valid_to` / `superseded_by`，过期的不参与检索但保留在库里。
  `recall(include_expired=True)` 可回看历史。这是 LongMemEval 上最影响成绩的一类能力：
  知识更新。
- **情绪冲击 `impact`**（借鉴 MemoryBank / EchoVessel）：-1~1。
  点火时加权，遗忘时半衰期最多 ×2.5。有感觉的事记得更久。
- **反思 `reflect()`**（借鉴 Generative Agents）：按标签把 ≥3 条碎片压成一条
  `reflection` 节点，连回成员，不衰减，幂等。可选 `rewrite=` 接 LLM。
- **前瞻记忆**：`commit` / `due` / `resolve`。承诺不衰减，到期出现在 tick 提醒里。
- **节律 `tick()`**：遗忘 → 反思 → 待办，一次做完。挂 cron 即"每天醒一次"。
- **评测 `bench`**：留一法（用标题查自己）+ 自定义探针（含 abstain 考法）。
  只测检索，不测模型。
- 新 CLI：`commit` / `due` / `resolve` / `supersede` / `history` / `reflect` / `tick` / `bench`。
- 新文档：[docs/完整生命.md](docs/完整生命.md)，八层清单 + 采纳判断 + 做不到的清单。

### 修复

- 过期节点会被扩散"带回来"（种子过滤了，命中没过滤）——现在两边都过滤。
- `history()` 缺 `superseded_by` 字段。

### 调研结论（写下来免得以后推翻）

- 厂商自测的 LoCoMo 分数不可信（全上下文基线就能赢）；LongMemEval 更有区分度，
  但唯一算数的是自己 50 条真实问题。
- ContextEcho（2026）证明 23 个前沿模型在长会话里都会人格漂移，压缩上下文不能复位，
  **单次重锚可以**。所以"换模型不变"靠的是每轮注入稳定内核 + 事后测漂移，不是靠模型自觉。
- REMP（EMNLP 2026）：长程角色扮演的两个瓶颈是记忆完整性与情绪一致性。
  前者归本库，后者归人格层。

### 仍然没做

权重层微调（无算力/无语料）、多设备同步、自动冲突消解、人格层（不在本仓库）。

---

## [0.1.0] — 2026-10-28

第一个能用的版本。四个机制都跑通了，测试 32 项全绿。

### 新增

- **核心**：`Brain` 门面 —— 加权图、赫布增强、分级半衰期衰减、激活扩散检索。
- **可解释召回**：`recall()` 返回的不只是命中，还有 seeds / depth / path，
  前端据此画扩散动画。
- **可视化**：单文件前端，力导向图 + 检索 + 三层滑块 + 主题切换。
  服务模式拉 API，`nkb viz` 导出后离线可用（检索在浏览器里用同一套公式算）。
- **三种接入**：MCP（stdio，5 个工具）、HTTP（`/api/*`）、Python SDK。
- **导入**：按 Markdown 标题切块，标签取自文件名与目录，自动连边，幂等。
- **配置**：`nkb.toml` + `NKB_*` 环境变量，默认值 → 库文件 → 显式 → 环境。
- **扩展点**：`Encoder` / `SeedScorer` / `StorageBackend` / `Renderer` 四个协议，
  编码器支持 entry points 插件。
- **CLI**：`init / add / link / recall / get / stats / ingest / forget / serve /
  mcp / viz / export / doctor / config`。
- **自检**：`nkb doctor` 检查 Python 版本、库可读可写、孤立节点、可视化资源、MCP 握手。

### 设计取舍（写下来免得以后推翻）

- **不用向量库**：向量答"哪段最像"，不答"和谁有关"。可解释性也没有。
  需要语义时换 `encode`，图结构不动。
- **不做 LLM 抽取**：抽取是黑箱，导入后没法解释"这条为什么在库里"。
  只用标题切分和人工 `add`。
- **单 JSON 文件 + 原子写**：为了能 `git diff` 看知识怎么长。
  几千节点够用，十万级再换 SQLite。
- **衰减手动触发**：没有后台定时器，避免"某个查询里节点突然没了"。
- **`k` 默认 8，建议 ≤6**：上下文里 6 条高相关的，比 20 条半相关的有用。

### 已知限制

- 默认检索是字面重合（字符二元组），不理解同义改写。短口语化问句需要靠标签兜。
- 单写者。多进程并发写会丢数据。
- 全量读写，2000 节点 `recall` 约 20ms（M 系列 Mac，纯 Python）。
- 前端没有虚拟化，节点过千会掉帧。
- `nkb forget` 只能向前衰减，没有"撤销"。

### 未做（见 ROADMAP）

SQLite 后端、embedding 编码器示例、增量布局、批量导入进度条、时间轴回放。
