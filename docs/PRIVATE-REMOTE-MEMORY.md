# 自有电脑/服务器上的手机与远程 Agent 接入

远程网关使用同一个 `MemoryHost`、连接库和记忆文件。手机是这份记忆的入口，不会把旧离线网页库自动上传或新建成另一份记忆。
本机控制器继续只监听 loopback；新增网关默认也只绑定 `127.0.0.1`。代码交付不代表已部署到公网。

## 启动与单写入者

从完整源码运行 `scripts/run_remote_memory.py`，使用 Python 3.11 或以上。明确指定自己的持久数据目录、HTTPS 源地址、管理员口令环境变量名称和 TLS 文件：

```sh
python3 scripts/run_remote_memory.py \
  --data-dir /private/love-house-data \
  --public-origin https://memory.example.com \
  --admin-token-env LOVE_HOUSE_REMOTE_ADMIN \
  --tls-cert /private/tls/fullchain.pem \
  --tls-key /private/tls/privkey.pem
```

`LOVE_HOUSE_REMOTE_ADMIN` 须由用户在进程环境中提供至少 32 字符的随机私密口令。不要把口令或 Agent 凭证放到命令行、URL、截图或日志。
`--bind` 默认 `127.0.0.1`，`--port` 默认 `9443`；实际 HTTPS 入口的域名/端口必须与 `--public-origin` 一致。
需要直接监听自己的网卡时必须明确提供 `--bind`，并使用 TLS；程序不会自动配置 DNS、防火墙、路由器、隧道、证书签发或系统服务。

启动器与桌面应用使用同一个 `.desktop-writer.lock`，同一目录已有桌面/服务写入者时不能再启动第二个写入进程。
通过此启动器运行时，可以从受保护的 `/app/` 使用同份完整界面；需要在已运行桌面进程内加入口时，应让网关共享该进程的 `MemoryHost`，不要绕过锁另开写入者。

## 明确可信的本机 HTTPS 反代

可以不向 Python 提供证书，而明确指定 `--proxy-secret-env LOVE_HOUSE_PROXY_SECRET`。此模式仅允许网关绑定 loopback。
用户自己的 HTTPS 反代须覆盖以下请求头，不能从外部原样转发同名头：

- `Host`：与 `--public-origin` 相同的域名和端口。
- `X-Forwarded-Proto: https`。
- `X-LoveHouse-Proxy-Key`：用户在指定环境变量中配置的至少 32 字符反代私密口令。

缺少该密钥、来源不是 loopback、协议不是 HTTPS 或 Host 不符，网关均拒绝。
本机控制器端口不会通过任意 URL 转发功能开放；网关管理代理仅连接自己持有的 `controller_port` 和固定业务 API 白名单。

## 手机入口和权限

手机访问 `https://自己的服务/mobile`，在同源页面登录管理员后，选择现有记忆库、创建通用 Agent 连接、复制配置。
`/app/` 使用最新共享界面，读取经历、整理规则、记忆规律等功能仍操作同一个服务。

管理员与 Agent 权限分开：

- 管理员登录生成随机、八小时有效的 `__Host-LoveHouseAdmin` cookie，带 `HttpOnly; Secure; SameSite=Strict; Path=/`。
- 管理员写请求必须同时具有正确 `Origin`、管理员 cookie 和 `X-LoveHouse-CSRF`；登录只接受同源请求。
- Agent 静态 Bearer 只访问自己固定的连接与记忆库，不能列出其他库、访问管理 API、打开 `/app/` 或代替管理员 cookie。
- URL 不承载凭证，不配置通配 CORS，不重定向认证请求。管理状态和凭证响应均为 `Cache-Control: no-store`。

静态 Bearer 用于用户私有部署、允许自定义 Authorization 请求头的 Agent 客户端。本实现没有 OAuth 授权服务器，不承诺只能使用 OAuth 的托管连接器可以直接接入。

## 配置与自动上报

