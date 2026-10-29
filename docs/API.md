# 爱之屋服务 API · 0.4

桌面控制器只监听 loopback。浏览器访问受 Host/Origin 校验，写入需要 JSON；按库请求带 `X-NKB-Library: <id>`，省略时始终是默认库，不随 GUI 当前选中库改变。

| 路由 | 行为 |
|---|---|
| `GET /api/libraries`，`POST /api/libraries {name}` | 列出/创建独立空白库 |
| `POST /api/library/select {library_id}` | 仅改变浏览中的库 |
| `GET /api/libraries/trash` | 已移入回收站的库 |
| `POST /api/libraries/<id>/delete-preview` | 删除前检查连接和数据影响 |
| `POST /api/libraries/<id>/delete`，`POST /api/libraries/<id>/restore` | `{confirm:true}` 移入回收站或恢复；删除撤销连接，恢复不自动重新启用 |
| `POST /api/connections` | `{name,host:agent或harness或api,library_id,session_scope,provider?}` 创建固定归属连接；agent 不需要 provider |
| `GET /api/connections/<id>/config` | 本机接入地址、本地凭证、宿主应用计划；不返回厂商密钥 |
| `POST /api/connections/<id>/provider` | `{base_url,model,api_key?,save_key?}`；空密钥不替换已保存值 |
| `POST /api/connections/<id>/configure` | `apply:false` 预览，`apply:true` 应用自己的 Harness 条目并备份 |
| `POST /api/connections/<id>/enabled` | `{enabled}` 暂停/恢复 |
| `POST /api/connections/<id>/disconnect` | 撤销旧本地凭证，保留记忆 |
| `POST /connections/<id>/v1/chat/completions` | 兼容模型网关；已经保存厂商密钥时 Bearer 使用本地凭证 |
| `POST /api/connections/<id>/events` | 宿主真实事件，Bearer 为本地连接 token；先归档再确认 |
| `POST /api/connections/<id>/context` | 按本连接固定库和会话返回有界记忆材料 |
| `POST /api/connections/<id>/heartbeat` | 心跳不是完成采集证明 |
| `POST /api/connections/<id>/tool` | Bearer 认证的固定库 MCP 读写工具；工具写入不等同宿主自动记录 |
| `POST /api/memory/context` | 当前指定库的有界 `love-house-memory-context/v1` JSON，只读 |
| `POST /api/memory/bootstrap` | 本库身份、人格、有界初始包、覆盖计数与后续目录入口 |
| `POST /api/memory/list` | `{limit?:1..100,cursor?}` 本库全部可用记忆目录，版本绑定的分页游标 |
| `POST /api/memory/read` | `{memory_id,field?:value或assistant或display,offset?,max_chars?,revision?}` 分块读取同库完整文字 |
| `POST /api/sharing/preview` | 只读导出范围与脱敏计数，不调用模型 |
| `POST /api/sharing/download` | `{confirm:true,expected_revision,format:json或markdown,summary_id?}` 完整单库文件内容，不自动上传 |
| `POST /api/sharing/summary` | `{confirm:true,expected_revision}` 显式使用本库整理模型和近24小时预算生成有界阅读索引 |
| `POST /api/sharing/import-preview` | `{content}` 验证完整JSON分享文件，不写库 |
| `POST /api/sharing/import` | `{confirm:true,content,name?}` 建立全新独立库，整理关闭，不改绑任何旧连接 |
| `GET /api/duplicates` | 本库已合并及待检查的重复记录 |
| `POST /api/duplicates/reconcile` | 确认同轮原文副本的来源关系，不删除原始档案 |
| `POST /api/duplicates/confirm`，`POST /api/duplicates/separate` | 验证版本后手动合并或拆开 |
| `GET /api/activity`，`GET /api/activity/<receipt>` | 本库活动及有权限的原始事件 |
| `GET /api/organizer` | 设置、密钥存储元数据、近24小时输入用量、任务与候选 |
| `POST /api/organizer/settings` | 自动整理、模型选择、节奏和预算 |
| `POST /api/organizer/preview` | 只读输入数量预览，绝不调用模型 |
| `POST /api/organizer/run` | 异步排队，返回 queued 不代表完成 |
| `POST /api/organizer/jobs/<id>/retry` | 仅当前库失败/等待重试任务 |
| `POST /api/organizer/candidates/<id>` | `{action:accept或reject}`，验证证据后审阅 |
| `POST /api/memories/<id>/enabled` | `{enabled}`，影响派生记忆召回，可恢复 |
| `POST /api/memories/<id>/correct` | `{text,label?}` 创建用户确认的新有效内容 |
| `POST /api/memories/<id>/forget-preview` | 只读显示原文、派生和备份影响 |
| `POST /api/memories/<id>/forget` | `{confirm:true}` 清理相关记忆、拷贝与缓存，保留无正文删除标记防重放 |
| `GET /api/backups`，`POST /api/backups {}` | 列出/创建本库私有可迁移 JSON 备份 |
| `POST /api/backups/<id>/restore-preview` | 只读验证；恢复模式为新库 |
| `POST /api/backups/<id>/restore` | `{confirm:true,name?}` 恢复为闲置的新库，不复制密钥、不重绑旧连接 |

