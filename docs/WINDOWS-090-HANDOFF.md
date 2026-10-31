# 爱之屋 0.9.0：Windows 更新交接

这份交接对应 macOS 0.9.0 的共享功能，基础源码提交为 `77f00d13385fc84dd5af418fb5a705bb299a14a7`，分支为 `codex/output-memory-090`；后续仅补文档的提交可一并获取。产品版本为0.9.0，服务协议继续0.4.0，AstrBot实验插件0.2.0，Harness适配器0.4.1。macOS构建号12不应直接充当Windows构建号。

**从另一台电脑上最新、已验证的Windows分支继续合并。** 本次没有修改 `desktop/windows_app.py`、`desktop/windows-installer.iss`、`desktop/requirements-windows.txt`、`scripts/build_windows.py` 或Windows发布工作流。不要用这份Mac工作区整目录覆盖Windows工程，尤其保留已完成的WebView2检测、启动诊断、安装和缓存清理修复。若Windows线上版本已经高于0.9.0，只合入需要的功能，并按现有版本策略递增，不降级版本或覆盖已有发布资产。

先读 [如何连接](如何连接.md)、[同鱼多平台接入](同鱼多平台接入.md) 和 [Mac 0.9验证说明](MACOS-090-VERIFICATION.md)。项目只接收已登记运行程序报送的可见资料，并向同一存档返回相关记忆；不能把配置成功当作“所有软件行为都已自动采集”。

## 1. 同步哪些共享改动

| 文件范围 | 最终行为及合并注意 |
| --- | --- |
| `service/source_client.py`、`service/agent_sources.py`、`service/connections.py`、`service/host.py`、`companion/ingestion.py` | 新增独立助手输出 `output`。无用户输入时也可保存最终文字，角色始终为assistant，不伪造user或完整turn；正文统一采用已校验的`text`，不能被旧工具`content`别名覆盖。稳定事件重试幂等，不把不同真实任务里相同的文字当作同一次事件。 |
| `organizer/state.py`、`rules.py`、`experiences.py`、`companion/memory.py`、`structured.py`、`core/brain.py` | 整理器可建立有逐字依据的历史助手陈述；这不等于确认它声称的现实事实。整理／确认记忆独立检索，原文有界补充；指定平台近期更正仍优先。修改来源后旧依据失效，不能靠旧索引继续回忆。 |
| `adapters/http.py`、`service/host.py` | 资料包在同库操作锁内读取现有索引，去掉回环HTTP与整图副本重建。接收请求只同步应用当前回执，查询不再同步排空所有积压；后台worker继续处理待交记录，待处理数量必须准确。 |
| `service/connections.py`、`service/agent_sources.py`、`companion/structured.py` | 数据库增补`last_recall`元数据、输出计数及待处理索引。资料包`source_coverage`和来源卡只统计实际返回的整理／原始／其他材料，不保存查询正文，不声称模型一定采纳。升级保留原SQLite、原存档与原凭据。 |
| `viz/web/connection-ux.js`、`agent-sources-ui.js`、新增`connection-help-ui.js`、`viz/builder.py` | 按实际运行程序选择Harness、AstrBot或其他MCP接入。新增“怎么连接？”帮助，说明交给谁、填在哪里、如何验证。登记的AstrBot来源直接进入来源配置，避免误入通用MCP配置。切库后不得继续显示或操作旧库的私有路径，关闭／Esc返回正确焦点。 |
| `extensions/astrbot-love-house/` | 实验插件升级0.2.0，详见下一节；随包`source_client.py`须与共享SDK字节一致。 |
| `extensions/deepseek-harness/`、`nkb/service/harness/` | 适配器升级0.4.1；源码、预构建JS、配置器、README和契约声明需同步。只复制源码、不更新分发副本会让安装后的行为仍停留在旧版。 |

外部平台参与者说“导入人格”时，保留原话和待本机确认提示，不直接覆盖存档人格。原来的私有窗口显式人格导入流程保持兼容。不要把任意QQ发言者识别为存档主人。

