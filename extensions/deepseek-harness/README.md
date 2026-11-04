# 爱之屋 DeepSeek Harness 宿主自动存档适配器（0.4.1）

此扩展监听真正的宿主事件，不依赖模型决定是否调用记忆 MCP 工具。爱之屋服务接收和保存记录，
宿主继续负责对话、模型调用与网页操作。每个连接由服务端固定绑定独立记忆库，切换爱之屋界面不会改变归档目标。

支持 **DeepSeek Harness 0.2.1-rc.3、0.2.1-rc.5 / Cordis 4.0.5 / Node ≥24.9**。契约来自官方 npm 精确版本的公开类型：

- `@deepseek-ai/dsh-session@0.2.1-rc.3`：`session/event(session,event)`，在提交后发布原始日志事件。
- `@deepseek-ai/dsh-agent@0.2.1-rc.3`：`agent/pre-step(payload,next)`，用真实上下文替换本步消息。
- `@deepseek-ai/dsh-llm@0.2.1-rc.3`：稳定 `message.id`、真实 `role/source`、附件引用与 `toolCallId`。

官方仓库当前 master `f3803c96974ad4a94195fb97e5c637e9c2a3afe3` 也经过源码审阅，但不据此声称已验证所有后续版本。
精确来源及支持矩阵见 `host-contract.json`。加载方式使用官方 Cordis 文件模块和 Overlay，未修改或替换 Harness asar。
2026-10-30 逐文件核对 rc.5 的 `dsh-agent/session/llm/scope` 官方 npm 包：除 `package.json` 中的
精确版本字符串，94 个文件与 rc.3 完全一致；在独立 rc.5 SDK 依赖中通过同一套 13 项真实
Cordis/SessionStore 与插件测试，包括完整轮次上报、会话隔离和离线恢复。校验来源和散列留在支持矩阵中。

## 快速配置

通过爱之屋向导选择库和连接，生成计划，再应用。`configure.py` 提供控制器直接调用的标准库入口：

```python
detect(app_path=None, profile_dir=None)
configure(connection_config, apply=False, app_path=None)  # 仅读取元数据、返回计划
configure(connection_config, apply=True, app_path=None)   # 备份后添加本连接条目
set_enabled(connection_config, enabled=False, remove=False, app_path=None)
```

控制器入参 `config` 支持 `connectionId/connectionToken/libraryId/sessionScope/runtimeDir`。
也接受 snake_case。可通过 `host_options.profile_dir` 明确选择另一个 profile。
默认路径由当前用户 home 和实际 App 路径推导，项目和公开模板没有个人用户名。

桌面向导调用 Python 配置器：Windows 会检查卸载注册表中的 `InstallLocation` 和常见安装目录，
也接受安装目录或 `DeepSeek Harness.exe` 的明确路径。版本从 `resources/app.asar` 或未打包的
`resources/app` 内的官方 package 元数据读取；不会启动宿主、解包/修改 asar，或读取 credentials。
默认 profile 是 `$DSH_HOME/profiles/desktop`（设置 `DSH_HOME` 时）或 `~/.dsh/profiles/desktop`，
自定义 profile 需明确指定。检测和计划均只读；应用成功才把两个路径保存到当前连接，重启和暂停复用此绑定。
识别已有 `cordis.yml` 的旧 profile，也识别官方 `initProfile` 生成的私有 `package.json`
（含 `dsh.profile.bundles` 字符串数组）；后者尚未启动时可以没有由宿主生成的 `cordis.yml`。
配置器保留 manifest，仅写自己的 patch 和插件文件，不替宿主创建 root config，也不把普通 npm 项目当成 profile。
发现程序与版本不代表已经自动存档；插件收到真实完整轮次回执后才算接通。
未来版本不只靠版本白名单：Python 会只读比对已安装 `dsh-agent/session/llm/scope` 的 37 个运行 JS
文件及模块入口、依赖等元数据，仅把同版 SDK 精确版本归一化；Cordis 核心仍须符合已验证版本。
与 `host-contract-fingerprints.json` 的已验证指纹完全一致时，生成绑定资源目录的契约 descriptor 后自动兼容。
插件每次启动会再次检查实际文件；宿主后续升级但指纹不变时自动重连并报告实际版本，接口代码或依赖变化则拒绝自动配置/加载，
检测结果会列出不匹配的包或文件。只读取固定的官方 SDK 元数据和代码字节，检测过程不导入或执行安装目录里的 JS。
独立 Node `dist/configure.js` CLI 的自动探测目前仍限 macOS；Windows 请使用桌面向导/Python 配置器。