provider 公共形状为 `{base_url,model,protocol,key_saved,credential_ready,storage}`；storage 是 `keychain`、`session` 或 `none`。API Key 永不由读取接口返回。网关 JSON/SSE 使用 `X-NKB-Session`，重试可提供稳定的 `X-NKB-Request-ID`。

整理设置示例（密钥只能写入，不出现在读回值中）：

```json
{"enabled":true,"provider_mode":"separate","base_url":"https://api.deepseek.com/v1","model":"填写实际可用模型名","api_key":"由用户本机填写","save_key":true,"cadence":"batch","auto_trigger_count":20,"batch_size":6,"daily_call_limit":100,"daily_char_limit":200000}
```

复用高级 API 转发模型使用 `provider_mode:connection` 与当前库的 `connection_id`。`auto_trigger_count:1..500` 严格按累计新记录数触发，达到后排空已选这一组，尾批不重新等待阈值；`0` 保留旧版短暂等待兼容行为。`batch_size` 是单次模型执行上限，不是触发阈值。预算是近24小时输入用量，非账单金额；尝试过的真实网络调用计数，缓存计划应用重试不会重复调用模型。

Agent 的 `config` 返回标准 `host_config.mcpServers` 和 `agent_setup_text`；公开配置没有厂商 Key 或记忆令牌，只有本机私有文件路径。`hook_config` 为轮次结束回调的单独配置，不混入标准 MCP 对象。协议、离线队列与自动重连见 [Agent 连接器](../nkb/service/AGENT_CONNECTOR.md)。

连接工具新增 `memory_bootstrap`、`memory_list`、`memory_read`，服务端固定连接归属，不接受 `library_id` 等未声明字段。带记忆 Bearer 的请求不能使用桌面管理接口；已知本地凭据也不能当成另一个高级 API 连接的厂商 Key。新窗口用同库历史，`session_id` 是来源标识，不是另一个记忆身份。一次上下文有界，完整读取通过目录和分块进行。

分享 JSON 使用 `love-house-memory-share/v1`，文件最多64MiB。为容纳编码开销，只有两个分享导入接口接受至130MiB请求体；其他普通JSON接口保持原有上限。下载需当前预览版本，变化后重新预览。文件含全部未忘记原文、人格、关系与历史状态，可识别凭据/本机路径被隐藏；个人经历仍由分享者检查。可选摘要附带程序记录的覆盖范围，不修改图谱或替代原文，缓存与库及内容版本绑定。

以下保留独立 `Brain` 库的接口文档。底层单库实验服务与桌面多库控制器的职责不同；桌面已停用内置聊天接口，不要求用户迁移聊天窗口。

# API

稳定性标注：**稳定** = 0.x 内不改签名；**实验** = 可能改；**内部** = 不保证。