创建接口返回 `remote_config`、`mcp_config`、`agent_setup_text` 和 `hook_config`，只包含 HTTPS URL 和显式请求头，没有本机 exe、Python 路径或跨设备不可用的 `127.0.0.1` 地址。

HTTP MCP 支持 `2025-11-25` 和 `2026-07-28`：

- 旧版支持 `initialize`，采用无协议 session 的可选无状态模式；独立 SSE GET 返回 405。
- 新版每次请求的 `params._meta` 携带协议版本、客户端身份和能力，并校验镜像 HTTP 头 `MCP-Protocol-Version`、`Mcp-Method`、`Mcp-Name`。
- 新版实现 `server/discover`；请求返回单个 JSON 响应，没有协议级 session。工具列表直接调用既有固定库工具权限校验。

工具连接本身只说明记忆可以访问。每轮自动上报需要宿主真正的轮次结束回调，把实际用户原话、最终助手原话、稳定窗口 ID 和轮次 ID 发给 `hook_config.url`。
网关只从回调允许字段构造 `love-house-agent-hook/v1` 事件，复用既有会话绑定和持久回执机制。
MCP 协议 session ID 不会代替宿主窗口 ID。首轮真实完整 hook 才绑定 `next_session`；手动 `memory_record_turn`/`memory_event` 不抢占窗口，也不冒充自动采集。

## 手机页面 API 合同

| 方法和路径 | 请求/响应 |
| --- | --- |
| `GET /api/remote/health` | 公开的服务类型、版本、HTTPS origin 和协议版本；没有记忆或凭证 |
| `POST /api/remote/admin/login` | `{admin_token}` → `{authenticated, csrf_token}` 和管理员 cookie；严格同源 |
| `GET /api/remote/admin/session` | cookie → `{authenticated, csrf_token}`，供同源页面刷新防伪令牌 |
| `POST /api/remote/admin/logout` | cookie + Origin + CSRF，注销并清除 cookie |
| `GET /api/remote/admin/libraries` | cookie → `{libraries, selected_id}` |
| `GET /api/remote/admin/connections` | cookie → `{connections}`，公共状态不含 token |
| `POST /api/remote/admin/connections` | cookie + Origin + CSRF；`{name,library_id,session_scope}`，范围默认 `next_session` |
| `GET /api/remote/admin/connections/{cid}/config` | cookie → 当前连接的远程 MCP 配置和安装说明 |
| `POST /api/remote/admin/connections/{cid}/enabled` | cookie + Origin + CSRF；`{enabled}` |
| `POST /api/remote/admin/connections/{cid}/disconnect` | cookie + Origin + CSRF；撤销连接，原记忆保留 |
| `POST /mcp/{cid}` | 固定连接的 Bearer；JSON-RPC 请求 |
| `POST /api/remote/connections/{cid}/events` | 固定连接的 Bearer；真实宿主 hook 字段 |
| `GET /api/remote/connections/{cid}/status` | 固定连接的 Bearer；真实工具/自动上报状态 |

共享 `/app/` 的 `/api/connections` 创建和 `/api/connections/{cid}/config` 回读也由网关返回远程配置。
其他开放的业务 API 在管理员校验后仅代理到本进程自己的本机控制器；`/api/adapters/harness` 等不在白名单中。

## 验证

`python3.12 -m unittest tests.test_remote_gateway -v` 使用临时自签测试证书和隔离记忆目录，实际发出 TLS/HTTP 请求。
覆盖双版本 MCP、Origin/CSRF/cookie、Bearer 越权、连接/库隔离、真实 hook 原话存档、真实窗口绑定、外窗拒收、暂停/撤销、手动记录状态、管理代理及 0.8 业务写回读。
测试没有访问用户服务、真实对话、模型凭证或付费模型。

协议来源：[2025-11-25 Streamable HTTP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)、
[2026-07-28 Streamable HTTP](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/streamable-http)、
[2026-07-28 Discovery](https://modelcontextprotocol.io/specification/2026-07-28/server/discover)。
