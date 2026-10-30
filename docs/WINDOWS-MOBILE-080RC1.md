# 爱之屋 0.8.0rc1：Windows 修复版与移动端预览

本次先提供已测试的 Windows 修复版、移动端入口和 Android 原密钥签名交接。macOS 新一轮功能仍在开发；待其跑通后再同步最终功能。这不是 macOS 新版统一验收完成的声明。

## 下载与使用

- Windows x64：下载 `LoveHouse-Setup-0.8.0rc1-Windows-x64.exe` 安装，或使用同版便携 ZIP。用 `Preview-SHA256SUMS.txt` 核对下载；保留已有记忆和备份。修复 Harness 入口被禁用、官方安装位置/配置识别，以及通用 MCP 已连接却没有真实轮次自动采集的问题。
- Android：本次提供 `LoveHouse-0.8.0rc1-Original-Key-Portable-382c5ee.zip` **开发签名交接包**，其中 App 仍未签名，不能直接安装或覆盖旧版。原密钥电脑接手见下一节；当前旧版 APK 保留。
- iPhone / Android 浏览器：[手机网页入口](https://love-house-mobile-myflww.sharp-rice-0090.chatgpt.site)。可添加到主屏幕。手机连接自己的 HTTPS 电脑/服务器，由有 Agent 能力的窗口保存并加载 MCP 配置；手机不探测桌面 Harness。本地离线存档不会因打开远程入口自动上传。完整共用界面使用现代浏览器。
- 自有服务搭建：[私有远程记忆说明](https://github.com/myflww/love-house/blob/382c5ee45f66016af7117c2ad5a9c16cc2a75f9e/docs/PRIVATE-REMOTE-MEMORY.md)。模型 API Key 不需要贴给手机入口。自动存档仍要求宿主交付真实轮次结束事件，工具在线本身不代表自动采集成功。

## 给原 Android 签名电脑的接手任务

1. 下载上述完整签名交接 ZIP，核对 SHA-256：`321f26138739efe006ac40ac921fcb9768dcfc6c6657ce3f891a5edddb9b7051`。
2. 解压后从包内 `README-先读这里.md` 开始，使用包内脚本和命令。该脚本包含 instrumentation / signer jar 模式，请勿与仓库旧脚本混用。
3. 使用这台电脑上原有发行密钥和 alias。私钥、keystore 和密码留在原电脑，不上传 GitHub，不发送到聊天。密码由本机终端隐藏询问。
4. 需要 Python 3.11+、Java 17+、Android SDK Build-Tools 36.0.0。包内已带经校验的官方 `apksigner.jar` 及上游通知；`aapt` / `zipalign` 使用该电脑的 SDK。
5. 按 README 分别签署 App APK 和开发验收 test APK，返回两份 APK 及各自 verification JSON；test APK 不作为用户安装包发布。
6. 对最终签名的 APK 完成 API28/API36 instrumentation，并在保留旧 App 的设备/模拟器上验证覆盖安装与记忆保留。**不要先卸载旧 App**。通过后才能发布可覆盖升级的 Android APK；本次不宣称这一步已完成。

固定身份：包名 `io.github.myflww.lovehouse.preview`，versionName `0.8.0rc1`，versionCode `2`（旧版为 `1`）；原证书 SHA-256 必须为 `ca4b184194816fe3617feaa841e11b47f5a9a9a00493e8cbc015210c04a3a4cc`。工具会拒绝错文件摘要、包名或证书，不生成新密钥。该交接包只适用于本次固定字节；后续新版本需重新生成交接包。

## 已验证的范围

源码候选：[`382c5ee45f66016af7117c2ad5a9c16cc2a75f9e`](https://github.com/myflww/love-house/commit/382c5ee45f66016af7117c2ad5a9c16cc2a75f9e)。CI 实际合并 checkout：`730cfb01d70d2eda62104c5ad8e46eac1e355069`。发布提交只增加交接材料和发布流程，不修改生产源码；附件从原 CI 下载并逐一核验 SHA-256，没有重新构建后冒用旧测试。

- [Windows 安装包、原生界面、桥接与安装后验证](https://github.com/myflww/love-house/actions/runs/41021442101) 已通过；本机 Windows ARM 虚拟机另有官方 Harness rc3/rc5 的源码连接验证。最终冻结安装包本轮没有重新安装到这台 ARM 虚拟机，支持的发行文件为 x64。
- [Android API28/API36 离线 APK](https://github.com/myflww/love-house/actions/runs/41021442251) 各 6 项真实测试通过；[Android HTTPS/MCP/真实轮次回调](https://github.com/myflww/love-house/actions/runs/41021442000) 通过。
- [iOS Simulator WKWebView HTTPS/MCP/真实轮次回调](https://github.com/myflww/love-house/actions/runs/41021442140) 通过；这是模拟器结果，尚不等于所有实体 iPhone 机型验收。
- [跨平台官方 Harness CLI](https://github.com/myflww/love-house/actions/runs/41021442002) 和 [完整回归](https://github.com/myflww/love-house/actions/runs/41021442005) 通过。已验证官方 rc3/rc5；未来版本需通过运行时兼容性检查，不承诺未来任意 API 变更都自动兼容。

本版本为独立预发布，旧稳定版、历史 Release 与 macOS 安装包保持原有状态。完整源码变更见 [Windows PR #4](https://github.com/myflww/love-house/pull/4) 和 [移动/共用服务 PR #5](https://github.com/myflww/love-house/pull/5)。许可、作者署名和第三方通知随源码和交接包保留。
