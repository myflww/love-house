# macOS：WorkBuddy 连接修复交接

## 目标与基线

本次从 Windows / Android 已发布的 `v0.8.0rc1` 源码（`d4130f8aec3882a30a7d237a5d29122509a2dc0d`）修复第二种 Agent / MCP 连接方式，候选版本为 `0.8.0rc2`。同步分支：`codex/workbuddy-connect-080rc2`。macOS 的独立功能开发分支仍需保留，不应直接用 Windows 分支覆盖整个项目。

```sh
git fetch origin codex/workbuddy-connect-080rc2
git diff v0.8.0rc1..origin/codex/workbuddy-connect-080rc2 -- nkb desktop/agent_memory_bridge.py desktop/agent_memory_hook.py desktop/harness_bridge.py extensions/deepseek-harness/configure.py scripts/configure_agent_source.py tests
```

先查看该分支的实际提交与测试结果，再按下列范围同步，解决 macOS 当前开发分支的冲突。不要导入 Android 密钥、Windows 打包产物、真实用户记忆或宿主聊天记录。

## 需要同步的行为

- MCP 配置必须引用运行服务实际生成的连接配置文件；提供完整路径复制及配置文件缺失的可操作诊断。macOS 使用自身用户数据目录，不能硬编码 Windows 的 `%LOCALAPPDATA%`。
- WorkBuddy 配置按宿主类型生成和回读，保留已有连接器。提示信任连接器；工具列表未刷新时提示重载或重启。不要把 CodeBuddy CLI / IDE 的 Hook 文档当作 WorkBuddy 桌面端用户设置已受支持的证据。
- 连接策略与绑定结果分离：`session_scope_policy` / 枚举语义的 `session_scope` 和 `bound_session_id` 分别表达策略与来源。迁移旧连接必须保留原窗口隔离，不能将原会话 ID 当作任意窗口策略。
- 可读、可写能力分别报告。等待首次来源绑定时，写入错误应带下一步动作；MCP 手动补录不能认领窗口。
- 收到一次 Hook 事件，只报告收到事件及最近时间、数量。持续记录依赖宿主继续调用；不能将手工探针标为已验证全自动。
- 重新绑定必须由管理界面明确确认；保留历史记忆，作废旧连接凭据，重新生成目标窗口配置。旧窗口不得继续写入。
- 本地连接管理 API 的会话鉴权、远程管理已有认证和 CSRF 保护必须一起同步。此举阻止匿名 API 枚举，不承诺抵御能够以同一用户运行并打开本地管理界面的恶意进程。
- 同步 `desktop/harness_bridge.py` 的旧 MCP 兼容修复：状态工具改由固定记忆库的目录身份与统计核对，不再直接读取受保护的管理状态接口，也不申请管理 Cookie 或列出其他连接。缺少这项会导致旧桥接的 `memory_status` 返回 401。
- 同步桌面连接向导与 `remote-mobile` 手机服务管理页；手机管理页不应残留一次事件即自动连接的文案。
- 更新 `scripts/build_macos.py` 的内嵌自检：`smoke_agent` 中完整 Hook 后仍应断言 `automatic_memory` 为 false，并核对 `host_reported`；窗口测试应断言枚举策略与独立 `bound_session_id`，不能再比较 `session_scope == 会话 ID`。三处本机 HTTP 自检辅助函数访问受保护的连接管理接口前，要通过根页面获取界面 Cookie 或使用同进程管理身份，不要关闭鉴权来让自检通过。这些 macOS 打包自检尚未在本次 Windows 环境改写或执行。

## macOS 上必须完成的验收

1. 在有空格及中文的用户数据目录启动源码服务和打包后的 `.app`；检查 bridge / hook 的实际路径与执行权限，不依赖开发机 Python PATH。
2. 安装到 WorkBuddy macOS：回读 MCP 配置并保留其他连接器；信任后确认 `memory_status` / `memory_bootstrap` 正常。记录 WorkBuddy 版本，不能沿用 Windows 5.9.3 的宿主支持结论。
3. 使用虚构会话上报，验证未绑定时返回指引；手工 MCP 补录不会占用窗口；绑定后其他会话不能写入。
4. 仅发送一次手工 Hook，确认界面没有宣称以后会自动存档。只有实际宿主回调才能作为持续接收的证据；不支持的配置位置应明确显示未验证。
5. 从 `0.8.0rc1` 旧格式连接迁移，核对策略、绑定与记忆数量。重新绑定后旧 token 失效、新窗口可接收，原记忆文本不变。
6. Safari / iPhone 主屏幕管理页验证登录、CSRF、状态刷新与重新绑定；管理 token 不应进入 URL、日志、浏览器持久存储或服务工作线程缓存。
7. 在 macOS 执行 Python 和 JavaScript 回归，再构建 `.app`，完成首次启动、退出重开、实际配置文件读写及覆盖升级测试。签名、公证与分发说明需按已有 macOS 发布流程处理。

通用回归命令（以分支当前测试名称为准）：

```sh
PYTHONUTF8=1 python3 -m unittest discover -s tests -v
PYTHONUTF8=1 python3 -m unittest discover -s desktop -p 'test_*.py' -v
node --test tests/js/*.test.cjs
node --test mobile/tests/*.test.mjs
python3 -m unittest discover -s mobile/tests -p 'test_*.py' -v
python3 scripts/build_macos.py
```

## 证据与限制

Windows 与移动候选的最终构建号、源码提交和 CI 结果以本分支发布说明 `docs/RELEASE-080RC2.md` 及发布附件 `WorkBuddy-080rc2-verification.json` 为准。本文件不是 macOS 新安装包的验收证明；macOS 原生 `.app`、macOS WorkBuddy 及 iPhone 真机仍需由接手电脑验证。现有 macOS 下载不得在完成上述验收前改标为已包含本次修复。

用户复盘只作为诊断依据。本文已省略其真实连接、会话与记忆库标识，以及本机临时路径。