## 2. 适配器升级规则

### AstrBot 0.2.0

- 接口基线为AstrBot 4.29.3。`on_agent_begin`在默认runner绕过普通模型请求hook时补充临时记忆；已有请求材料时不重复添加。临时资料进入模型请求，不写回宿主长期对话历史，不改system人格。
- 完整对话仍保存一次turn。没有已保存用户输入时，最终助手文字独立保存为output。流片、中间工具步骤、空文字、停止／错误状态不能伪装成正常完成输出。
- `after_message_sent`仅写插件私有`host_send_stages`元信息，不再生成可回忆观察，也不送去整理。纯状态命令不应新增助手经历；历史资料和待交队列不因升级被清空。
- 新配置`record_scheduled_outputs`默认false。只有用户显式打开后才处理官方`CronMessageEvent`，仍要求已登记UMO和实际平台实例一致；调度文本只用于查询，不保存为主人发言。保留原平台，附`execution_origin=scheduled`、`actual_platform=cron`。
- 更新已有插件时保留用户配置、UMO、私有来源路径、journal和SDK队列。不能因为新增开关而静默扩大采集范围。

### Harness 0.4.1

- 契约固定支持运行时`0.2.1-rc.3`。这只是已核对的版本契约，不是对任意后续版本的兼容承诺。
- 只为已固定、或已由真人绑定的根会话补齐无新用户输入时的最终输出与行动前回忆。必须有对应开始／完成状态和最终可见文字；中断、子代理、其他窗口、未绑定窗口不得靠独立输出自抢绑定。
- 无新用户输入时，查询只读取当前会话公开`Session.deriveMessages()`投影；不可读取私有推理或另一个会话。公开投影不可用时不猜任务；未产生新的用户发言或合成turn。
- Windows专用Harness安装／发现／重载仍需在Windows实机确认。Mac的契约与离线测试不等于Windows桌面集成已经通过；无法确认时保留明确的不支持说明，不伪装为一键成功。

## 3. Windows打包必须核对

1. 保持原每用户数据目录`%LOCALAPPDATA%\LoveHouse`，不要迁移到安装目录，也不要因名称或版本变化另建空库。保留已有Controller端口恢复、单写者锁、Bridge／Hook独立控制台exe及Windows凭据保护。
2. `connection-help-ui.js`已由builder内联到页面。打包后实际打开帮助，核对脚本只注入一次、像素字体与按钮资源正常、展开／收起和窄窗口不遮挡主要操作。不要只测源码浏览器。
3. **补齐AstrBot插件导出。** 当前这份源码的Windows `build_windows.py:data_files()`没有收录`extensions/astrbot-love-house`，而`host.astrbot_package()`会读取其中`package.py`。冻结包仅合入共享页面，不能保证“导出AstrBot实验插件”可用。请沿用Windows最新实现，或添加固定源码白名单／确定性ZIP及受控导出入口，确保完整包内能导出`LoveHouse-AstrBot-0.2.0-experimental.zip`。不得从用户运行目录搜集插件，也不允许网页传任意保存路径。若保留浏览器下载方案，要验证真实下载成功；失败不能显示成功。原生保存另测取消、异源与错误处理。
4. AstrBot ZIP仅含`package.py`定义的8份插件源码。私有配置、Key、消息原文、SQLite、队列、`node_modules`和测试报告不能进安装包；该ZIP与构建时源码打包结果应有相同SHA256。
5. 不回退另一台电脑已有WebView2修复。检查缺运行时、已有运行时、非默认安装路径和重复启动时分别给出准确提示；不要把任何启动失败统一解释为“另一个窗口已打开”。依赖下载／安装按既有用户可见流程执行。
6. `LICENSE`、`NOTICE`、第三方字体／WebView2等许可继续随包。自有代码公开下载、PolyForm Noncommercial 1.0.0、保留作者myflww署名，已有安装包不覆盖发布。