每个连接有独立 hash 条目、标记块、Overlay、私有连接文件和 outbox。安装 A、安装 B、重新配置 A 不会删除 B。
配置器只更新自己的标记块，先备份既有 patch；其他配置字节保留，不读取或修改 Harness credentials。
连接 token 写入独立 `0600` 文件，Overlay 只引用该路径，计划与日志不回传 token。
生成文件前请使用向导应用配置；单独复制一个指向尚不存在私有文件的 Overlay 不能完成接入。

`dist/index.js` 已打包，只依赖 Node 内置模块；复制到其他机器后不依赖开发 cwd 或项目 node_modules。
安装目录有自己的 `type:module` 包声明。宿主插件可多实例复用，每个实例都只有自己的配置、监听与队列。

## 每轮实际发生什么

1. 已提交的真实 user、assistant、tool/call、tool/result 及 turn 边界自动进入私有 outbox。
2. 请求选定连接的上下文后，在 `agent/pre-step` 中加入带明确 producer 的 recall 材料。已经固定的根会话在本轮无新 human 时，也可用该会话公开已提交的最近 human 任务取回相关记忆，见下文范围。
3. 自己注入的 synthetic 消息不会再次采入记忆；其他上下文也不会冒充人类发言。
4. `turn/end` 附带 normalized 记录，仅 completed、无 interrupted 且确实看到 start 时标为 complete。已有真实用户输入仍只保存一份 turn，不额外生成 output。
5. 原始事件发往已认证连接；只有 `accepted:true` 才删除 outbox。该 ACK 只说明私有 journal 已落盘，
   不代表图谱投影已经成功。图谱 pending/retry 由服务端活动状态显示。

保留原始角色、message ID、call ID 与附件引用，不去读取引用文件，不把引用假称附件全文。
递归移除明确 credential 字段及可解析工具参数里的 credential 键；用户实际发言的 text 不被改写。
不收集宿主 credentials、环境变量或 request/header 配置快照。normalized 只取可见正文，原始失败尝试保留出处。

### 已绑定窗口里的独立助手输出

0.4.1 补充了没有真实用户输入的独立最终输出。仅在明确固定会话 ID，或 `next_session` 已被真实 human 发言绑定之后的同一个根会话中启用；显式多窗口 `connection` 范围保留原有 turn 路径，本次不扩大独立输出范围。子代理不采集，也不会注入这份根会话记忆。

必须先观察到本轮 start，最终 end 的 turn 编号一致且 `reason.kind=completed`。本轮没有真实 human 输入，最后一条已提交 `assistant/message` 来自 model、包含稳定消息 ID 和非空可见文字，且没有工具调用或其他未知内容块，才生成 `type=output, role=assistant, text`。后面还有工具调用/结果、新步骤或未形成表面消息的 attempt 时，旧助手文字不会冒充最终输出。只取最后一条最终正文，不拼接此前工具步骤，不把调度或 synthetic 内容补造为 user。

`assistant/message` 本身只作为既有原始事件保存，不能提前生成独立 output；取消、中断、错误、缺少 turn/start 或没有明确最终文字仍只保留已有原始证据路径。独立输出不触发首次窗口 claim，也不允许后台另一根会话自动加入。

### 下一次无新输入的工作前取回记忆

当同一个根会话已经固定，或者 `next_session` 已由真实 human 绑定，且本轮 start 已被观察、turn 编号一致、没有 interrupted 时，`agent/pre-step` 即使没有新 human 消息，也会取回一次相关记忆。检索问题只来自这个 `payload.agent.session` 的公开 `deriveMessages()`：选择最新 `role=user`、`source.kind=user` 的可见文字。它读取 SessionStore 已提交的模型可见 surface，不读取原始事件快照、其他会话、磁盘文件、请求头或私有推理；影子替换后的旧表面消息也不会绕过公开投影重新出现。

这份旧任务只用作 query，不会被重新上报成 user，不会创建新 turn 或取得窗口 claim。公开投影有效但没有 human 任务文字时，只请求固定的“当前已绑定存档的长期基线和约定”。公开方法缺失或读取失败则不猜任务，聊天继续。资料注入使用现有的明确 `neural-knowledge-context` producer，一轮成功取回后不按 step 重复查询，自身资料仍不会回流采集。

未绑定窗口、其他窗口、子代理、显式多窗口 `connection` 的无 human 请求、缺少本轮 start 或已中断的轮次都不进入这条新增读取路径。原有真实 human 请求仍沿用原来的绑定与注入流程。以上使用真实 rc.3 Cordis/SessionStore 合成事件完成离线验收，尚不能称为用户实际无人值守任务的实机验收，也不代表能观察其他执行器。支持判断仍基于已有精确宿主版本与公开事件契约；没有添加每次加载时重新校验任意 asar 的密码学指纹机制。

