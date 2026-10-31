# 爱之屋 0.9.1rc1 · Windows 分享与整理修复预览

修复 0.8.0rc2 用户反馈的两个问题，并接入另一台设备 Windows 交接书中的 0.9 共享功能。

| 系统 | 当前下载 | 状态 |
| --- | --- | --- |
| Windows 10 2004+ / 11 x64 | 本页 EXE 安装版或完整 ZIP 便携版 | 新修复预览 |
| macOS Apple Silicon | [0.9.0 发布页](https://github.com/myflww/love-house/releases/tag/v0.9.0) | 独立 macOS 版本 |
| Android | [0.8.0rc2 原签名 APK](https://github.com/myflww/love-house/releases/download/v0.8.0rc2/LoveHouse-0.8.0rc2-Android.apk) | 保持现有候选版，可覆盖升级 |
| iPhone | [Safari 主屏幕版](https://love-house-mobile-myflww.haixiac34.chatgpt.site) | 保持现有 0.8.0rc2 PWA |

分享包预览不再依赖整理模型状态；完整 JSON / Markdown 无需 API。预览异常可重试，原生保存区分取消、失败与成功，修复 Windows 保留名及 AstrBot ZIP 导出。

整理任务领取后读取新快照，修复新到原文误报“来源已删除”。配置与凭据先校验再保存；缺配置不白占调用预算；安全区分 API、证书、超时和 JSON 错误。旧失败任务重试时重新核对当前依据，真正遗忘的内容不会恢复。

同步独立助手输出、有依据的整理记忆召回、实际来源统计、连接帮助、AstrBot 0.2.0 和 Harness 0.4.1；保留 Windows / WorkBuddy 既有启动、窗口重绑定和鉴权修复。工具在线或一次 Hook 不能证明持续自动存档。

升级前关闭应用，保留 `%LOCALAPPDATA%\LoveHouse`；便携版完整解压。核对同页 SHA256。完整修复、测试与限制见 [Windows 说明](https://github.com/myflww/love-house/blob/v0.9.1rc1/docs/WINDOWS-091-FIXES.md) 和附件 `Windows-091-verification.json`。测试使用临时库和模拟 API，没有读取用户密钥或产生真实模型费用；不能代表所有电脑和实际 DeepSeek 账户已验证。

主程序未附发行商代码签名；随包微软运行时组件单独验证微软签名与散列。公开提供自有源码与下载，PolyForm Noncommercial 1.0.0，保留 myflww 署名与第三方许可。此次不覆盖既有平台发布资产。
