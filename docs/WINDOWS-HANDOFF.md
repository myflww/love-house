# 爱之屋 Windows 适配交接

状态：**开发交接，尚未完成 Windows 消费者环境修复，尚未发布 0.5.1。**

## 目标与定位

爱之屋（Love House）是为特定个人 Agent 保存长期记忆的本地软件。它不是聊天客户端。保持独立存档、固定连接归属、默认单窗口、原始对话与整理结果分开、来源可追溯。外观维持像素可爱风，只有神经星图区黑色。

本次范围只修复 Windows 用户从 GitHub 下载后打不开的问题，优先修正常启动和依赖分发，不重做记忆引擎、图谱或 macOS。

公开仓库：https://github.com/myflww/love-house

专用交接分支：`codex/windows-handoff-20261029`

交接代码：https://github.com/myflww/love-house/tree/codex/windows-handoff-20261029

已发布版本：https://github.com/myflww/love-house/releases/tag/v0.5.0

发布基线提交：`18b80cd90ec2b1aa73568ba54cb290a70ca3757d`。

当前源码版本仍是 `0.5.0`；拟修复版为 `0.5.1`，版本和发布标识尚未同步。服务协议维持 `0.4.0`，不跟随产品补丁版本随意改动。

## 用户真实反馈

另一名用户在 Windows 上下载运行后看到旧版通用错误框：

> 爱之屋未能打开。若另一窗口已经打开，请切回该窗口。本程序需要微软 WebView2 Runtime，请从微软官方页面安装后重试。现有记忆数据已保留。

对方系统只确定大致为 Windows 10 或 Windows 11；具体版本、架构、下载的是安装器还是便携版、真实异常日志均未知。

**截图只能证明进入了通用异常处理，不能证明缺 WebView2 就是唯一根因。** 不要先把依赖全装好后就声称复现和修复了原问题。

## 快照里的实际状态

- `desktop/windows_app.py`、`desktop/windows_diagnostics.py` 已有本地诊断增量：区分已运行、未发现 WebView2、其它失败，保留安全日志，并提供 `--diagnose`。
- `scripts/build_windows.py`、安装器、测试与 CI 也有对应本地增量。它们不等同于 GitHub 上已发布的 0.5.0 安装文件；以快照文件和差异清单为准。
- 当前安装器的 WebView2 检测只查询登记项，缺少时打开微软页面，**没有随包离线组件自动修复**。
- `desktop/windows_prerequisites.py` 与 `desktop/windows_startup.py` **尚不存在**。`runtime_status / repair_runtime` 是拟定接口，不能当成已实现。
- `--consumer-smoke`、`--startup-probe` **尚未实现**。当前可用的开发诊断是 `--diagnose`，它在旧的已发布 EXE 中未必存在，应先构建这份源码。
- 当前 CI 仍以预装 WebView2 为前置条件，仍需补消费者环境验收。
- 本次转交前启动的三个审计子任务均只读审计/接口协调，没有新增代码或发版。快照保留本机已经存在的全部诊断草稿，不把设计讨论冒称完成。

同目录 `docs/WINDOWS-HANDOFF-CHANGES.json` 记录相对发布基线的文件差异；`PUBLIC_SOURCE_MANIFEST.json` 记录本次源码快照的实际 SHA256。交接包另有 Mac 上本次有限测试记录。

## 优先执行顺序

1. **在 Windows 上复现普通启动**。记录 Windows 版本/构建号/架构、下载文件名、安装路径、WebView2 和 .NET 状态。先取得实际异常与阶段；不要清空原用户数据来修复。
2. 审阅现有 `windows_diagnostics.py` 增量，完成安全日志：版本、phase、错误码、exception type、errno/winerror、受控代码位置；不记录聊天、Key、token、环境变量值或完整异常文本。数据目录不可写时，诊断应能退到用户 TEMP。
3. 分开处理：真正重复实例、目录不可写、WebView2 缺失/损坏、CLR/.NET 初始化、打包 DLL 缺失及其它异常。重复实例不能误报 Runtime，也不能移除第一个实例的 ready 文件。检查 `stop()` 不应在服务线程尚未启动时阻塞 shutdown。
4. 完成 Runtime 可靠探测及分发修复，安装后复检可用性；不要只凭 registry key 存在或安装退出码 0 判断成功。
5. 如提供“浏览器兼容模式”，清楚标记为兼容模式，保持同一个单 writer Controller 的完整生命周期；不能打开浏览器后立即退出主进程。退出后才释放 writer/ready。
6. 补真实消费者验证并跑全量回归，全部通过后发布独立 0.5.1，不覆盖 0.5.0 同名文件冒充修复。

## 微软依赖方案（待实施）

优选随安装包提供 **Evergreen x64 离线安装程序**，保持微软后续更新。Fixed Version 更大，并要求项目维护其安全更新，不作为默认方案。

微软官方依据：

- 分发、检测、离线安装器和 per-user 安装：https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution
- Evergreen 与 Fixed Version：https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/evergreen-vs-fixed-version

官方入口：`https://go.microsoft.com/fwlink/p/?LinkId=2124701`。

本机已通过官方 HTTPS 下载过一份 214,884,560 字节的 x64 安装程序；SHA256 为：

