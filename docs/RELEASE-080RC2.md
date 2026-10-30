# 爱之屋 0.8.0rc2 · WorkBuddy 连接修复预览

本次根据 Windows WorkBuddy 5.9.3 的接入复盘改进第二种 Agent / MCP 连接方式。MCP 工具连通、来源窗口绑定和收到宿主记录分别显示，不再将一次手工 Hook 视为持续自动存档已开启。

## 下载

| 系统 | 文件或入口 | 范围 |
| --- | --- | --- |
| Windows 10（2004+）/ Windows 11 x64 | `LoveHouse-Setup-0.8.0rc2-Windows-x64.exe`；`LoveHouse-0.8.0rc2-Windows-x64.zip` | 安装版与便携版；无需自行安装 Python / Node |
| Android 8.0+ | `LoveHouse-0.8.0rc2-Android.apk` | 原持久私钥签名，包名不变，versionCode 3；先备份后直接覆盖安装，不要卸载旧版 |
| iPhone | [Safari 主屏幕版](https://love-house-mobile-myflww.sharp-rice-0090.chatgpt.site) | 网页应用；分享 → 添加到主屏幕，没有 IPA 包 |
| macOS Apple Silicon | [现有 0.5.0 稳定包](https://github.com/myflww/love-house/releases/tag/v0.5.0) | 本次仅提供更新交接书，新版 `.app` 尚未完成 macOS 本机验收 |

源码归档不是安装包。Windows 未附商业发行商代码签名；Android 发行签名与 Windows 代码签名是两件事。核对本次发布的 SHA-256 文件及来源。

## 本次变化

- WorkBuddy 专用 MCP 配置合并：显示实际配置路径，保留其他连接器、备份旧文件并回读检查。提供信任入口与工具未刷新的重载 / 重启指引。
- 配置文件不存在时，Bridge / Hook 输出结构化修复提示，不输出凭据或配置正文。
- 分离连接策略与绑定窗口，增加实际读写能力和等待绑定时的下一步指引。MCP 手动补录不会抢占窗口。
- 展示 Hook 次数、最近接收时间及条件性接收状态；未验证的 WorkBuddy 桌面 Hook 设置不作为自动安装方案。
- 确认后重新绑定：保留历史记忆、轮换凭据，使用独立的新配置及队列。旧窗口不能取得新配置凭据。
- 本地连接管理 API 需要界面会话；手机远程管理继续要求管理员登录与 CSRF。此保护不等于同一用户下的本机进程隔离。
- Windows 数据目录与安装目录明确区分；Harness 检测优先使用实际 LOCALAPPDATA；Android / iPhone 指引同步。

## 验证与已知边界

发布附件 `WorkBuddy-080rc2-verification.json` 记录实际构建源码、CI、原签名升级验证及文件哈希。只有验证过的安装包才会附在此发布页；不要安装开发用 unsigned APK 或测试 APK。

Windows 验证包含后端、原生窗口、安装后运行、中文空格路径及去除开发 PATH 的启动检查。Android 使用 Android 9 / Android 16 模拟器，分别从 `0.1.0-preview1` 和 `0.8.0rc1` 原签名版本覆盖安装，检查原话、回复、标签，并执行实际 WebView / 存储 / 系统文件导出测试。Android 与 iOS 的 HTTPS 服务管理页使用真实模拟器引擎验证。

模拟器与 CI 不能代表所有实体设备。本次没有新增 Windows 10、Android 手机、iPhone 或 macOS WorkBuddy 真机验收承诺；WorkBuddy 桌面端是否连续触发用户 Hook 仍取决于对应宿主版本，工具在线不代表每轮内容已保存。

本机离线手机记忆可以独立使用。连接电脑 / 服务器的同份记忆需要该服务在线，且手机不会读取电脑或其他 App 的窗口内容。

详见同页附件 `WORKBUDDY-CONNECTION.md` 与 `MACOS-080RC2-WORKBUDDY-HANDOFF.md`，或分支中的同名文档。原创代码继续遵守 PolyForm Noncommercial 1.0.0，保留 myflww 署名及所有第三方许可。