## 4. 验收顺序与通过标准

先用临时库和假凭据跑完整回归，不读取其他软件Key、不增加真实模型费用。以下命令在Windows专用构建环境执行，解释器和Node沿用项目固定环境：

```powershell
python -m unittest discover -s tests -q
python -m unittest discover -s desktop -p "test_*.py" -q
python extensions/astrbot-love-house/package.py --check
python scripts/sync_harness_assets.py
```

`sync_harness_assets.py`是同步命令，没有`--check`选项。执行后查看diff，并逐文件比较受控副本；预期同版本源码不应产生意外差异。Harness目录另运行`npm ci`、`npm test`、`npm run typecheck`，需要重新编译时运行`npm run build`并再次同步分发副本。Node应符合该目录声明的版本要求。

本次重点回归：`test_visible_outputs`、`test_output_memory_organizer`、`test_organized_retrieval`、`test_platform_recent_recall`、`test_connection_help_ui`、`test_astrbot_adapter`，并保留原窗口隐私、跨库隔离、来源、离线队列、备份／分享、遗忘、重复、保留策略及Windows打包测试。普通环境跳过的固定官方接口测试应单列；可在独立AstrBot 4.29.3开发环境通过`ASTRBOT_OFFLINE_SOURCE`指定官方源码运行，不能把skip写成通过。

实机检查至少包括：

- 两个记忆库和一个未登记窗口：登记来源只写固定库，切换页面不改变归属；另一库查询不到口令；未登记窗口不进入本地待交队列或服务端原始档案。
- 同一事件重复回调只存一次；不同任务的相同文字仍分别保留。普通对话不额外再产生独立output；状态命令不新增可回忆节点。失败／中断不能算完整输出。
- 关爱之屋后产生合成记录，再重开：待交先持久保存，恢复后补交一次。重启Windows应用后端口发现、原来源、库身份、原记忆和凭据保持，后台任务不扩容授权范围。
- 有整理／确认记忆且有更多原始材料：实际资料包包含整理节点，来源计数准确；平台近期更正优先。编辑或忘记来源后对应旧整理依据不得继续被召回。
- 外部参与者的“导入人格”原话仍能查到，但不能改本机人格；来源Bearer不能读取其他库、登记新来源或调用管理导出。
- 配置帮助明确说明：配置给运行程序或有权限的配置助手，发进普通QQ聊天不等于接入；记忆连接不需要聊天模型Key，整理Key仅处理已接收资料。本机路径不能直接复制到云服务器／另一台设备使用。

按Windows最新构建流程生成便携ZIP与安装版；当前脚本入口为`python scripts/build_windows.py`，需在Windows x64原生环境执行。至少核验包内backend smoke、包内WebView2 native smoke、安装后同样的native smoke及报告清理状态，再生成SHA256并发布；Mac产物不能替代这些报告。

## 5. 已有证据与未验证部分

Mac这轮完成806项后端回归（普通环境跳过2项后另作固定版本验证）、17项桌面检查、37项AstrBot固定版本检查、23项Harness行为检查和类型检查。真实模型的3次受控实验验证了：从已有QQ助手输出生成有来源的整理陈述，通过正常跨来源检索交给全新接收会话后能回答新旧口令，空记忆对照无法回答。它证明这条整理记忆通路能实际使用，没有证明所有陈述是现实事实。

新增Cron／Harness无人输入路径尚未完成各平台全套实机验收；SnowLuma、NapCat、云端、其他runner、纯语音／图片及长期运行仍须单独验证。Mac性能数字不能作为Windows时延保证，当前大库仍使用JSON存储。

交付时在Windows自己的报告中分开写：共享回归、打包、原生安装、真实采集／回忆、未覆盖项。不要上传用户记忆、Key、私有连接文件或真实聊天截图。升级失败应保留原应用回滚副本及受管单库备份；回退前先停止新版写者，不让两个版本同时写同一库。