---

## `nkb.Brain` — 稳定

```python
Brain(data=None, path=None, encode=None, storage=None, config=None, scorer=None)
```

| 参数 | 说明 |
|---|---|
| `data` | 已解析的库字典（一般不用手传） |
| `path` | `brain.json` 路径；给了就自动挂 `JsonFileStorage` |
| `encode` | 编码器：函数 / 名字 / `None`（默认 bigram） |
| `storage` | 自定义存储后端，实现 `load()` / `save()` |
| `config` | `Config` 实例，覆盖默认参数 |
| `scorer` | 自定义点火策略，签名见 `SeedScorer` |

### 建 / 存

| 方法 | 说明 |
|---|---|
| `Brain.new(path=None, name="untitled")` | 新建空库 |
| `Brain.open(path)` | 打开；文件不存在抛 `FileNotFoundError` |
| `.save(path=None)` | 原子写；没有路径抛 `ValidationError` |
| `.persist()` | 有路径就存，没有就跳过（工具层用） |
| `.to_dict()` | 可 JSON 化的完整结构 |

### 写

| 方法 | 说明 |
|---|---|
| `.add(label, text="", kind="concept", tags=None, salience=0.6, id=None, meta=None, impact=0.0) -> str` | 加节点；`impact` 是情绪冲击 -1~1 |
| `.update(nid, **fields) -> dict` | 改 label / text / kind / tags / salience / meta |
| `.remove(nid) -> bool` | 删节点及其所有边 |
| `.link(a, b, w=0.35) -> float` | 连边并加强，返回新权重；自连抛错 |
| `.unlink(a, b) -> bool` | 删边 |
| `.auto_link(nid, top=None, floor=0.0) -> [(id, w)]` | 按字面重合连最近的几个 |

### 学习 / 遗忘

| 方法 | 说明 |
|---|---|
| `.reinforce(ids, lr=None, bump=None) -> {"nodes","pairs"}` | 赫布：两两加强 + 回血 |
| `.forget(now=None) -> {"dropped","dropped_ids","thinned"}` | 按半衰期衰减，跌破阈值删除 |

### 读

| 方法 | 说明 |
|---|---|
| `.recall(query, steps=None, k=None, damping=None, retain=None, kinds=None, min_score=None, include_expired=False, as_of=None) -> dict` | 激活扩散；默认过滤已过期事实 |
| `.supersede(old, new, at=None) -> str` | 旧事实被新事实取代（旧的不删，退出检索） |
| `.invalidate(a, b, at=None) -> bool` | 让一条连接失效 |
| `.history(nid) -> list[dict]` | 被取代的链条 |
| `.commit(what, due=None, **kw) -> str` | 记一条承诺（不衰减） |
| `.due(within=None, now=None) -> list[dict]` | 未了结的承诺 |
| `.resolve(nid, note="") -> dict` | 了结承诺 |
| `.seed_scores(query) -> {id: score}` | 只看点火，不扩散（调参时有用） |
| `.neighbors(nid) -> [(id, w)]` | 按权重降序 |
| `.get(nid) -> dict \| None` | 原始节点 |
| `.stats() -> dict` | 规模与连接强度 |
| `.export() -> dict` | 给可视化 / 前端的扁平结构 |

`recall()` 返回：

```python
{
  "query": str,
  "hits": [ {id, label, kind, tags, score, depth, recalls, salience,
             age_days, path[ids], path_labels[str], text} ],
  "seeds": [ {id, score} ],          # 被点燃的节点
  "trail": [ {from, to, flow, step} ],  # 走过的边，给动画用
  "steps": int, "visited": int,
  "note": str                        # 只有没命中时出现
}
```

没命中时 `hits == []` 且带 `note` —— **不会退化成"随便给几条"**。

---

## `nkb.render` — 稳定

