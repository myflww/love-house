# Windows 适配验证记录

日期：2026-10-30（Asia/Shanghai）。基于交接分支提交 `22750fb408370de4abed6988aa178f01eebc5bb2`。

第一轮本机二进制验收保留了 0.5.0 版本号，下面的本机资产校验记录对应那次测试包，不是已发布的 v0.5.0 原包。
当前 Windows 修复预览使用独立产品版本 **0.5.1rc1**，服务协议保持 0.4.0；通过 CI 后单独发布预览包，并从公开地址重新下载验收，保留 0.5.0 与 Mac 历史文件。
Windows 10 及干净 Windows 10/11 缺失或损坏 Runtime 的实测仍待完成，0.5.1 正式稳定版保留该门槛。公开版本与文件选择见 [下载与系统支持](下载与系统支持.md)。

## 已确认的问题与修复

- 第二实例清理会删除首实例 ready 文件；现在只有持锁实例能删除自己的状态。
- HTTP 服务线程未启动时调用 shutdown 会永久等待；现在按线程状态关闭 socket。
- 运行时登记或文件存在不代表可用；现在以包内 x64 WebView2Loader 的版本探测为准，注册表只作辅助。
- 微软 Runtime 原先需要用户另行下载；现在安装包、便携包均携带经过固定 SHA256 和微软有效数字签名核验的 Evergreen x64 离线安装器。
- WebView2 初始化失败可能只被上游记录而不抛异常；现在启动等待有上限，退出时释放服务并记录安全阶段。
- 日志目录不可写时原先没有有效诊断；现在退回用户 TEMP，诊断显示实际日志位置，隐藏用户名路径及异常原文。
- 原有 legacy MCP 入口依赖系统代码页；现在三个 stdio 入口均明确 UTF-8 和 LF，中文及 emoji 原文保持完整。
- 测试关闭后 Chromium 缓存可能仍并发写入；仅对有所有权标记的隔离 WebView2 目录做有限重试，其它权限、磁盘及路径错误仍失败。

## 本机实测范围

Windows 11 x64，构建号 26200；.NET Framework Release 533509。
任务开始时系统已预装 WebView2 156.0.4314.50：`system_runtime_preinstalled: true`。
原反馈用户的系统版本、下载包和异常仍未知，不能把本机结果当作原报错唯一根因的证明。

构建使用官方 CPython 3.12.10 x64 NuGet 分发，解释器数字签名为 Python Software Foundation 且有效；安装器使用官方 Inno Setup 6.7.4。
构建依赖按 `desktop/requirements-windows.txt` 固定；SDK 和第三方许可证的原始字节校验保持开启。

已完成：普通 EXE 入口显示实际原生界面；独立中文及空格 LOCALAPPDATA 路径；重复启动只提示已运行，首实例 ready 与健康检查不受影响；打包后端、MCP/Hook、分享导入、重启；页面健康检查、保存桥、图谱和 WebGL。

消费者冒烟还覆盖了便携程序目录及临时目录含中文和空格、PATH 无 Python/Node、外部 PYTHONHOME/PYTHONPATH/PYTHONNET/WebView2 变量污染。所有成功报告同时要求退出码 0、`ok: true`、`process_complete: true`；旧报告先删除。

官方 Inno 安装包已在非提权账户下安装到中文及空格目录，退出码 0；已安装程序的 backend、native、consumer 和 runtime 四项均为退出码 0、`ok: true`、`process_complete: true`。卸载退出码 0，隔离目录中的假记忆哨兵文件字节保持完整。

源码全量回归 526 项，4 项因 POSIX 或符号链接权限条件跳过，其余通过；desktop 回归 19 项，12 项原有 POSIX 检查跳过，其余通过。最终两项审阅修复后另跑 Windows 专项 69 项全部通过。缺失/失败分支保持模拟标记。

测试只使用新建的隔离假数据，没有真实模型调用或个人凭据访问；个人存档、默认单窗口、固定存档归属、许可证和署名保持不变。

## 尚待完成的实机验收

- 干净 Windows 10/11 x64 上实际缺失 Runtime 的安装、自动修复和复检。
- 实际损坏 Runtime、修复失败或取消、受限安装策略、重启要求等消费者场景。
- 已有个人存档的升级验收应由副本验证，不能清空或移动原库。

已有模拟测试覆盖缺失、残留登记、损坏探测、验签失败、超时、取消和安装后仍不可用；这些只能标作模拟结果。
GitHub Windows runner 也可能预装 Runtime，因此普通 CI 成功不代替上述验收。发布工作流要求显式启用并提供消费者验收记录，禁止覆盖已有同名文件。

## 使用与复查

安装包按当前用户安装；卸载不删除 `%LOCALAPPDATA%\LoveHouse`。
便携版先完整解压，再打开 `LoveHouse.exe`，不需要另装 Python 或 Node。
缺少 Runtime 时会询问是否安装随包的微软组件。明确执行 `LoveHouse.exe --repair-runtime` 可以对可探测但初始化异常的 Runtime 尝试重装修复。
`LoveHouse.exe --diagnose` 生成不含记忆、Key、token 或对话原文的诊断。

开发验证命令：

```powershell
python -m unittest discover -s tests -v
python -m unittest discover -s desktop -p 'test_*.py' -v
python scripts/fetch_windows_runtime.py
python scripts/build_windows.py --iscc '你的 Inno Setup 6 路径\ISCC.exe'
```

安装版和便携版均可执行 `LoveHouse.exe --consumer-smoke --report <新报告路径>`；它显示测试窗口并使用独立假数据，结束后才提交最终结果。
