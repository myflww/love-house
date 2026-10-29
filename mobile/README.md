# 爱之屋移动预览

移动版与桌面版共用单库分享 JSON 格式，界面和记忆保存在设备本地。`web/` 是 Android APK 与 iPhone 主屏幕网页共用的静态应用；没有后端、账号、云同步或模型调用。

本预览支持：

- 多个独立记忆库，手动记录原文、回复与标签。
- 编辑、删除、关键词检索和标签关联星图。
- 桌面单库分享 JSON 导入、JSON 备份与 Markdown 阅读导出。
- IndexedDB 原子保存，关闭后继续使用；浏览器版本首次加载完成后可离线打开。

桌面的 Agent 自动接入、Harness 配置、模型整理、回收站和完整神经图引擎仍属于桌面版。移动星图只展示标签关系，最多显示 80 个节点；完整记录仍可搜索和导出。导入不会执行文件里的连接、密钥或模型配置。

Android 原生壳位于 `../android/`，没有互联网、录音、相机或广泛存储权限。系统文件选择器用于用户主动导入与备份。卸载 APK 或清除应用数据会删除本机记忆，升级前请导出 JSON；只有相同包名与签名的覆盖安装才能保留旧数据。

iPhone 使用 Safari 打开部署地址，再点分享 → 添加到主屏幕。从主屏幕图标重新打开后再保存记忆；Safari 标签页和主屏幕应用的数据空间可能不同。清除网站数据、卸载主屏幕应用或系统回收网站存储可能丢失数据，请定期导出 JSON。这里提供的是主屏幕网页应用，不是原生 IPA。

## 本地开发

用 Python 3 启动静态预览：

```sh
python -m http.server 8301 --bind 127.0.0.1 --directory mobile/web
```

服务工作线程需要 HTTPS 或本机 localhost 安全来源。通过局域网 HTTP 打开的页面不能验证离线安装能力。正式部署须把根目录的 `LICENSE`、`NOTICE`、`THIRD_PARTY_NOTICES.md` 一并复制到网页目录；字体许可位于 `web/assets/ark-pixel-OFL.txt`。

存储和实际桌面格式互通检查：

```sh
node --test mobile/tests/store.test.mjs
python mobile/tests/test_desktop_interop.py -v
```

## Android 构建

需要 JDK 17、Gradle 8.13、Android SDK 36 / Build-Tools 36.0.0 和 Python 3。默认最低 Android 8.0（API 26）；请保持 Android System WebView 更新。

```sh
python scripts/prepare_mobile_assets.py
gradle -p android :app:assembleDebug :app:assembleDebugAndroidTest :app:assembleRelease :app:lintRelease
gradle -p android :app:connectedDebugAndroidTest
python scripts/check_android_test_results.py
```

Windows 可把 `LOVE_HOUSE_BUILD_PYTHON` 设为正常 Python 的完整路径。`assembleRelease` 只生成未签名开发产物，不能当作可安装下载包。发行 APK 必须使用仓库之外保存的持久私钥签名，再验证该签名文件的安装与回归。任何密钥、签名口令、真实记忆和本地 SDK 路径都不应进入仓库、网站或 CI 产物。

项目继续采用 PolyForm Noncommercial 1.0.0，保留 myflww 作者署名和第三方许可。