`session_scope=connection` 表示显式连接范围，精确会话 ID 只接收该窗口。
`next_session` 在首个真实 human 消息前绑定，启动通知和 synthetic 内容不会抢占；绑定会持久保存。
同进程多个待绑定实例不会抢同一个窗口。暂停不丢失会话 claim，也不会把恢复后的残缺轮次伪装成完整轮次。

每次采集、注入、心跳和重试前重读私有 `enabled`。暂停停止新采集及重试，旧 outbox 保留供恢复；
断开可移除仅本连接的宿主条目。心跳只代表插件在线，不代表真实对话已经存档。

## 服务协议

发现当前 home 下 `.runtime/*.json` 的 `controller_port` 与 `service_version:0.4.x`，每次发送重新发现并检查健康。
不会回退到旧版显示端口或个人端口。默认直连回环，不使用环境代理，不跟随重定向。
远端服务必须显式配置 `base_url`、`allow_remote:true` 并使用 HTTPS。

- `POST /api/connections/{id}/events`，Bearer token；稳定 body 为 `{session_id,event_id,event_type,seq,time,record}`。
- `record={schema:'deepseek-harness-event/v1',host_id,host_version,raw_event,normalized?}`，删密钥时有 `redacted_fields`。
- normalized turn：`{type:'turn',turn_id,status,reason,user,assistant,messages}`。
- normalized output：`{type:'output',role:'assistant',text,turn_id,status:'complete',reason:'completed',evidence:{assistant_message_id}}`。它是助手陈述，不是完整对话或已确认用户事实。
- normalized tool：`{type:'tool',call_id,tool_name,turn_id,outcome,content}`。工具无错误只标 observed，不擅自宣称网页业务成功。
- `POST /api/connections/{id}/context`，同认证，`{session_id,query}` 返回真实 `packet`。
- `POST /api/connections/{id}/heartbeat` 只报告在线，不建立虚构会话或完整记录。

事件标识来自持久 host ID、真实 session ID、原始 seq 和事件类型。重试读取相同 outbox 文件，
不会把当前时间或尝试次数加入原事件而破坏幂等。连接配置发生变化时也不会把旧队列改送另一个库。
未加载插件的历史不自动扫描；磁盘写入失败会明确报错，不能声称那些记录已进入队列。

## 不支持版本的备用方式

`dist/proxy.js` 是可实际转发 OpenAI 兼容聊天请求的显式 API 代理，支持 JSON 与 SSE；
需将客户端 provider 流量明确路由到它。它只能看到经过代理的 provider 请求/回复，
没有原生窗口身份时使用明确配置的 proxy namespace，不能观察未回传 provider 的工具结果。
因此它始终标记 wire-only / partial，不冒充完整宿主自动存档；暂停时继续透明透传，停止注入和归档。
正常 rc.3/rc.5 用户应选择宿主插件方式。此项目不会自行更换模型、读取 provider API key 或发起付费模型测试。

## 构建与离线验收

```sh
npm ci --ignore-scripts --legacy-peer-deps
npm run build
npm test
```

测试使用 mock 宿主与本地 mock HTTP，没有真实模型调用。覆盖完整角色/附件引用、工具失败、
取消/partial、outbox 重启重放、真实 pre-step 注入、synthetic 排除、多连接配置和停用、
不同会话隔离、可运行的降级代理。支持矩阵的公开类型检查与离线测试不等于用户现有会话已经完成实际归档；
仍须在插件加载后收到一轮真实记录的持久回执，才能宣称该连接已经自动存档。

## Linux/macOS 的官方 npm CLI 验收

可显式指定官方 `@deepseek-ai/dsh` 的包目录和隔离 profile，已验证精确版本继续使用相同宿主插件。npm CLI 的未知版本目前保守拒绝，不套用 Electron 安装包的资源布局判断。仓库 `scripts/verify_harness_connection.py` 用真实 CLI、临时 `DSH_HOME`、本机合成模型和临时记忆服务，分别验证 Harness/原 MCP 连接自动保存及第二会话隔离；任何一项失败都会返回非零退出码。它不读取已有聊天配置或真实模型密钥。

独立输出额外覆盖固定窗口、human 绑定后输出、未绑定不能自抢窗口、中间/失败步骤排除、turn 编号一致、子代理隔离、离线稳定 ID 重放，以及官方精确 rc.3 的真实 Cordis/SessionStore 合成事件。没有真实模型调用，也没有修改用户 Harness 配置。

无新 human 的行动前召回还覆盖固定会话与已绑定 next_session、最近公开 human 任务选择、固定基线、同轮不重复注入、自身 recall 不变成新 user，以及不允许的窗口在读取公开历史之前就被排除。
