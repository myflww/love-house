# 爱之屋 0.5.1rc1 · Windows 公开预览

本次提供独立的 Windows x64 修复预览版。Windows 11 x64 已完成实机启动、安装版和便携版验证；Windows 10 2004 及以上版本仍待实机验证。干净系统上缺失或损坏 WebView2 的完整验收仍在进行，因此此版本保留为预览版。

## 下载与系统版本

| 系统 | 版本与下载 | 验证状态 |
|---|---|---|
| Windows 11 x64 | [0.5.1rc1 安装器](https://github.com/myflww/love-house/releases/download/v0.5.1rc1/LoveHouse-Setup-0.5.1rc1-Windows-x64.exe) · [便携 ZIP](https://github.com/myflww/love-house/releases/download/v0.5.1rc1/LoveHouse-0.5.1rc1-Windows-x64.zip) | 已做本机实测，公开下载包另由独立 CI 下载复验 |
| Windows 10 x64，2004 起 | 同上 | 仍待 Windows 10 实机验证 |
| macOS | [0.5.0 稳定版](https://github.com/myflww/love-house/releases/tag/v0.5.0) | 延续原稳定版，本次不替换其文件 |

[Windows SHA256 校验文件](https://github.com/myflww/love-house/releases/download/v0.5.1rc1/Windows-SHA256SUMS.txt)。下载后运行安装器；便携版请完整解压 ZIP 后打开 `LoveHouse.exe`。普通使用者无需安装 Python 或 Node。

## 本次修复

- 随包提供微软 Evergreen x64 WebView2 离线安装程序，执行前核验固定 SHA256 和微软有效签名。安装器检测实际 Loader 可用性，缺失时明确提示修复，并在安装后再次检测。
- 区分重复启动、数据目录权限、WebView2、.NET/CLR 和打包依赖错误；修复服务清理卡住及第二实例破坏首实例状态的问题。
- 提供 `LoveHouse.exe --diagnose` 安全诊断和 `LoveHouse.exe --repair-runtime` 明确修复入口，支持中文和空格路径，并处理干扰启动的环境变量。
- 保留 `%LOCALAPPDATA%\LoveHouse` 记忆目录、卸载保留记忆、默认单窗口隔离和原有非商用许可。

公开发布后，工作流会在另一台 Windows runner 上匿名下载安装器、ZIP 和 SHA256 文件，校验字节、安装并运行后端及原生界面测试。若复验失败，该预览会被转回草稿。CI 的预装 Runtime 状态会如实记录；它不代表干净 Windows 消费者环境验收已经完成。
