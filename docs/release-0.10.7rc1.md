# 爱之屋 0.10.7rc1：跟随 DSH 接口更新

本版把新版 DSH 兼容改动整合进完整安装包，并修复升级爱之屋后 DSH 配置目录仍保留旧适配器的遗漏。

## 连接与升级

- 按实际需要的公开接口检查兼容性，版本号只用于说明；兼容的实现更新和新增字段不再因版本白名单被挡住。加载时再次检查安装中的 SDK，识别宿主升级。
- 升级时刷新已有、可核对归属的适配器副本；保留连接身份、记忆库、窗口绑定、暂停状态和待发送记录。用户删除或自定义的配置不擅自重建。
- 已经运行的 DSH 需要重新加载一次插件，才能运行更新后的代码；完成一轮对话后，以实际存档回执确认连接。发现宿主不等于完成自动存档。
- 用户连接的多个窗口可以同时工作；未连接窗口、其他独立库和子代理不会因此获得记忆访问。
- 接口不兼容时给出具体诊断，保留现有配置。自动检查无法保证所有未来破坏性变更都兼容。

## 维护与验证

兼容矩阵覆盖已支持旧版、0.2.2-rc.1 和更新通道 0.2.2-rc.2。每日检查分别跟踪官方 npm 的 latest 和 next，解析精确 CLI/SDK 版本，用临时 profile 和本机合成模型运行真实官方 CLI；无付费模型调用，不读取用户记忆。检查结果在 GitHub Actions 可见。

受测运行源码为 `4a61140d0c220c41ace2aea0f9cbd0a28b0cf29d`。本机 Python 全套 1425 项通过（10 项条件跳过），JavaScript 334 项通过，桌面源码 24 项通过（12 项平台跳过），适配器 47 项通过。公开源包另行扫描、生成逐文件清单；最终说明提交与受测程序的运行文件和构建输入按 Git 内容及文件模式核对一致。

- [Python3.11／3.12／3.13 与浏览器 CI](https://github.com/myflww/love-house/actions/runs/43369845358)通过；没有读取真实用户记忆和凭据，付费模型调用0次。
- [DSH 七组兼容矩阵](https://github.com/myflww/love-house/actions/runs/43369845347)首次全部通过：0.2.1-rc.3、rc.5 的 Linux；0.2.2-rc.1 的 Linux／Windows；0.2.2-rc.2 的 Linux／Windows／macOS。14个真实 CLI 连接用例检查完整轮次、原话、回复和外部窗口排除。实际版本、附件摘要和行为记录见[核验汇总](dsh-0107-evidence/compatibility-ci-summary.json)。
- [Windows 完整包验收](https://github.com/myflww/love-house/actions/runs/43369845850)包含打包、原生应用、实际安装、0.10.6→0.10.7 覆盖升级，以及去除开发 PATH／污染环境下的安装件和便携件运行。完成后的原始结果与来源记录在发布资产 `Windows-0107-verification.json`；CI 主机预装 WebView2，不代表全部 Windows 系统或损坏运行时已验证。
- [macOS 完整包验收](https://github.com/myflww/love-house/actions/runs/43369845369)通过 AppKit／WKWebView、后端重启、模拟 Keychain、来源及窗口隔离，并分别运行应用本体与 ZIP 解压件。Mac 为 Apple Silicon、macOS13+，ad-hoc 签名，未公证；没有在用户 Applications 目录执行真实旧 App 覆盖升级。见 `macOS-0107-verification.json`。
- [Android 构建与实际仪器测试](https://github.com/myflww/love-house/actions/runs/43369845370)通过 API28／36，源码和主包版本同步为 0.10.7rc1/code5。API36验证完整引擎，API28旧WebView仅验证旧入口和更新提示，不代表旧内核支持完整界面。按照用户安排，原签名设备负责后续签名、签名主包覆盖升级及追加 APK；本轮发布开发交接包和[具体任务书](ANDROID-0107-HANDOFF.md)，不是可安装 Android 新版。当前可安装版仍为 0.10.6rc1。

升级爱之屋后，先打开爱之屋，再重载一次已经运行的 DSH 插件。可核对归属的旧适配器副本会同步更新，保留绑定；不要求重新导入记忆。公开下载逐字节核验另附 `Public-download-verification.json`；Android 开发交接 ZIP 不会被版本检测器当作主程序更新。

没有新增 Intel Mac、Windows ARM64／32 位、Linux 或 iPhone 安装包。完整原签名交接需要另一台设备执行，不能用本轮 unsigned/debug 测试结果代替签名主包的覆盖升级验收。

[兼容机制与维护方法](HARNESS-COMPATIBILITY.md) · [本版下载](https://github.com/myflww/love-house/releases/tag/v0.10.7rc1)