```text
1c401b327fbc7bb9731b4e350a2194f083cbc3ede46508d52e1cae6610a39bea
```

最终 URL：

```text
https://msedge.sf.dl.delivery.mp.microsoft.com/filestreamingservice/files/f699d81e-69ce-4b09-aa07-23ff2713045b/MicrosoftEdgeWebView2RuntimeInstallerX64.exe
```

**此文件尚未通过 Windows Authenticode 验证，未在 Mac 执行。** 哈希只能说明所下载字节，不能代替微软签名验证。Windows 打包/修复前应验证签名为 Valid、签名主体为 Microsoft Corporation，再核对预期 SHA256。巨型安装 EXE 不进源码仓库，由构建下载验证后进入安装包。

拟定 bundle 路径：`resources/runtime/MicrosoftEdgeWebView2RuntimeInstallerX64.exe` 与 `resources/runtime/manifest.json`。

拟定接口（均待实现/对齐）：

```text
runtime_status() -> {available, version, source, code}
bundled_installer_status(bundle_root=None) -> {available, verified, code}
repair_runtime(bundle_root=None, timeout=180, force=False)
  -> {ok, code, runtime, exit_code?, restart_required?}
```

检测 Evergreen Runtime 的 GUID：`{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`，核对 HKCU/HKLM、32/64 registry view 的有效 `pv`。再用包内 x64 WebView2Loader 的实际版本探测互证，避免残留登记误判。区分 SDK DLL 与 Runtime。

pywebview 6.2.1 还需要 .NET Framework 4.6.2+，`HKLM\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full` 的 Release 至少 394802；把 CLR 失败与 Runtime 缺失分开。安装流程清楚告知必需微软组件和许可来源，按当前用户安装；便携版由使用者明确点击修复。验签失败不得执行。

## 验收矩阵

- 实际普通入口，默认 `%LOCALAPPDATA%\LoveHouse`，测试用新建隔离假数据根，禁止真实模型与凭据访问。
- 安装位置和 LOCALAPPDATA 含中文、空格。
- 子进程 PATH 没有 Python/Node；额外注入不合适的 PYTHONHOME/PYTHONPATH/PYTHONNET/WEBVIEW2 变量，检查进程内安全处理。
- 首实例持锁时再次启动，只返回 already_running；首实例仍健康。
- 安装版、便携版分别测试；普通用户、无管理员权限场景。
- Runtime 已安装、缺失、损坏、修复取消、修复失败。预装 runner 需明确标 `system_runtime_preinstalled:true`；模拟缺失只能标 `simulated_missing`，不能冒称干净系统实测。
- SDK、GUI 与已安装程序严格要求退出码 0、`ok:true`、`process_complete:true`。不能吞异常或只相信旧 report。
- 原有存档、窗口 A/B 隔离、离线补存、备份和导入导出回归，尤其 B 的正文不得进入 A 的文件/队列/日志。

## 文件与构建入口

| 文件 | 用途 |
|---|---|
| `desktop/windows_app.py` | GUI、Controller 生命周期、单 writer、启动入口 |
| `desktop/windows_diagnostics.py` | 当前诊断增量；需审阅、完善、真实验证 |
| `scripts/build_windows.py` | 三个 PyInstaller 产物、许可与 SDK hash gate、安装器 |
| `desktop/windows-installer.iss` | Inno Setup 按用户安装，AppId 保持不变 |
| `desktop/requirements-windows.txt` | 固定 Windows 构建依赖 |
| `.github/workflows/release.yml` | 真实 Windows 打包/安装后验证/发版 |
| `tests/test_windows_packaging.py` | Windows 壳、打包、诊断与清理契约 |
| `nkb/service/agent_client.py`、`host.py` | 已有窗口隐私和固定存档，非本次重做范围 |

在 Windows 项目目录中：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r desktop\requirements-windows.txt
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe desktop\windows_app.py --diagnose
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m unittest discover -s desktop -p 'test_*.py' -v
.\.venv\Scripts\python.exe scripts\build_windows.py
```

需要官方 Inno Setup 6 编译器。普通使用者安装最终 EXE 不需要自己安装 Python 或 Node。

## 必须保留的约束

- Windows 记忆数据目录 `%LOCALAPPDATA%\LoveHouse`，卸载不删个人记忆。不得为“能启动”重置或迁移成空库。
- 默认单窗口，本机队列前过滤 + 服务端复核；连接固定存档；不能退回无标识全窗口采集来掩盖错误。
- API Key 留在系统凭据保管库，导出与日志不带密钥、token 或真实对话。交接包不带任何个人存档和凭据。
- macOS 已安装程序、Mac 用户数据及 Harness profile 不在本次范围内。
- `LICENSE` 为 PolyForm Noncommercial 1.0.0，保留作者 myflww 的 `NOTICE`，第三方原许可继续保留。
- `.gitattributes` 保持精确字节，不能通过放宽 SDK/许可证 SHA 校验来通过 CI。
- 测试后再同步产品版本/安装器/工作流/说明为 0.5.1。不要把协议版本 0.4.0 当产品版本改掉，不发布未经消费者环境验证的“修复版”。