| 函数 | 说明 |
|---|---|
| `to_markdown(result, max_chars=1800, with_path=True) -> str` | 注入 system 的推荐格式，带分数/年龄/路径/护栏句 |
| `to_plain(result, max_chars=1800) -> str` | 纯文本版 |
| `get_renderer(name="markdown")` | 按名字取 |
| `register_renderer(name, fn=None)` | 注册，支持装饰器 |
| `SYSTEM_HINT` | 一句建议塞进 system 的话 |

---

## `nkb.ingest` — 稳定

| 函数 | 说明 |
|---|---|
| `split_markdown(text) -> [(title, body)]` | 按标题切；没有标题按空行切 |
| `ingest_dir(brain, root, kind="doc", mode="heading", link=True, verbose=True) -> {"added","skipped"}` | 幂等：同 `#标题` 不重复导入 |
| `ingest_text(brain, text, source="manual", kind="doc", link=True)` | 导入一段文本 |

---

## `nkb.retrieval` — 稳定

| 名称 | 说明 |
|---|---|
| `bigram(text) -> set[str]` | 默认编码器 |
| `get_encoder(spec)` / `register_encoder(name, fn)` / `available()` | 编码器注册表（支持 entry points） |
| `dice(a, b)` | 集合相似度 |
| `OverlapScorer` | 默认点火策略；换成自己的传 `Brain(scorer=...)` |
| `adjacency(edges)` / `spread_activation(adj, seeds, steps, damping, retain)` | 纯函数，可单独用 |
| `SpreadResult` | `.act / .depth / .parent / .trail / .path(nid)` |

---

## `nkb.storage` — 稳定

| 名称 | 说明 |
|---|---|
| `JsonFileStorage(path, indent=1, fsync=True)` | 原子写（tmp + `os.replace`） |
| `StorageBackend` | 协议：`load() -> dict` / `save(data)` |

---

## `nkb.config` — 稳定

```python
Config(...)          # 字段见下
Config.load("nkb.toml")
Config.from_dict(d)
config.with_env()    # 叠加 NKB_* 环境变量
config.to_dict()
```

字段：`half_life`, `drop_below`, `edge_max`, `edge_half_life`, `seed_floor`,
`steps`, `damping`, `retain`, `k`, `min_score`, `hebbian_lr`, `salience_bump`,
`auto_link_top`。

环境变量：`NKB_STEPS` `NKB_DAMPING` `NKB_K` `NKB_SEED_FLOOR` `NKB_AUTO_LINK_TOP`。

---

## `nkb.adapters` — 实验

| 名称 | 说明 |
|---|---|
| `http.serve(brain, host="127.0.0.1", port=8765)` | 返回 `ThreadingHTTPServer` |
| `mcp.serve(brain)` | stdio 循环 |
| `mcp.handle(brain, msg) -> dict \| None` | 单条消息处理（可单测） |
| `mcp.call_tool(brain, name, args) -> dict` | 工具分发（可单测） |
| `mcp.TOOLS` | 工具 schema 列表 |

---

## `nkb.viz` — 实验

| 名称 | 说明 |
|---|---|
| `build(brain, out) -> Path` | 导出单文件 HTML（数据内嵌） |
| `html_for_serve() -> str` | 服务模式返回模板（数据走 API） |

---

## `nkb.bench` — 实验

| 名称 | 说明 |
|---|---|
| `leave_one_out(brain, k=5)` | 用节点标题查自己，返回 hit_rate / mrr / 漏掉的 |
| `run_probes(brain, probes, k=5)` | 自定义探针，含 `abstain`（必须承认不知道） |
| `format_report(result, verbose=False)` | 打印用 |

## `nkb.core.lifecycle` — 实验

| 名称 | 说明 |
|---|---|
| `reflect(brain, min_cluster=3, max_new=2, rewrite=None)` | 把同标签碎片压成一条 reflection 节点 |
| `tick(brain, now=None)` | 遗忘 → 反思 → 待办，一次做完 |

## `nkb.errors` — 稳定

```
NKBError
├── ValidationError  (ValueError)   入参非法
├── NotFound         (KeyError)     节点/编码器不存在
├── StorageError     (OSError)      读写失败
└── ConfigError      (ValueError)   配置非法
```

