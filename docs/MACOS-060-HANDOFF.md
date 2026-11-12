# macOS 0.6.0 与其他系统同步交接

2026-10-30：本轮先交付 macOS，其他系统由用户在另一台电脑更新。目标是独立 Agent 长期记忆软件，保留既有 Windows 修复和 Android 工作。

代码分支：`codex/macos-060-memory-upgrade`，仓库 `myflww/love-house`。

## 接手顺序

1. 读取 `docs/KIMI-REVIEW-20261030.md`、本文件与 CHANGELOG 的 0.6.0 段落。第三方审计的全套提速数字并未全部复现，不要在发布说明写成已达成。
2. 获取此分支；从当前 Windows/Android 自己的最新工作分支合并或选择本轮提交。不要用本地整个旧目录覆盖 main，也不要硬重置已有工作。
3. 保留 Windows 的运行时离线安装程序、签名/hash检测、单写者启动和消费环境验证；保留 Android 的活动工程与签名/构建流程。本机工作区旧 Windows 草稿不是最新 Windows 成品。
4. 共享改动主要在 `nkb/core/transaction.py`、`companion/{memory,ingestion,persona,structured,handoff}.py`、`ingest/dialogues.py`、`adapters/http.py`、`service/{host,updates}.py` 和 `viz/{builder,web}` 中本次新增组件。其余更改为测试与文档。Mac 原生入口和构建仅改 `desktop/AtlasApp.swift`、`scripts/build_macos.py`。
5. 各系统运行完整后端、前端行为及各自原生安装/启动测试，再发布各自安装包。0.6.0 是产品源码版本；服务协议仍为 0.4.0，个人库结构与旧路径继续兼容。

## 新入口与约束

| 接口/入口 | 用途 | 边界 |
|---|---|---|
| POST `/api/dialogue-import/preview` | 聊天记录只读预览 | `content`、可选 `name` / `format`；4 MiB 原文/2000 条消息 |
| POST `/api/dialogue-import/apply` | 整批导入 | 同预览内容 + `confirm:true` + `expected_fingerprint`；一次事务一次落盘 |
| POST `/api/memory/handoff` | 新窗口摘录 | `profile:S/M/L`；只读，不调用模型，不配置客户端 |
| GET `/api/updates` | 查看版本/触发桌面后台检查 | 不含任何记忆数据；仅 GitHub 公开发布查询 |
| POST `/api/updates/check` | 手动后台检查 | 非阻塞；60 秒最短间隔 |
| POST `/api/updates/settings` | 版本检查偏好 | `auto_check`、`channel:stable/preview` |

前三个接口固定使用请求头中用户选择的存档，不跟随其他窗口或页面选库。它们是桌面管理入口，不授予 Agent 凭据跨库存档权限。新窗口持续记录仍用已有 MCP/宿主钩子，复制摘录只提供这一份资料。

`updates.json` 仅含公开版本缓存和用户更新偏好。稳定通道跳过预览；兼容 SemVer 和既有 `v0.5.1rc1` 标签。资产名应带明确系统与架构，例如 `LoveHouse-0.6.0-macOS-arm64.zip`、`LoveHouse-Setup-0.6.0-Windows-x64.exe`；无匹配包就不推荐错误平台安装包。不自动下载或安装。

## 回归与验收

```sh
PYTHONPATH=.:tests python3.12 -m unittest discover -s tests -v
PYTHONPATH=.:tests python3.12 -m unittest discover -s desktop -p 'test_*.py' -v
```

Windows PowerShell 的 PYTHONPATH 用系统对应语法设置；不要把 Mac 测试通过称为 Windows 实机验收。前端行为测试由 Python 测试调用 Node，需在开发/CI 安装 Node；成品普通用户不需要 Node。

重点验证：大批旧聊天只写一次、磁盘故障完整回滚、相同文件重复跳过、忘记不复活、缺时间不冒充现在、复制前同意、异步切库不泄漏、更新平台/架构匹配、离线/关自动仍可正常存忆。CI / 原生自检关闭真实网络版本检查，版本功能单测用注入 transport，不调用真实模型。

不要上传真实聊天、个人库、API Key、连接令牌或系统凭据。自有部分继续公开下载、PolyForm Noncommercial 1.0.0、保留 myflww 署名，第三方许可独立保留。
