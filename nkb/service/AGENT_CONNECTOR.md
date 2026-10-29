# 本机 Agent 记忆连接器

这条连接只接入爱之屋记忆服务，**不需要模型厂商 API Key**，也不转发模型生成请求。聊天模型仍由用户自己的 Agent 宿主管理。每条连接固定一个记忆库；切换爱之屋里正在浏览的库不会改绑。

## 第一次连接

由爱之屋的 `make_agent_config(data_dir, connection_secret, persist=True)` 生成：

- 一个标准的 `mcpServers` 配置对象，可保存到支持 MCP stdio 的本机 Agent 宿主。
- `agent-connections/<connection_id>.json` 私有连接文件，权限 0600；其中只有爱之屋连接令牌和本机路径，没有模型厂商密钥。
- 一个独立的 `hook_config`，供支持轮次结束回调的宿主安装自动存档。不要把这个非标准对象混进只接受 `mcpServers` 的配置文件。

默认路径会根据完整源码或 `.app/Contents/Resources` 动态生成，命令参数只含私有配置文件路径，不含令牌。打包版会设置专用 `PYTHONHOME`；源码版使用当前 Python。桌面包需包含 `agent_memory_bridge.py`、`agent_memory_hook.py` 及原有 `harness_bridge.py`。仅安装一个不含桌面适配器的 wheel 不等于这些脚本已存在。

MCP 初始化与工具列表在爱之屋暂未启动时仍可加载；`memory_status` 会如实显示尚未连接。需要宿主实际加载配置后才能认为工具已接入，模型口头声称“连接成功”不是证据。

## 自动存档的边界

MCP 工具本身是模型主动调用的。自动记录每一轮需要宿主在真实回合结束时调用以下脚本，把实际角色原话作为 stdin JSON：

```text
python3 agent_memory_hook.py --connection-config <爱之屋生成的私有文件路径>
```

```json
{"session_id":"宿主的稳定窗口ID","turn_id":"宿主的真实轮次ID","status":"complete","user":"实际用户发言","assistant":"实际最终回复"}
```

中断或未完成内容应使用 `status:"partial"`，只保留原文档案，不冒充完整记忆。工具观察使用 `type:"tool"`、`text`、`call_id` 及如实的 `outcome`。没有回调时，宿主只能通过记忆工具显式读写，不能宣传自动监听任意聊天窗口。

来源协议：

- 宿主回调：`record.schema=love-house-agent-hook/v1`，`normalized.origin=agent_host_hook`。
- MCP 手动补录：`record.schema=love-house-agent-tool/v1`，`normalized.origin=manual_record`。

服务端用这一区别维持“工具可用”和“已验证收到自动记录”的状态，不把心跳或一次主动补录冒充被动采集。用户已经安装回调时，模型不应每轮再手动保存同一对话。

## 关闭再打开

连接 ID、库 ID 和令牌保存在本机，不因换聊天模型或重新启动电脑而改变。SDK 每次请求扫描私有 `runtime_dir` 的就绪文件，只访问 `127.0.0.1`，检查 PID 和兼容协议。端口变化也会重新发现。MCP bridge 每 15 秒尝试心跳与重连；Agent 宿主下次加载同一份配置即可继续，不需要每次在爱之屋重新绑定。

宿主已真实提交、但爱之屋暂时不在线的记录会先原子写入 0600 outbox。仅服务返回 `accepted:true` 后才清掉本地待发送文件。`queued_offline` 表示仅本机队列已落盘，**不是服务端已保存**。爱之屋启动后会扫描已启用连接的 outbox；bridge 后台也会继续重试。未上报给 SDK 的聊天无法凭空补录。

固定事件 ID 重试不会重复记忆；同 ID 不同内容不会覆盖原文件。队列最多 5000 事件或 128 MiB，满或磁盘失败会明确报错，不驱逐旧原文、不假报成功。HTTP 409 或损坏的单条记录仍保留，不阻塞其他独立事件发送。

暂停/断开时服务端重写私有文件 `enabled/revoked/token`；客户端每次采集与交付前重读，暂停后不继续收新记录。撤销令牌不会被 SDK 换成新库或新身份。故意忘记的旧事件即使被 ACK，也返回 `forgotten`，不会宣称已重新存档。

## 本机与安全范围

这不是跨设备公网连接。禁止使用 `HTTP_PROXY` 或重定向离开本机，也不会读取 KeyStore 或模型凭据。`source_url` 去掉查询与片段，拒绝 URL 中认证信息。Hook 只保留规范事件字段，不把额外 headers、API Key、环境变量或未知宿主字段塞入原文档案。

原文角色内容是记忆数据，JSON 字符串不会执行。记忆连接令牌仍是此库的本机读写凭证，放在私有文件中；公开配置代码只有文件路径。整理模型如被用户单独启用，其模型 API Key 另由爱之屋的凭据存储管理，与这条连接无关。

## API

```python
client = AgentClient(private_config_path)
client.tool("memory_context", {"query":"当前话题", "session_id":"实际窗口ID"})
client.submit_hook(actual_host_event)
client.submit_tool_record("memory_record_turn", actual_tool_arguments)
client.heartbeat()
client.drain(limit=50)
client.start()  # stdio bridge 生命周期内的后台重连
client.stop()
```

所有读写只走绑定连接的认证接口：`/api/connections/<id>/tool`、`events` 与 `heartbeat`。SDK 不选择 GUI 当前库、不打开 brain 文件、不创建另一个图谱写者。
