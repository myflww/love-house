# 给 Windows 电脑上新 Codex 任务的首条消息

请在这台 Windows 电脑接手爱之屋（Love House）的 Windows 启动兼容修复，并完成验证与后续交付。

先从 GitHub 专用交接分支获取最新源码，不要只取 main 的旧发布基线：

```powershell
git clone --branch codex/windows-handoff-20261029 --single-branch https://github.com/myflww/love-house.git love-house-windows
cd love-house-windows
```

如本机已有未提交工作，先检查并保护它，不要使用 reset --hard 或清理个人文件。后续从这个交接分支派生 `codex/windows-051-fix` 工作分支。

先读取 `docs/WINDOWS-HANDOFF.md`、`docs/WINDOWS-HANDOFF-CHANGES.json` 和 `PUBLIC_SOURCE_MANIFEST.json`，核对本机快照。公开仓库是 https://github.com/myflww/love-house ，已发布基线是 0.5.0 / commit 18b80cd90ec2b1aa73568ba54cb290a70ca3757d。当前快照有尚未发布的 Windows 诊断增量，仍标 0.5.0；0.5.1 未完成。

真实用户在 Win10 或 Win11 下载后，只看到“爱之屋未能打开，可能已运行或需要 WebView2”的通用错误。具体系统、包类型及真实异常未知；不要直接认定只缺 WebView2。请先在这台 Windows 电脑复现普通启动，读取真实系统/运行时事实，完善安全启动日志并取得准确错误类型和阶段，再完成依赖检测、安装修复和打包。

当前已有 `windows_diagnostics.py` 与 `--diagnose` 草稿，先审阅、保留有用改动。`windows_prerequisites.py`、`--consumer-smoke`、`--startup-probe` 等只是交接里的计划，不能假设已经存在。根据源码实际情况实现。可安装/配置必要的官方开发依赖，涉及新凭据、系统许可或工具审批时按当前环境规则处理，不绕过系统保护。

建议安装器携带经微软 Authenticode 与 SHA 核验的 x64 Evergreen 离线安装程序，向用户说明后仅缺失时按用户安装；便携版提供明确修复入口。区分已运行、权限/路径、WebView2、.NET/CLR、打包依赖等错误。兼容模式必须保持单 writer 服务生命周期。

验收请覆盖真实普通启动、中文/空格安装与用户数据路径、没有开发环境 PATH、环境污染、重复启动，以及运行时存在/缺失/损坏/修复失败。预装 WebView2 的 CI 或模拟缺失不能冒称干净系统验证。保留退出码 0 + ok:true + process_complete:true 的严格门禁。

不要清空用户记忆，不读取或上传真实聊天/Key/token，不改默认单窗口和固定存档，不碰 Mac 已安装程序/数据/Harness配置。保持公开、非商用、myflww署名和第三方许可。请先在 `codex/windows-051-fix` 工作分支推进，修复及回归通过后再发布独立 0.5.1 与校验文件，保留 0.5.0 历史和 Mac 稳定版入口。

请先给出根据本机实际结果得出的根因，再完成修复、测试、安装包和发布交付；不要停在猜测、修改源码或仅有 CI 预装环境的成功上。