## CLI — 稳定

```
nkb [-b brain.json] <命令>

init [--demo] [--force]      add <label> --text --kind --tags --salience
link <a> <b> [-w]            recall <query> [-k --steps --damping --json --md --learn]
get <id>                     stats
ingest <dir> [--kind --mode] forget
serve [--host --port]        mcp
viz [--out]                  export [--out]
doctor                       config [--write]
-V/--version
```

也可以用 `python -m nkb`（等价于 `nkb`）。

## 0.3 记忆生命周期与可视化补充

```python
brain.add(label, text='', kind='episode', tags=None, salience=.6,
          impact=0.0, event_at=None, session_id=None, meta=None)
brain.reinforce(ids, lr=None, bump=None, now=None)
brain.export(as_of=None)                 # 只读完整图谱
brain.preview(days=0, now=None)           # 相同公式，向后推演，不落盘
```

`export/preview`节点包含`state, effective_salience, reinforced, recoverable, recovery_days_left, protected, protection_reason, is_anchor, anchor_info, meta`。
`anchor_info`包含`before_ids, after_ids, bridge_ids, bridges, context_snippets`；摘录有`id,label,excerpt,event_at,session_id,created,captured_at,is_excerpt,source_present,source_available`。

边包含`effective_w, stored_w, valid_from, valid_to, active, state, anchor_relations`。状态投影统一用于检索、前端与维护；读操作不创建记忆或学习连接。过去`as_of`不会提前返回之后才产生的上下文。

默认规则：`recovery_days=200, anchor_threshold=.75, important_threshold=.95, context_before=2, context_after=2, context_window_hours=6, bridge_window_hours=24, bridge_max_events=6, max_nodes=10000`。全部保存在知识库配置中；`NKB_RECOVERY_DAYS/NKB_ANCHOR_THRESHOLD/NKB_MAX_NODES`可覆盖。

HTTP新增`POST /api/preview {days}`、`GET /api/node?id=...`。`POST /api/forget`只允许当前维护；不接受未来删除模拟。同源、可信Host、严格JSON与有限数值验证适用于所有接口。

MCP新增`kb_preview`。`kb_recall`缺省`learn=false`，明确传`true`才写入巩固。

`reflect`返回可选`skip_reasons`：容量不足时`reason='capacity_limit'`，跳过该次归纳，不驱逐其来源事件或产生残缺反思。

## 0.3.1 伴侣与 Harness 接入

- `GET /api/ai/status`：是否有环境密钥、模型和人设；不返回密钥。
- `POST /api/ai/profile {name,persona,user_name}`：保存稳定人设资料。
- `POST /api/ai/context {query,session_id}`：只读生成相关记忆、长期基线和最多六轮历史；返回可追溯节点ID、材料包和完整messages。
- `POST /api/ai/chat {message,session_id,request_id,api_key?,model?}`：显式调用官方DeepSeek，网络期间不占图谱操作锁，成功回复才保存用户原话/助手回复；密钥不落盘。相同会话与请求编号重试不会重复计入已有对话。
- `POST /api/ai/remember {text,kind,important,session_id}`：用户明确确认的记忆。
- `POST /api/ai/record {user,assistant,session_id,request_id}`：保存已有API或网页对话的两个角色原文。
- `POST /api/ai/event {text,source_url,outcome,session_id,request_id}`：保存有来源的工具观察，outcome区分observed/success/failed，不冒充用户确认。来源URL去除认证信息/查询与fragment。
- `GET /api/ai/harness`：返回适用于官方`@deepseek-ai/dsh-mcp-client`的Overlay配置及自检入口。
- `POST /api/ai/harness/context`：总是验证个人记忆服务，示例界面不冒充个人库。

例库不接受陪伴记忆写入和实际API聊天，避免把演示材料混成用户经历。API密钥仅用于本次调用或从`DEEPSEEK_API_KEY`读取；不写入知识库、配置、日志或MCP工具响应。
